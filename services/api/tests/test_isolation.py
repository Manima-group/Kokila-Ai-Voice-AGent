"""Tenant and user isolation enforced by PostgreSQL RLS, not only by application code (§19, §24.2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import DbScope, unit_of_work
from tests.conftest import new_user


async def test_cross_tenant_api_access_is_404(client):
    a, _ = await new_user(client, "A")
    b, _ = await new_user(client, "B")
    conv = (await a.post("/v1/conversations", json={})).json()
    r = await b.get(f"/v1/conversations/{conv['id']}/messages")
    assert r.status_code == 404
    r = await b.post(f"/v1/conversations/{conv['id']}/turns", json={"text": "hi"}, idem="crosstenant1")
    assert r.status_code == 404
    mem = (await a.post("/v1/memory", json={"content": "A's private fact"})).json()
    assert (await b.delete(f"/v1/memory/{mem['id']}")).status_code == 404
    # B cannot read A's tenant identity settings either.
    r = await b.get(f"/v1/tenants/{a.workspace_id}/assistant-identity")
    assert r.status_code == 404


async def test_rls_blocks_raw_sql_without_context(client):
    a, _ = await new_user(client, "A")
    await a.post("/v1/memory", json={"content": "rls probe fact"})
    async with unit_of_work(scope=DbScope.ANONYMOUS) as db:
        n = await db.scalar(text("select count(*) from memory_items"))
        assert n == 0
        n = await db.scalar(text("select count(*) from conversations"))
        assert n == 0
    # Right tenant but wrong user still cannot see personal memory.
    async with unit_of_work(scope=DbScope.TENANT, tenant_id=uuid.UUID(a.workspace_id), user_id=uuid.uuid4()) as db:
        assert await db.scalar(text("select count(*) from memory_items")) == 0
    # Platform scope cannot read customer content.
    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        assert await db.scalar(text("select count(*) from memory_items")) == 0
        assert await db.scalar(text("select count(*) from messages")) == 0


async def test_rls_with_check_blocks_cross_tenant_insert(client):
    a, _ = await new_user(client, "A")
    b, _ = await new_user(client, "B")
    with pytest.raises(DBAPIError):
        async with unit_of_work(scope=DbScope.TENANT, tenant_id=uuid.UUID(a.workspace_id)) as db:
            await db.execute(
                text(
                    "insert into audit_events (id, tenant_id, action, target_ref, outcome, detail) "
                    "values (gen_random_uuid(), :t, 'x', 'y', 'success', '{}')"
                ),
                {"t": b.workspace_id},
            )


async def test_audit_is_append_only_for_app_role(client):
    a, _ = await new_user(client, "A")
    with pytest.raises(DBAPIError):
        async with unit_of_work(scope=DbScope.TENANT, tenant_id=uuid.UUID(a.workspace_id)) as db:
            await db.execute(text("delete from audit_events"))
