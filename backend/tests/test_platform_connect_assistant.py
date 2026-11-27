import json
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.assistant.llm import LLMProvider, LLMReply, ToolCall, set_provider_override
from app.assistant.models import Reminder
from app.assistant.service import deliver_due_reminders
from app.connect.adapters import set_http_factory
from app.core.security import hash_password
from app.tenants.models import User
from tests.conftest import add_member, register

TODAY = date.today().isoformat()


def _root(client, db):
    db.add(User(email="root@manima.co.in", password_hash=hash_password("Sup3rSecret99"), full_name="Root", is_superadmin=True))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"email": "root@manima.co.in", "password": "Sup3rSecret99"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _set(client, root, tid, changes, reason="contract change"):
    rev = client.get(f"/api/v1/admin/tenants/{tid}/capabilities", headers=root).json()["revision"]
    return client.patch(f"/api/v1/admin/tenants/{tid}/capabilities", json={"changes": changes, "expected_revision": rev, "reason": reason}, headers=root)


# ---- Entitlements ------------------------------------------------------------------------------------------------
def test_product_entitlements_enforced_on_api(client, db):
    root = _root(client, db)
    a, a_tid, _ = register(client, "Calling Only Co")
    b, b_tid, _ = register(client, "Assistant Only Co")
    c, _, _ = register(client, "Both Co")
    assert _set(client, root, a_tid, [{"key": "product.business_assistant", "enabled": False}]).status_code == 200
    assert _set(client, root, b_tid, [{"key": "product.calling_agent", "enabled": False}]).status_code == 200
    caps_a = client.get("/api/v1/me/capabilities", headers=a).json()["capabilities"]
    assert caps_a["product.calling_agent"] and not caps_a["product.business_assistant"] and not caps_a["assistant.text"]
    r = client.get("/api/v1/assistant/config", headers=a)
    assert r.status_code == 403 and r.json()["error"]["code"] == "capability_disabled"
    assert client.get("/api/v1/agents", headers=b).status_code == 403
    assert client.get("/api/v1/calls", headers=b).status_code == 403
    r = client.post("/api/v1/connect/metrics/run", json={"metric_key": "kokila.calls_summary"}, headers=b)
    assert r.status_code == 403  # assistant cannot read Calling Agent data the client has not bought
    assert client.get("/api/v1/agents", headers=c).status_code == 200
    assert client.get("/api/v1/assistant/config", headers=c).status_code == 200


def test_capability_admin_conflicts_and_controls(client, db):
    root = _root(client, db)
    h, tid, _ = register(client)
    assert client.get(f"/api/v1/admin/tenants/{tid}/capabilities", headers=h).status_code == 403
    stale = client.patch(
        f"/api/v1/admin/tenants/{tid}/capabilities",
        json={"changes": [{"key": "voice.outbound", "enabled": True}], "expected_revision": 999, "reason": "x y z"},
        headers=root,
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    bad = _set(client, root, tid, [{"key": "voice.outbound", "enabled": True}, {"key": "voice.agents", "enabled": False}])
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "dependency_conflict"
    ok = _set(client, root, tid, [{"key": "voice.outbound", "enabled": True}])
    assert ok.status_code == 200 and any(x["key"] == "voice.outbound" and x["effective"] for x in ok.json()["capabilities"])
    assert client.get("/api/v1/campaigns", headers=h).status_code == 200
    # platform-wide kill of a capability wins over the tenant override
    assert (
        client.put("/api/v1/admin/capabilities/voice.outbound/control", json={"enabled": False, "reason": "carrier incident"}, headers=root).status_code == 200
    )
    assert client.get("/api/v1/campaigns", headers=h).status_code == 403
    assert client.put("/api/v1/admin/plans/trial/capabilities", json={"enabled": ["voice.agents"], "reason": "test"}, headers=root).status_code == 409
    actions = [x["action"] for x in client.get("/api/v1/admin/audit-logs", headers=root).json()]
    assert "admin.tenant_capabilities_changed" in actions and "admin.capability_platform_control" in actions


# ---- Kokila Connect / ERPNext ------------------------------------------------------------------------------------
def erpnext_handler(request: httpx.Request) -> httpx.Response:
    if request.headers.get("Authorization") != "token key123:secret456":
        return httpx.Response(401, json={"exc": "auth"})
    path = request.url.path
    if path == "/api/method/frappe.auth.get_logged_user":
        return httpx.Response(200, json={"message": "reports@acme.in"})
    if path == "/api/resource/Company":
        return httpx.Response(200, json={"data": [{"name": "Acme", "default_currency": "INR"}]})
    if path == "/api/resource/Sales Invoice":
        filters = json.loads(request.url.params["filters"])
        if any(f[0] == "posting_date" for f in filters):
            rng = next(f[2] for f in filters if f[0] == "posting_date")
            rows = [
                {"name": "SINV-1", "posting_date": rng[0], "customer": "Ravi", "base_net_total": 1000, "base_grand_total": 1180, "is_return": 0},
                {"name": "SINV-2", "posting_date": rng[0], "customer": "Sita", "base_net_total": 2500.5, "base_grand_total": 2950.59, "is_return": 0},
                {"name": "SINV-3", "posting_date": rng[0], "customer": "Ravi", "base_net_total": -200, "base_grand_total": -236, "is_return": 1},
            ]
            return httpx.Response(200, json={"data": rows})
        rows = [
            {"name": "SINV-9", "customer": "Ravi", "due_date": "2026-01-01", "outstanding_amount": 500},
            {"name": "SINV-8", "customer": "Sita", "due_date": "2026-02-01", "outstanding_amount": 300},
            {"name": "SINV-7", "customer": "Ravi", "due_date": "2026-03-01", "outstanding_amount": 100},
        ]
        return httpx.Response(200, json={"data": rows})
    if path == "/api/resource/Bin":
        return httpx.Response(200, json={"data": [{"item_code": "FILTER-A", "warehouse": "Main", "actual_qty": 2, "projected_qty": 2}]})
    return httpx.Response(404)


@pytest.fixture
def erpnext():
    set_http_factory(lambda: httpx.Client(transport=httpx.MockTransport(erpnext_handler)))
    yield
    set_http_factory(None)


def _connect(client, h, secret="secret456"):
    return client.post(
        "/api/v1/connect/connections",
        json={"connector_key": "erpnext", "name": "Acme ERP", "base_url": "https://erp.acme.test", "credentials": {"api_key": "key123", "api_secret": secret}},
        headers=h,
    )


def test_erpnext_connection_and_metrics(client, db, erpnext):
    h, tid, _ = register(client)
    cat = {c["key"]: c for c in client.get("/api/v1/connect/connectors", headers=h).json()}
    assert cat["erpnext"]["status"] == "not_connected" and cat["tally"]["status"] == "not_available"
    bad = client.post(
        "/api/v1/connect/connections",
        json={"connector_key": "erpnext", "name": "Wrong", "base_url": "https://erp.acme.test", "credentials": {"api_key": "key123", "api_secret": "nope"}},
        headers=h,
    ).json()
    assert bad["status"] == "failed"
    r = client.post("/api/v1/connect/metrics/run", json={"metric_key": "erpnext.sales_total"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "connector_not_connected"  # failed connection is never used
    conn = _connect(client, h).json()
    assert conn["status"] == "connected" and conn["verified_identity"] == "reports@acme.in"
    assert "secret" not in json.dumps(conn)
    assert {c["key"]: c for c in client.get("/api/v1/connect/connectors", headers=h).json()}["erpnext"]["status"] == "connected"
    sales = client.post(
        "/api/v1/connect/metrics/run", json={"metric_key": "erpnext.sales_total", "params": {"date_from": TODAY, "date_to": TODAY}}, headers=h
    ).json()
    kpis = {k["label"]: k["value"] for k in sales["kpis"]}
    assert kpis["Net sales"] == 3300.5 and kpis["Invoices"] == 2 and kpis["Returns"] == 1 and sales["kpis"][0]["unit"] == "INR"
    assert sales["source"]["connector"] == "erpnext" and sales["source"]["records"] == 3
    out = client.post("/api/v1/connect/metrics/run", json={"metric_key": "erpnext.customer_outstanding"}, headers=h).json()
    assert out["table"]["rows"][0] == ["Ravi", 2, 600.0]
    low = client.post("/api/v1/connect/metrics/run", json={"metric_key": "erpnext.low_stock", "params": {"threshold": 5}}, headers=h).json()
    assert low["table"]["rows"][0][0] == "FILTER-A"
    cmp_ = client.post(
        "/api/v1/connect/metrics/run", json={"metric_key": "erpnext.sales_compare", "params": {"date_from": TODAY, "date_to": TODAY}}, headers=h
    ).json()
    assert {k["label"].split(" ")[0]: k["value"] for k in cmp_["kpis"]}["Change"] == 0.0
    # tenant isolation
    other, _, _ = register(client, "Other Co")
    assert client.post(f"/api/v1/connect/connections/{conn['id']}/verify", headers=other).status_code == 404
    r = client.post("/api/v1/connect/metrics/run", json={"metric_key": "erpnext.sales_total"}, headers=other)
    assert r.status_code == 409
    assert client.post(f"/api/v1/connect/connections/{conn['id']}/revoke", headers=h).json()["status"] == "revoked"
    assert client.post("/api/v1/connect/metrics/run", json={"metric_key": "erpnext.sales_total"}, headers=h).status_code == 409


def test_planned_connectors_cannot_be_faked(client):
    h, _, _ = register(client)
    r = client.post(
        "/api/v1/connect/connections", json={"connector_key": "tally", "name": "Tally main", "base_url": "https://t.example.com", "credentials": {}}, headers=h
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "connector_not_available"


# ---- Business Assistant --------------------------------------------------------------------------------------------
class ScriptedLLM(LLMProvider):
    """Deterministic test double: calls a tool for the first turn, then summarises the actual tool output."""

    name, model = "test-double", "scripted-1"

    def chat(self, system, messages, tools):
        last = messages[-1]
        if last["role"] == "tool":
            data = json.loads(last["content"])
            if data.get("kpis"):
                k = data["kpis"][0]
                return LLMReply(f"{k['label']}: {k['value']} {k['unit'] or ''}".strip())
            return LLMReply(f"Tool status: {data.get('status')}")
        text = last["content"].lower()
        names = {t.name for t in tools}
        if "sales" in text and "run_metric" in names:
            return LLMReply("", [ToolCall("c1", "run_metric", {"metric_key": "erpnext.sales_total", "date_from": TODAY, "date_to": TODAY})])
        if "follow" in text and "create_follow_up_task" in names:
            return LLMReply("", [ToolCall("c2", "create_follow_up_task", {"phone": "9845012345", "note": "Call about renewal"})])
        if "remember" in text and "propose_memory" in names:
            return LLMReply("", [ToolCall("c3", "propose_memory", {"content": "Prefers Telugu"})])
        if "sales" in text:
            return LLMReply("", [ToolCall("c4", "run_metric", {"metric_key": "erpnext.sales_total"})])  # not offered in this mode
        return LLMReply("Hello!")


@pytest.fixture
def llm():
    set_provider_override(ScriptedLLM())
    yield
    set_provider_override(None)


def test_assistant_not_configured_is_explicit(client):
    h, _, _ = register(client)
    cfg = client.get("/api/v1/assistant/config", headers=h).json()
    assert cfg["llm"] == {"configured": False, "provider": None, "model": None}
    conv = client.post("/api/v1/assistant/conversations", json={"mode": "business"}, headers=h).json()
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "today's sales?"}, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"


def test_business_mode_uses_real_connector_data(client, erpnext, llm):
    h, _, _ = register(client)
    conv = client.post("/api/v1/assistant/conversations", json={"mode": "business"}, headers=h).json()
    # Without a connection the assistant must report the failure, not invent a number
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "What were today's sales?"}, headers=h).json()
    assert r["content"] == "Tool status: error" and r["artifacts"] == []
    _connect(client, h)
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "What were today's sales?"}, headers=h).json()
    assert r["content"] == "Net sales: 3300.5 INR" and r["provider"] == "test-double" and r["model"] == "scripted-1"
    assert r["artifacts"][0]["type"] == "metric" and r["artifacts"][0]["data"]["source"]["connector"] == "erpnext"
    msgs = client.get(f"/api/v1/assistant/conversations/{conv['id']}/messages", headers=h).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_approval_required_for_writes(client, llm):
    h, _, _ = register(client)
    conv = client.post("/api/v1/assistant/conversations", json={"mode": "business"}, headers=h).json()
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "Create a follow up for Ravi"}, headers=h).json()
    assert r["content"] == "Tool status: approval_required"
    assert client.get("/api/v1/leads", headers=h).json()["total"] == 0  # nothing written before approval
    action = client.get("/api/v1/assistant/actions", headers=h).json()[0]
    assert client.post(f"/api/v1/assistant/actions/{action['id']}/decision", json={"approve": True, "args_hash": "tampered"}, headers=h).status_code == 409
    ok = client.post(f"/api/v1/assistant/actions/{action['id']}/decision", json={"approve": True, "args_hash": action["args_hash"]}, headers=h).json()
    assert ok["status"] == "executed"
    assert (
        client.post(f"/api/v1/assistant/actions/{action['id']}/decision", json={"approve": True, "args_hash": action["args_hash"]}, headers=h).status_code
        == 409
    )
    assert len(client.get("/api/v1/leads/tasks/open", headers=h).json()) == 1


def test_personal_mode_isolation_memory_and_reminders(client, db, llm):
    h, tid, _ = register(client)
    colleague, _ = add_member(client, h, "MANAGER")
    conv = client.post("/api/v1/assistant/conversations", json={"mode": "personal"}, headers=h).json()
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "Please remember I prefer Telugu"}, headers=h).json()
    assert r["artifacts"][0]["type"] == "memory_proposal"
    mem = client.get("/api/v1/assistant/memory", headers=h).json()
    assert mem[0]["status"] == "pending"
    assert client.post(f"/api/v1/assistant/memory/{mem[0]['id']}/approve", headers=h).json()["status"] == "active"
    # personal mode never gets business tools
    r = client.post(f"/api/v1/assistant/conversations/{conv['id']}/messages", json={"content": "sales today"}, headers=h).json()
    assert r["content"] == "Tool status: error"
    # another user in the same organization cannot see personal data
    assert client.get(f"/api/v1/assistant/conversations/{conv['id']}/messages", headers=colleague).status_code == 404
    assert client.get("/api/v1/assistant/memory", headers=colleague).json() == []
    assert client.delete(f"/api/v1/assistant/memory/{mem[0]['id']}", headers=colleague).status_code == 404
    # reminders -> notifications
    due = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    rid = client.post("/api/v1/assistant/reminders", json={"text": "Call supplier", "due_at": due}, headers=h).json()["id"]
    db.query(Reminder).filter(Reminder.id == uuid.UUID(rid)).update({"due_at": datetime.now(UTC) - timedelta(seconds=1)})
    db.commit()
    assert deliver_due_reminders(db) == 1
    notes = client.get("/api/v1/notifications", headers=h).json()
    assert notes["unread"] == 1 and notes["items"][0]["body"] == "Call supplier"
    assert client.get("/api/v1/notifications", headers=colleague).json()["unread"] == 0


def test_assistant_identity_requires_capability(client, db):
    root = _root(client, db)
    h, tid, _ = register(client)
    assert client.patch("/api/v1/assistant/preferences", json={"assistant_name": "Mr. Penn"}, headers=h).status_code == 403
    _set(client, root, tid, [{"key": "assistant.identity", "enabled": True}])
    assert client.patch("/api/v1/assistant/preferences", json={"assistant_name": "Mr. Penn", "language": "te-IN"}, headers=h).status_code == 200
    assert client.get("/api/v1/assistant/config", headers=h).json()["preferences"]["assistant_name"] == "Mr. Penn"
    assert client.patch("/api/v1/assistant/preferences", json={"assistant_name": "<script>"}, headers=h).status_code == 422
