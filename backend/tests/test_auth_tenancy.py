import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from tests.conftest import add_member, grant_plan, register


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok" and r.json()["redis"] == "ok"


def test_register_login_me(client):
    headers, tid, email = register(client)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Sup3rSecret99"})
    assert r.status_code == 200 and r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["memberships"][0]["role"] == "COMPANY_ADMIN"
    sub = client.get("/api/v1/billing/subscription", headers=headers).json()
    assert sub["status"] == "trialing" and sub["plan"]["code"] == "trial"


def test_duplicate_registration_and_weak_password(client):
    _, _, email = register(client)
    r = client.post("/api/v1/auth/register", json={"company_name": "X Co", "full_name": "A B", "email": email, "password": "Sup3rSecret99"})
    assert r.status_code == 409
    r = client.post("/api/v1/auth/register", json={"company_name": "X Co", "full_name": "A B", "email": "n@example.com", "password": "short"})
    assert r.status_code == 422


def test_invalid_credentials_and_lockout(client):
    _, _, email = register(client)
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Sup3rSecret99"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_locked"


def test_expired_and_tampered_tokens(client):
    headers, _, _ = register(client)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    expired = jwt.encode({"sub": me["id"], "typ": "access", "exp": datetime.now(UTC) - timedelta(seconds=5)}, get_settings().jwt_secret, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"
    forged = jwt.encode({"sub": me["id"], "typ": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)}, "not-the-secret-xxxxxxxxxxxxxxxxxxxx", algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    assert client.get("/api/v1/contacts").status_code == 401


def test_refresh_rotation_and_reuse_detection(client):
    register(client)
    old = client.cookies.get("kokila_refresh")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    new = client.cookies.get("kokila_refresh")
    assert new and new != old
    client.cookies.set("kokila_refresh", old, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401  # reuse of rotated token
    client.cookies.set("kokila_refresh", new, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401  # whole family revoked


def test_cross_tenant_isolation(client, db):
    a, a_tid, _ = register(client, "Tenant A")
    b, b_tid, _ = register(client, "Tenant B")
    grant_plan(db, a_tid)
    c = client.post("/api/v1/contacts", json={"phone": "9876543210", "name": "Ravi"}, headers=a).json()
    # B cannot read A's contact even with the id, and gets 404 (no existence leak)
    assert client.get(f"/api/v1/contacts/{c['id']}", headers=b).status_code == 404
    assert client.get("/api/v1/contacts", headers=b).json()["total"] == 0
    # B cannot impersonate A's tenant via header
    spoof = {**b, "X-Tenant-ID": a_tid}
    assert client.get("/api/v1/contacts", headers=spoof).status_code == 403
    # Same phone may exist in both tenants
    assert client.post("/api/v1/contacts", json={"phone": "+919876543210"}, headers=b).status_code == 201
    # Billing isolation
    assert client.get("/api/v1/billing/invoices", headers=b).json()["total"] == 0
    # Cross-tenant campaign/call ids are 404
    assert client.get(f"/api/v1/campaigns/{uuid.uuid4()}", headers=b).status_code == 404
    assert client.get(f"/api/v1/calls/{uuid.uuid4()}", headers=b).status_code == 404


def test_role_denials(client, db):
    admin, tid, _ = register(client)
    grant_plan(db, tid)
    viewer, _ = add_member(client, admin, "VIEWER")
    operator, op_id = add_member(client, admin, "OPERATOR")
    assert client.get("/api/v1/contacts", headers=viewer).status_code == 200
    assert client.post("/api/v1/contacts", json={"phone": "9876500001"}, headers=viewer).status_code == 403
    assert client.post("/api/v1/agents", json={"name": "X", "template": "receptionist"}, headers=operator).status_code == 403
    assert client.get("/api/v1/billing/subscription", headers=operator).status_code == 403
    assert client.get("/api/v1/admin/tenants", headers=admin).status_code == 403
    # Operator only sees/edit assigned leads
    contact = client.post("/api/v1/contacts", json={"phone": "9876500002"}, headers=admin).json()
    lead = client.post("/api/v1/leads", json={"contact_id": contact["id"]}, headers=admin).json()
    assert client.get("/api/v1/leads", headers=operator).json()["total"] == 0
    assert client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "contacted"}, headers=operator).status_code == 403
    assert client.post(f"/api/v1/leads/{lead['id']}/assign", json={"user_id": op_id}, headers=admin).status_code == 200
    assert client.get("/api/v1/leads", headers=operator).json()["total"] == 1
    assert client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "contacted"}, headers=operator).status_code == 200


def test_suspended_tenant_blocked(client, db):
    from app.tenants.models import Tenant

    headers, tid, _ = register(client)
    t = db.get(Tenant, uuid.UUID(tid))
    t.status = "suspended"
    db.commit()
    r = client.get("/api/v1/contacts", headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_suspended"
