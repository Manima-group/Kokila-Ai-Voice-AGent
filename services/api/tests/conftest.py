"""Integration test harness against real PostgreSQL 16 + Redis (no database mocks).

The reasoning provider is the isolated dev_mock adapter; every reply it produces is labelled "[dev mock]".
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pyotp
import pytest

API_DIR = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("KOKILA_TEST_DB", "kokila_test")
PGHOST = os.environ.get("KOKILA_TEST_PGHOST", "localhost")
os.environ.update(
    {
        "KOKILA_ENV": "test",
        "KOKILA_DATABASE_URL": f"postgresql+asyncpg://kokila_app:kokila_app_dev@{PGHOST}:5432/{TEST_DB}",
        "KOKILA_MIGRATION_DATABASE_URL": f"postgresql+asyncpg://kokila_owner:kokila_owner_dev@{PGHOST}:5432/{TEST_DB}",
        "KOKILA_REDIS_URL": os.environ.get("KOKILA_TEST_REDIS_URL", "redis://localhost:6379/15"),
        "KOKILA_REASONING_PROVIDER": "dev_mock",
        "KOKILA_RATE_LIMIT_SCALE": "1000",
    }
)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402


def _run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=API_DIR, check=True, env=os.environ.copy())


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    _run("-m", "alembic", "downgrade", "base")
    _run("-m", "alembic", "upgrade", "head")
    _run("-m", "app.cli", "bootstrap")
    import redis

    redis.Redis.from_url(os.environ["KOKILA_REDIS_URL"]).flushdb()


@pytest.fixture(scope="session")
async def client(_schema):
    from app.main import create_app

    app = create_app()
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    from app.core.db import dispose_engine

    await dispose_engine()


class Api:
    def __init__(self, client: httpx.AsyncClient, token: str, refresh: str, workspace_id: str | None) -> None:
        self.c, self.token, self.refresh_token, self.workspace_id = client, token, refresh, workspace_id

    def h(self, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", **extra}

    async def get(self, url: str, **kw):
        return await self.c.get(url, headers=self.h(), **kw)

    async def post(self, url: str, json=None, idem: str | None = None, **kw):
        headers = self.h(**({"Idempotency-Key": idem} if idem else {}))
        return await self.c.post(url, json=json, headers=headers, **kw)

    async def patch(self, url: str, json=None):
        return await self.c.patch(url, json=json, headers=self.h())

    async def put(self, url: str, json=None):
        return await self.c.put(url, json=json, headers=self.h())

    async def delete(self, url: str):
        return await self.c.delete(url, headers=self.h())


PASSWORD = "correct-horse-battery-staple"


async def new_user(client: httpx.AsyncClient, name: str = "Test User") -> tuple[Api, str]:
    email = f"u-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": name})
    assert r.status_code == 202, r.text
    r = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    d = r.json()
    return Api(client, d["access_token"], d["refresh_token"], d["workspace_id"]), email


async def relogin(client: httpx.AsyncClient, email: str, workspace_id: str | None = None) -> Api:
    r = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": PASSWORD, **({"workspace_id": workspace_id} if workspace_id else {})},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    return Api(client, d["access_token"], d["refresh_token"], d["workspace_id"])


@pytest.fixture(scope="session")
async def super_admin(client) -> Api:
    from sqlalchemy import update

    from app.core.db import DbScope, unit_of_work
    from app.models import User

    api, email = await new_user(client, "Manima Admin")
    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        await db.execute(update(User).where(User.email == email).values(platform_role="super_admin"))
    r = await api.post("/v1/auth/mfa/enroll")
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = await api.post("/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204, r.text
    r = await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, "platform": True, "otp": pyotp.TOTP(secret).now()}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["platform"] and d["mfa"]
    return Api(client, d["access_token"], d["refresh_token"], None)


async def set_plan(admin: Api, tenant_id: str, plan_code: str) -> None:
    r = await admin.get(f"/v1/platform/tenants/{tenant_id}")
    rev = r.json()["tenant"]["policy_revision"]
    r = await admin.put(
        f"/v1/platform/tenants/{tenant_id}/subscription",
        json={"plan_code": plan_code, "expected_revision": rev, "reason": "test setup"},
    )
    assert r.status_code == 200, r.text
