"""Voice session controls (KOK-14-MUTE), turns, interruption, tool approvals (§23.1a, §24.3, §27.4)."""

from __future__ import annotations

import uuid

from tests.conftest import new_user, set_plan


async def _plus_user(client, super_admin):
    user, email = await new_user(client, "Plus User")
    await set_plan(super_admin, user.workspace_id, "assistant-plus")
    return user


async def _session(user, device="device-primary1"):
    r = await user.post("/v1/assistant/sessions", json={"channel": "web_voice", "device_id": device, "locale": "auto"})
    assert r.status_code == 201, r.text
    return r.json()


async def test_session_starts_fully_muted(client, super_admin):
    user = await _plus_user(client, super_admin)
    s = await _session(user)
    assert s["mic_muted"] is True and s["speaker_muted"] is True and s["state"] == "idle"
    r = await user.post(
        f"/v1/assistant/sessions/{s['id']}/state", json={"state": "listening", "expected_generation": 0}
    )
    assert r.status_code == 409  # cannot listen while muted


async def test_mute_controls_revision_and_device_rules(client, super_admin):
    user = await _plus_user(client, super_admin)
    s = await _session(user)
    sid = s["id"]
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/controls",
        json={
            "mic_muted": False,
            "speaker_muted": False,
            "expected_revision": s["revision"],
            "device_id": "device-primary1",
        },
    )
    assert r.status_code == 200, r.text
    s2 = r.json()
    assert not s2["mic_muted"] and not s2["speaker_muted"]
    # stale revision
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/controls",
        json={"mic_muted": True, "expected_revision": s["revision"], "device_id": "device-primary1"},
    )
    assert r.status_code == 409
    # speaker mute invalidates queued speech (generation advances) and does not touch the mic
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/controls",
        json={"speaker_muted": True, "expected_revision": s2["revision"], "device_id": "device-primary1"},
    )
    s3 = r.json()
    assert s3["speaker_muted"] and not s3["mic_muted"] and s3["generation"] == s2["generation"] + 1
    # mute-all then another device resumes: stays muted; unmute from a non-active device is refused
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/controls",
        json={
            "mic_muted": True,
            "speaker_muted": True,
            "expected_revision": s3["revision"],
            "device_id": "device-primary1",
        },
    )
    s4 = r.json()
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/controls",
        json={"mic_muted": False, "expected_revision": s4["revision"], "device_id": "device-other22"},
    )
    assert r.status_code == 403
    r = await user.post(
        f"/v1/assistant/sessions/{sid}/resume", json={"last_sequence": 0, "device_id": "device-other22"}
    )
    assert r.status_code == 200
    assert r.json()["session"]["mic_muted"] is True and r.json()["session"]["device_id"] == "device-other22"


async def test_reconnect_on_same_device_preserves_unmuted_state_without_replay(client, super_admin):
    user = await _plus_user(client, super_admin)
    s = await _session(user)
    s = (
        await user.post(
            f"/v1/assistant/sessions/{s['id']}/controls",
            json={"mic_muted": False, "expected_revision": s["revision"], "device_id": "device-primary1"},
        )
    ).json()
    r = await user.post(
        f"/v1/conversations/{s['conversation_id']}/turns",
        json={"text": "hello", "session_id": s["id"], "generation": s["generation"]},
        idem="turn-reconnect-1",
    )
    assert r.status_code == 200
    r = await user.post(
        f"/v1/assistant/sessions/{s['id']}/resume", json={"last_sequence": 0, "device_id": "device-primary1"}
    )
    body = r.json()
    assert body["session"]["mic_muted"] is False
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


async def test_text_turn_with_dev_mock_and_idempotent_replay(client):
    user, _ = await new_user(client, "Sai")
    conv = (await user.post("/v1/conversations", json={})).json()
    r1 = await user.post(
        f"/v1/conversations/{conv['id']}/turns", json={"text": "నమస్తే, how are you?"}, idem="turn-idem-0001"
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["assistant_message"]["content"].startswith("[dev mock] Kokila received")
    assert d1["assistant_message"]["dev_mock"] is True
    assert d1["user_message"]["language"] == "te-IN"
    r2 = await user.post(
        f"/v1/conversations/{conv['id']}/turns", json={"text": "నమస్తే, how are you?"}, idem="turn-idem-0001"
    )
    d2 = r2.json()
    assert d2["replayed"] is True and d2["turn_id"] == d1["turn_id"]
    msgs = (await user.get(f"/v1/conversations/{conv['id']}/messages")).json()["items"]
    assert len(msgs) == 2


async def test_turn_requires_idempotency_key(client):
    user, _ = await new_user(client)
    conv = (await user.post("/v1/conversations", json={})).json()
    r = await user.post(f"/v1/conversations/{conv['id']}/turns", json={"text": "hi"})
    assert r.status_code == 422


async def test_memory_save_requires_bound_approval(client, super_admin):
    user = await _plus_user(client, super_admin)
    conv = (await user.post("/v1/conversations", json={})).json()
    r = await user.post(
        f"/v1/conversations/{conv['id']}/turns",
        json={"text": "remember that I prefer replies in Telugu"},
        idem="turn-mem-0001",
    )
    d = r.json()
    assert d["state"] == "awaiting_approval"
    run = d["tool_runs"][0]
    assert run["tool_key"] == "memory.save" and run["status"] == "awaiting_approval"
    assert "approval" in d["assistant_message"]["content"]
    assert (await user.get("/v1/memory")).json()["items"] == []  # nothing saved yet
    ap = run["approval"]
    # Approval is bound to the exact arguments.
    bad = await user.post(f"/v1/approvals/{ap['id']}/decision", json={"decision": "approve", "args_hash": "0" * 64})
    assert bad.status_code == 409
    # Another user cannot decide it.
    other, _ = await new_user(client)
    assert (
        await other.post(
            f"/v1/approvals/{ap['id']}/decision", json={"decision": "approve", "args_hash": ap["args_hash"]}
        )
    ).status_code == 404
    ok = await user.post(
        f"/v1/approvals/{ap['id']}/decision", json={"decision": "approve", "args_hash": ap["args_hash"]}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "succeeded"
    items = (await user.get("/v1/memory")).json()["items"]
    assert [i["content"] for i in items] == ["I prefer replies in Telugu"]
    again = await user.post(
        f"/v1/approvals/{ap['id']}/decision", json={"decision": "approve", "args_hash": ap["args_hash"]}
    )
    assert again.status_code == 409  # no duplicate side effect
    assert len((await user.get("/v1/memory")).json()["items"]) == 1


async def test_denied_and_cancelled_runs_do_nothing(client, super_admin):
    user = await _plus_user(client, super_admin)
    r = await user.post(
        "/v1/tools/runs", json={"tool_key": "memory.save", "args": {"content": "deny me"}}, idem="run-deny-00001"
    )
    assert r.status_code == 202
    ap = r.json()["approval"]
    d = await user.post(f"/v1/approvals/{ap['id']}/decision", json={"decision": "deny", "args_hash": ap["args_hash"]})
    assert d.json()["status"] == "cancelled" and d.json()["error_code"] == "approval_denied"
    r = await user.post(
        "/v1/tools/runs", json={"tool_key": "memory.save", "args": {"content": "cancel me"}}, idem="run-cancel-0001"
    )
    c = await user.post(f"/v1/tools/runs/{r.json()['run_id']}/cancel")
    assert c.json()["cancelled"] is True
    assert (await user.get("/v1/memory")).json()["items"] == []
    # Idempotency key reuse with different args is a conflict.
    r = await user.post(
        "/v1/tools/runs", json={"tool_key": "memory.save", "args": {"content": "other"}}, idem="run-cancel-0001"
    )
    assert r.status_code == 409


async def test_invalid_tool_args_fail_validation_not_execution(client):
    user, _ = await new_user(client)
    r = await user.post("/v1/tools/runs", json={"tool_key": "time.now", "args": {"evil": "x"}}, idem="run-badargs1")
    assert r.status_code == 202 and r.json()["status"] == "failed"
    assert r.json()["error_code"] == "invalid_arguments"
    r = await user.post("/v1/tools/runs", json={"tool_key": "time.now", "args": {}}, idem="run-timenow1")
    assert r.json()["status"] == "succeeded" and r.json()["result"]["timezone"] == "Asia/Kolkata"


async def test_free_plan_cannot_discover_memory_write_tool(client):
    user, _ = await new_user(client)
    keys = {t["key"] for t in (await user.get("/v1/tools")).json()["items"]}
    assert "memory.save" not in keys and "time.now" in keys
    r = await user.post(
        "/v1/tools/runs", json={"tool_key": "memory.save", "args": {"content": "x y z"}}, idem="run-free-00001"
    )
    assert r.status_code == 403


async def test_barge_in_records_only_heard_text_and_discards_stale(client, super_admin):
    user = await _plus_user(client, super_admin)
    s = await _session(user)
    s = (
        await user.post(
            f"/v1/assistant/sessions/{s['id']}/controls",
            json={
                "mic_muted": False,
                "speaker_muted": False,
                "expected_revision": s["revision"],
                "device_id": "device-primary1",
            },
        )
    ).json()
    r = await user.post(
        f"/v1/conversations/{s['conversation_id']}/turns",
        json={"text": "tell me a long story", "session_id": s["id"], "generation": s["generation"]},
        idem="turn-bargein-01",
    )
    d = r.json()
    assert d["state"] == "speaking"
    mid = d["assistant_message"]["id"]
    r = await user.post(
        f"/v1/assistant/sessions/{s['id']}/interrupt",
        json={"expected_generation": s["generation"], "message_id": mid, "played_chars": 10},
    )
    assert r.status_code == 200 and r.json()["state"] == "listening"
    msgs = (await user.get(f"/v1/conversations/{s['conversation_id']}/messages")).json()["items"]
    assert msgs[-1]["status"] == "interrupted" and msgs[-1]["played_chars"] == 10
    # A turn carrying the old generation is rejected as stale.
    r = await user.post(
        f"/v1/conversations/{s['conversation_id']}/turns",
        json={"text": "next", "session_id": s["id"], "generation": s["generation"]},
        idem="turn-bargein-02",
    )
    assert r.status_code == 409


async def test_media_tokens_report_unconfigured_providers_honestly(client, super_admin):
    user = await _plus_user(client, super_admin)
    s = await _session(user)
    r = await user.post(f"/v1/assistant/sessions/{s['id']}/media-token")
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_unavailable"
    r = await user.post(f"/v1/assistant/sessions/{s['id']}/realtime-token")
    assert r.status_code == 409  # muted: no realtime audio before an explicit unmute


async def test_quota_exhaustion(client, super_admin):
    user, _ = await new_user(client)
    rev = (await super_admin.get(f"/v1/platform/tenants/{user.workspace_id}")).json()["tenant"]["policy_revision"]
    r = await super_admin.patch(
        f"/v1/platform/tenants/{user.workspace_id}/entitlements",
        json={
            "changes": [{"key": "assistant.text", "enabled": True, "limits": {"monthly": 2}}],
            "expected_revision": rev,
            "reason": "quota test",
        },
    )
    assert r.status_code == 200, r.text
    conv = (await user.post("/v1/conversations", json={})).json()
    for i in range(2):
        r = await user.post(f"/v1/conversations/{conv['id']}/turns", json={"text": f"hi {i}"}, idem=f"quota-turn-{i}")
        assert r.status_code == 200
    r = await user.post(f"/v1/conversations/{conv['id']}/turns", json={"text": "one more"}, idem="quota-turn-9")
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"


async def test_memory_crud_and_revision(client):
    user, _ = await new_user(client)
    m = (await user.post("/v1/memory", json={"content": "Favourite city: Hyderabad"})).json()
    r = await user.patch(f"/v1/memory/{m['id']}", json={"content": "Favourite city: Vizag", "expected_revision": 99})
    assert r.status_code == 409
    r = await user.patch(f"/v1/memory/{m['id']}", json={"content": "Favourite city: Vizag", "expected_revision": 1})
    assert r.json()["content"] == "Favourite city: Vizag" and r.json()["revision"] == 2
    assert (await user.delete(f"/v1/memory/{m['id']}")).status_code == 204
    assert (await user.delete(f"/v1/memory/{uuid.uuid4()}")).status_code == 404
