import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://kokila:kokila@localhost:5432/kokila_test")
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789-abcdefghijklmnop"
os.environ["VOICE_PROVIDER"] = "mock"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dummy"
os.environ["RAZORPAY_KEY_SECRET"] = "test_key_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_webhook_secret"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "10000"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402

KEEP = {"alembic_version", "plans"}


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    # Validate migrations in both directions on every test run.
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db(migrated):
    with engine.begin() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))]
        c.execute(text("TRUNCATE " + ", ".join(t for t in tables if t not in KEEP) + " CASCADE"))
        c.execute(text("DELETE FROM plans WHERE code <> 'trial'"))
    from app.voice.registry import _mock

    _mock().fail_outbound = False
    _mock().placed.clear()
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def register(client, company="Acme Realty", email=None):
    email = email or f"admin-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/v1/auth/register", json={"company_name": company, "full_name": "Admin User", "email": email, "password": "Sup3rSecret99"})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    tid = me["memberships"][0]["tenant_id"]
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tid}, tid, email


def add_member(client, admin_headers, role):
    email = f"{role.lower()}-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/v1/users", json={"email": email, "full_name": role.title(), "role": role}, headers=admin_headers)
    assert r.status_code == 201, r.text
    pw = r.json()["temporary_password"]
    tok = client.post("/api/v1/auth/login", json={"email": email, "password": pw}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}", "X-Tenant-ID": admin_headers["X-Tenant-ID"]}, r.json()["user_id"]


def grant_plan(db, tenant_id, *, outbound=True, minutes=1000, agents=5, concurrency=5, users=10, code="growth_test"):
    from app.billing.models import Plan, Subscription

    plan = db.query(Plan).filter_by(code=code).one_or_none()
    if plan is None:
        plan = Plan(
            code=code,
            name="Growth (test)",
            price_minor=499900,
            included_minutes=minutes,
            max_agents=agents,
            max_concurrent_calls=concurrency,
            max_users=users,
            features={"outbound": outbound, "calendar": True},
        )
        db.add(plan)
        db.flush()
    for s in db.query(Subscription).filter_by(tenant_id=uuid.UUID(str(tenant_id)), is_current=True):
        s.is_current = False
    db.flush()
    now = datetime.now(UTC)
    db.add(
        Subscription(
            tenant_id=uuid.UUID(str(tenant_id)),
            plan_id=plan.id,
            status="active",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
            is_current=True,
        )
    )
    db.commit()
    return plan


def make_published_agent(client, headers, name="Front Desk", template="real_estate"):
    r = client.post("/api/v1/agents", json={"name": name, "template": template}, headers=headers)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = client.post(f"/api/v1/agents/{aid}/versions/1/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def mock_provider():
    from app.voice.registry import _mock

    return _mock()


def post_signed(client, path, payload):
    body, sig = mock_provider().signed(payload)
    return client.post(path, content=body, headers={"x-retell-signature": sig, "content-type": "application/json"})
