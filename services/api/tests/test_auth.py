from __future__ import annotations

from tests.conftest import PASSWORD, new_user


async def test_register_is_neutral_for_existing_email(client):
    api, email = await new_user(client)
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": "X"})
    assert r.status_code == 202
    assert "sign in" in r.json()["message"]


async def test_login_failure_is_neutral(client):
    _, email = await new_user(client)
    bad_pw = await client.post("/v1/auth/login", json={"email": email, "password": "wrong-password-123"})
    no_user = await client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["error"]["message"] == no_user.json()["error"]["message"]
    assert bad_pw.json()["error"]["trace_id"]


async def test_me_and_personal_workspace(client):
    api, email = await new_user(client, "Sai")
    r = await api.get("/v1/me")
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == email and me["role"] == "owner" and me["workspace_id"] == api.workspace_id
    ws = (await api.get("/v1/me/workspaces")).json()
    assert len(ws) == 1 and ws[0]["type"] == "personal"
    caps = (await api.get("/v1/me/capabilities")).json()
    assert "assistant.text" in caps["enabled"] and "assistant.voice" not in caps["enabled"]
    assert "platform.security" in caps["enabled"]


async def test_refresh_rotation_and_reuse_detection(client):
    api, _ = await new_user(client)
    r1 = await client.post("/v1/auth/refresh", json={"refresh_token": api.refresh_token})
    assert r1.status_code == 200
    new = r1.json()
    # Reusing the rotated token revokes the whole family, including the newly issued tokens.
    r2 = await client.post("/v1/auth/refresh", json={"refresh_token": api.refresh_token})
    assert r2.status_code == 401
    r3 = await client.post("/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert r3.status_code == 401
    r4 = await client.get("/v1/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    assert r4.status_code == 401


async def test_logout_revokes_access(client):
    api, _ = await new_user(client)
    assert (await api.post("/v1/auth/logout")).status_code == 204
    assert (await api.get("/v1/me")).status_code == 401


async def test_unauthenticated_and_garbage_tokens(client):
    assert (await client.get("/v1/me")).status_code == 401
    r = await client.get("/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_weak_password_rejected(client):
    r = await client.post(
        "/v1/auth/register", json={"email": "weak@example.com", "password": "Zq9!xy", "display_name": "W"}
    )
    assert r.status_code == 422
    assert "Zq9!xy" not in r.text  # input values are not echoed back


async def test_health(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    r = await client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json()["checks"]["reasoning"] == "configured"


async def test_rate_limiter_blocks_after_threshold():
    import pytest

    from app.core.errors import KokilaError
    from app.core.ratelimit import hit

    for _ in range(3000):
        await hit("unit-test", "ip-1", limit=3, window_s=60)
    with pytest.raises(KokilaError) as exc:
        await hit("unit-test", "ip-1", limit=3, window_s=60)
    assert exc.value.status_code == 429
