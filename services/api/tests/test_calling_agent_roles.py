"""Integration step 1: Calling Agent roles, permissions and catalog keys."""

from __future__ import annotations

from sqlalchemy import text

from app.domain.capabilities import CAPABILITIES, CATALOG_VERSION
from app.domain.constants import ROLE_PERMISSIONS, Permission, TenantRole


def test_role_permissions_are_least_privilege() -> None:
    owner, admin = ROLE_PERMISSIONS[TenantRole.OWNER], ROLE_PERMISSIONS[TenantRole.ADMIN]
    manager, staff = ROLE_PERMISSIONS[TenantRole.MANAGER], ROLE_PERMISSIONS[TenantRole.STAFF]
    viewer = ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert owner == frozenset(Permission)
    assert Permission.BILLING_MANAGE in owner and Permission.BILLING_MANAGE not in admin
    assert {Permission.CAMPAIGNS_CONTROL, Permission.LEADS_ASSIGN, Permission.CONSENT_WRITE} <= manager
    assert Permission.CONTACTS_DELETE not in manager and Permission.TENANT_MEMBERS_MANAGE not in manager
    assert Permission.CALLS_HANDOFF in staff and Permission.CAMPAIGNS_WRITE not in staff
    writes = {p for p in Permission if p.value.endswith((".write", ".manage", ".control", ".import", ".delete"))}
    # memory.manage covers only the viewer's own user-private memory (RLS restrictive policy), not tenant data.
    assert not (viewer & (writes - {Permission.MEMORY_MANAGE}))
    assert ROLE_PERMISSIONS[TenantRole.MEMBER].isdisjoint({Permission.CALLS_READ, Permission.CONTACTS_WRITE})


def test_catalog_has_calling_agent_keys() -> None:
    assert CATALOG_VERSION == 2
    assert CAPABILITIES["voice.crm"].dependencies == ("voice.agents",)
    assert CAPABILITIES["voice.appointments"].dependencies == ("voice.crm",)
    assert CAPABILITIES["connector.erpnext"].dependencies == ("connect.embed",)


async def test_new_roles_accepted_by_schema(client) -> None:
    from app.core.db import DbScope, unit_of_work

    async with unit_of_work(scope=DbScope.PLATFORM) as db:
        defn = await db.scalar(
            text("select pg_get_constraintdef(oid) from pg_constraint where conname = 'ck_memberships_role'")
        )
        keys = set((await db.scalars(text("select key from capability_catalog where active"))).all())
    assert "'manager'" in defn and "'viewer'" in defn
    assert {"voice.crm", "voice.appointments", "connector.erpnext"} <= keys
