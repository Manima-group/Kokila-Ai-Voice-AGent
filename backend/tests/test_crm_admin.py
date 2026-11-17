import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.integrations.models import OutboxEvent
from app.integrations.outbox import process_outbox, sign_payload
from app.telephony.models import Call
from app.tenants.models import User
from tests.conftest import grant_plan, make_published_agent, register

CSV = """phone,name,email,tags,consent_purpose,consent_source,consent_evidence
9845011111,Asha,asha@example.com,vip;bangalore,sales,web_form,Form 1
+91 98450 11111,Asha dup,,,,,
12345,Bad,,,,,
9845022222,Bhanu,,,sales,web_form,
9845033333,Chetan,,,,,
"""


def test_csv_import_and_timeline(client):
    h, _, _ = register(client)
    r = client.post("/api/v1/contacts/import", files={"file": ("c.csv", CSV, "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 3 and out["duplicates_in_file"] == 1 and out["consents_recorded"] == 1
    assert out["invalid_count"] == 2  # bad phone + consent without evidence
    found = client.get("/api/v1/contacts?q=Asha", headers=h).json()
    assert found["total"] == 1 and found["items"][0]["tags"] == ["vip", "bangalore"]
    assert client.get("/api/v1/contacts?tag=vip", headers=h).json()["total"] == 1
    detail = client.get(f"/api/v1/contacts/{found['items'][0]['id']}", headers=h).json()
    assert len(detail["consents"]) == 1 and detail["suppressed"] is False
    bad = client.post("/api/v1/contacts/import", files={"file": ("c.csv", "name\nx\n", "text/csv")}, headers=h)
    assert bad.status_code == 400


def test_suppression_removal_rules_and_erasure(client):
    h, _, _ = register(client)
    c = client.post("/api/v1/contacts", json={"phone": "9845044444", "name": "Dev"}, headers=h).json()
    client.post("/api/v1/suppression", json={"phone": "9845044444", "reason": "opt_out"}, headers=h)
    entry = client.get("/api/v1/suppression", headers=h).json()["items"][0]
    assert client.delete(f"/api/v1/suppression/{entry['id']}", headers=h).status_code == 409
    client.post(f"/api/v1/contacts/{c['id']}/consents", json={"purpose": "sales", "source": "written", "evidence": "Signed form"}, headers=h)
    assert client.delete(f"/api/v1/suppression/{entry['id']}", headers=h).status_code == 204
    r = client.post("/api/v1/deletion-requests", json={"contact_id": c["id"], "reason": "DPDP erasure request"}, headers=h)
    assert r.status_code == 201 and r.json()["status"] == "completed"
    assert client.get(f"/api/v1/contacts/{c['id']}", headers=h).status_code == 404
    assert client.get("/api/v1/suppression", headers=h).json()["total"] == 1  # erased person is never re-dialled
    logs = client.get("/api/v1/audit-logs?action=contact.erased", headers=h).json()
    assert logs["total"] == 1


def test_lead_tasks_and_assignment(client, db):
    h, tid, _ = register(client)
    c = client.post("/api/v1/contacts", json={"phone": "9845055555"}, headers=h).json()
    lead = client.post("/api/v1/leads", json={"contact_id": c["id"]}, headers=h).json()
    t = client.post(
        f"/api/v1/leads/{lead['id']}/activities", json={"kind": "task", "body": "Call back", "due_at": "2030-01-01T10:00:00+05:30"}, headers=h
    ).json()
    assert len(client.get("/api/v1/leads/tasks/open", headers=h).json()) == 1
    client.post(f"/api/v1/leads/{lead['id']}/activities/{t['id']}/complete", headers=h)
    assert client.get("/api/v1/leads/tasks/open", headers=h).json() == []
    other, _, _ = register(client, "Other Co")
    other_user = client.get("/api/v1/auth/me", headers=other).json()["id"]
    r = client.post(f"/api/v1/leads/{lead['id']}/assign", json={"user_id": other_user}, headers=h)
    assert r.status_code == 422  # cannot assign to a user outside the tenant


def test_webhook_outbox_delivery_signed(client, db):
    import httpx

    h, tid, _ = register(client)
    conn = client.post(
        "/api/v1/integrations",
        json={"kind": "n8n", "name": "n8n", "target_url": "https://n8n.example.com/webhook/x", "event_types": ["call.analyzed"]},
        headers=h,
    ).json()
    secret = conn["signing_secret"]
    db.add(OutboxEvent(tenant_id=uuid.UUID(tid), event_type="call.analyzed", payload={"call_id": "abc"}))
    db.commit()
    seen = []

    def handler(request: httpx.Request):
        ts = request.headers["X-Kokila-Timestamp"]
        assert request.headers["X-Kokila-Signature"] == "sha256=" + sign_payload(secret, request.content, int(ts))
        seen.append(request)
        return httpx.Response(200)

    stats = process_outbox(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert stats["sent"] == 1 and len(seen) == 1
    db.add(OutboxEvent(tenant_id=uuid.UUID(tid), event_type="call.analyzed", payload={}))
    db.commit()
    stats = process_outbox(db, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert stats["failed"] == 1
    assert client.get("/api/v1/integrations/deliveries?status=failed", headers=h).json()["total"] == 1


def _superadmin(client, db):
    db.add(User(email="root@manima.co.in", password_hash=hash_password("Sup3rSecret99"), full_name="Root", is_superadmin=True))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"email": "root@manima.co.in", "password": "Sup3rSecret99"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_superadmin_operations(client, db):
    root = _superadmin(client, db)
    h, tid, _ = register(client, "Tenant One")
    assert client.get("/api/v1/admin/tenants", headers=h).status_code == 403
    lst = client.get("/api/v1/admin/tenants", headers=root).json()
    assert lst["total"] == 1 and lst["items"][0]["plan"] == "trial"
    plan = {
        "code": "growth",
        "name": "Growth",
        "price_minor": 999900,
        "included_minutes": 2000,
        "max_agents": 5,
        "max_concurrent_calls": 5,
        "max_users": 10,
        "features": {"outbound": True},
    }
    assert client.put("/api/v1/admin/plans", json=plan, headers=root).status_code == 200
    assert any(p["code"] == "growth" for p in client.get("/api/v1/billing/plans", headers=h).json())
    assert client.post(f"/api/v1/admin/tenants/{tid}/compliance-decision", json={"approved": True, "note": "not yet"}, headers=root).status_code == 409
    comp = {"legal_name": "Tenant One Pvt Ltd", "dlt_entity_id": "1101", "attests_consent_collection": True, "attests_recording_disclosure": True}
    assert client.put("/api/v1/tenants/current/compliance", json=comp, headers=h).json()["status"] == "pending_review"
    d = client.post(f"/api/v1/admin/tenants/{tid}/compliance-decision", json={"approved": True, "note": "Docs verified"}, headers=root).json()
    assert d["outbound_approved"] is True
    ks = client.put("/api/v1/admin/kill-switch", json={"enabled": True, "reason": "carrier incident"}, headers=root).json()
    assert ks["enabled"] is True
    health = client.get("/api/v1/admin/health", headers=root).json()
    assert health["database"] == "ok" and health["tenants"]["active"] == 1
    assert client.post(f"/api/v1/admin/tenants/{tid}/status", json={"status": "suspended", "reason": "non-payment"}, headers=root).status_code == 200
    assert client.get("/api/v1/contacts", headers=h).status_code == 403
    actions = [a["action"] for a in client.get("/api/v1/admin/audit-logs", headers=root).json()]
    assert "admin.kill_switch" in actions and "admin.tenant_suspended" in actions


def test_analytics_real_data(client, db):
    h, tid, _ = register(client)
    grant_plan(db, tid)
    agent = make_published_agent(client, h)
    db.add(
        Call(
            tenant_id=uuid.UUID(tid),
            provider="retell",
            provider_call_id="r1",
            direction="inbound",
            status="completed",
            duration_seconds=120,
            outcome="qualified",
            agent_id=uuid.UUID(agent["id"]),
            provider_cost_minor=14,
            extracted={},
        )
    )
    db.add(Call(tenant_id=uuid.UUID(tid), provider="retell", provider_call_id="r2", direction="outbound", status="failed", outcome="no_answer", extracted={}))
    db.commit()
    o = client.get("/api/v1/analytics/overview", headers=h).json()
    assert o["calls"] == {"total": 2, "answered": 1, "failed": 1, "inbound": 1, "outbound": 1, "answer_rate": 0.5, "handoffs": 0}
    assert o["provider_cost"][0]["amount_minor"] == 14
    perf = client.get("/api/v1/analytics/agents", headers=h).json()
    assert perf[0]["calls"] == 1 and perf[0]["positive_outcomes"] == 1
    assert db.scalar(select(Call.id).where(Call.provider_call_id == "r1"))
