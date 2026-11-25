"""Super Admin licensing and the single effective-access policy (§25 acceptance evidence)."""

from __future__ import annotations

import pytest

from app.domain.capabilities import ALL_CAPABILITIES, find_dependency_cycle
from tests.conftest import new_user, relogin, set_plan


def test_registry_is_acyclic_and_complete():
    keys = {c.key for c in ALL_CAPABILITIES}
    assert {f"KOK-{i:02d}" for i in range(1, 21)} <= {c.requirement_id for c in ALL_CAPABILITIES}
    assert {
        f"connector.{k}"
        for k in (
            "tally",
            "zoho",
            "salesforce",
            "sap",
            "dynamics",
            "gmail",
            "outlook",
            "whatsapp",
            "teams",
            "slack",
            "n8n",
            "manima",
        )
    } <= keys
    assert find_dependency_cycle({c.key: c.dependencies for c in ALL_CAPABILITIES}) is None
    assert find_dependency_cycle({"a": ("b",), "b": ("a",)}) == ["a", "b", "a"]


async def test_platform_requires_platform_session_and_mfa(client, super_admin):
    tenant_user, _ = await new_user(client)
    r = await tenant_user.get("/v1/platform/tenants")
    assert r.status_code == 403
    assert (await super_admin.get("/v1/platform/tenants")).status_code == 200


async def _business_tenant(client, super_admin, plan: str | None = None):
    owner, email = await new_user(client, "Owner")
    r = await super_admin.post(
        "/v1/platform/tenants",
        json={"name": "Sagar Air Test", "owner_email": email, "plan_code": plan, "reason": "provision test"},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    return tid, await relogin(client, email, tid)


async def _patch(admin, tid, changes, reason="package edit"):
    rev = (await admin.get(f"/v1/platform/tenants/{tid}")).json()["tenant"]["policy_revision"]
    return await admin.patch(
        f"/v1/platform/tenants/{tid}/entitlements",
        json={"changes": changes, "expected_revision": rev, "reason": reason},
    )


@pytest.mark.parametrize(
    "selected",
    [
        ["assistant.text", "assistant.voice", "assistant.memory", "assistant.identity"],  # four
        [
            "assistant.text",
            "assistant.voice",
            "assistant.memory",
            "assistant.identity",
            "voice.agents",
            "voice.inbound",
        ],  # six
    ],
)
async def test_custom_packages_enforced_everywhere(client, super_admin, selected):
    tid, owner = await _business_tenant(client, super_admin)
    r = await _patch(super_admin, tid, [{"key": k, "enabled": True} for k in selected])
    assert r.status_code == 200, r.text
    purchasable = {c.key for c in ALL_CAPABILITIES if c.purchasable}
    assert set(r.json()["effective_capabilities"]) & purchasable == set(selected)
    caps = (await owner.get("/v1/me/capabilities")).json()
    assert set(caps["enabled"]) & purchasable == set(selected)
    # Direct API enforcement of an unpurchased capability:
    r = await owner.post("/v1/assistant/preferences/wake-word/validate", json={"phrase": "Hey Kokila"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "capability_disabled"


async def test_full_package(client, super_admin):
    tid, owner = await _business_tenant(client, super_admin, plan="enterprise-custom")
    caps = (await owner.get("/v1/me/capabilities")).json()
    assert {c.key for c in ALL_CAPABILITIES} <= set(caps["enabled"])


async def test_dependency_conflict_is_atomic(client, super_admin):
    tid, owner = await _business_tenant(client, super_admin)
    r = await _patch(
        super_admin, tid, [{"key": "assistant.memory", "enabled": True}, {"key": "assistant.voice", "enabled": True}]
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "dependency_conflict"
    caps = (await owner.get("/v1/me/capabilities")).json()
    assert "assistant.memory" not in caps["enabled"]  # nothing partially applied
    # Disabling a dependency while dependants are on is also rejected.
    assert (
        await _patch(
            super_admin, tid, [{"key": "assistant.text", "enabled": True}, {"key": "assistant.voice", "enabled": True}]
        )
    ).status_code == 200
    r = await _patch(super_admin, tid, [{"key": "assistant.text", "enabled": False}])
    assert r.status_code == 409
    assert r.json()["error"]["details"]["dependency_conflicts"][0]["required_by"] == ["assistant.voice"]


async def test_revision_conflict_and_infrastructure_locked(client, super_admin):
    tid, _ = await _business_tenant(client, super_admin)
    r = await super_admin.patch(
        f"/v1/platform/tenants/{tid}/entitlements",
        json={"changes": [{"key": "assistant.text", "enabled": True}], "expected_revision": 999, "reason": "stale"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_conflict"
    r = await _patch(super_admin, tid, [{"key": "platform.security", "enabled": False}])
    assert r.status_code == 422


async def test_kill_switch_and_suspension_take_effect_immediately(client, super_admin):
    user, _ = await new_user(client)
    conv = (await user.post("/v1/conversations", json={})).json()
    caps = (await super_admin.get("/v1/platform/capabilities")).json()["items"]
    rev = next(c for c in caps if c["key"] == "assistant.text")["control_revision"]
    r = await super_admin.patch(
        "/v1/platform/capabilities/assistant.text",
        json={"enabled": False, "expected_revision": rev, "reason": "incident drill"},
    )
    assert r.status_code == 200, r.text
    try:
        r = await user.post(f"/v1/conversations/{conv['id']}/turns", json={"text": "hello"}, idem="killswitch-1")
        assert r.status_code == 403 and r.json()["error"]["code"] == "capability_disabled"
    finally:
        r = await super_admin.patch(
            "/v1/platform/capabilities/assistant.text",
            json={"enabled": True, "expected_revision": rev + 1, "reason": "drill over"},
        )
        assert r.status_code == 200
    # Suspension
    t = (await super_admin.get(f"/v1/platform/tenants/{user.workspace_id}")).json()["tenant"]
    r = await super_admin.patch(
        f"/v1/platform/tenants/{user.workspace_id}/status",
        json={"status": "suspended", "expected_revision": t["revision"], "reason": "test"},
    )
    assert r.status_code == 200
    assert (await user.get("/v1/me/capabilities")).status_code == 403
    r = await super_admin.patch(
        f"/v1/platform/tenants/{user.workspace_id}/status",
        json={"status": "active", "expected_revision": t["revision"] + 1, "reason": "test"},
    )
    assert (await user.get("/v1/me/capabilities")).status_code == 200


async def test_platform_tenant_detail_has_no_customer_content(client, super_admin):
    user, _ = await new_user(client)
    conv = (await user.post("/v1/conversations", json={})).json()
    await user.post(f"/v1/conversations/{conv['id']}/turns", json={"text": "private secret note"}, idem="priv-1")
    detail = await super_admin.get(f"/v1/platform/tenants/{user.workspace_id}")
    assert "private secret note" not in detail.text
    audit = await super_admin.get("/v1/platform/audit")
    assert audit.status_code == 200 and audit.json()["items"]


async def test_plan_upgrade_changes_access(client, super_admin):
    user, _ = await new_user(client)
    r = await user.post("/v1/assistant/sessions", json={"channel": "web_voice", "device_id": "device-aaaa"})
    assert r.status_code == 403
    await set_plan(super_admin, user.workspace_id, "assistant-plus")
    r = await user.post("/v1/assistant/sessions", json={"channel": "web_voice", "device_id": "device-aaaa"})
    assert r.status_code == 201, r.text
