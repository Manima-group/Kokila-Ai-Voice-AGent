"""Row-level security, least-privilege grants and append-only protections.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op
from app.models.base import PLATFORM_MANAGED_TABLES, TENANT_TABLES, USER_PRIVATE_TABLES

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "kokila_app"
CTX_TENANT = "nullif(current_setting('kokila.tenant_id', true), '')::uuid"
CTX_USER = "nullif(current_setting('kokila.user_id', true), '')::uuid"
CTX_SCOPE = "current_setting('kokila.scope', true)"
APPEND_ONLY = ("audit_events", "platform_audit_events", "policy_revisions", "usage_events")


def upgrade() -> None:
    op.execute(f"""
    do $$ begin
      if not exists (select 1 from pg_roles where rolname = '{APP_ROLE}') then
        create role {APP_ROLE} nologin nobypassrls;
      end if;
    end $$;
    """)
    op.execute(f"grant usage on schema public to {APP_ROLE}")
    op.execute(f"grant select, insert, update, delete on all tables in schema public to {APP_ROLE}")
    op.execute(f"grant select on alembic_version to {APP_ROLE}")
    for t in APPEND_ONLY:
        op.execute(f"revoke update, delete on {t} from {APP_ROLE}")
    # Global catalog / control tables are read-only to the app except through platform routes.
    for t in TENANT_TABLES:
        op.execute(f"alter table {t} enable row level security")
        op.execute(f"alter table {t} force row level security")
        op.execute(
            f"create policy tenant_isolation on {t} using (tenant_id = {CTX_TENANT}) "
            f"with check (tenant_id = {CTX_TENANT})"
        )
    for t in PLATFORM_MANAGED_TABLES:
        op.execute(
            f"create policy platform_manage on {t} using ({CTX_SCOPE} = 'platform') "
            f"with check ({CTX_SCOPE} = 'platform')"
        )
    for t in USER_PRIVATE_TABLES:
        owner = "(user_id is null or user_id = {u})" if t == "memory_items" else "user_id = {u}"
        op.execute(
            f"create policy user_private on {t} as restrictive "
            f"using ({owner.format(u=CTX_USER)}) with check ({owner.format(u=CTX_USER)})"
        )
    # A user can always see their own memberships (workspace switcher / login).
    op.execute(f"create policy own_memberships on memberships for select using (user_id = {CTX_USER})")
    # Workers dispatch outbox events across tenants under an explicit system scope.
    op.execute(
        f"create policy system_dispatch on outbox_events using ({CTX_SCOPE} = 'system') "
        f"with check ({CTX_SCOPE} = 'system')"
    )
    # Organizations: visible to the active tenant, its members, or the platform scope.
    op.execute("alter table organizations enable row level security")
    op.execute("alter table organizations force row level security")
    op.execute(f"""create policy org_visibility on organizations using (
        id = {CTX_TENANT} or {CTX_SCOPE} = 'platform'
        or exists (select 1 from memberships m where m.tenant_id = organizations.id and m.user_id = {CTX_USER})
      ) with check (id = {CTX_TENANT} or {CTX_SCOPE} = 'platform')""")


def downgrade() -> None:
    op.execute("drop policy if exists org_visibility on organizations")
    op.execute("alter table organizations disable row level security")
    op.execute("drop policy if exists system_dispatch on outbox_events")
    op.execute("drop policy if exists own_memberships on memberships")
    for t in USER_PRIVATE_TABLES:
        op.execute(f"drop policy if exists user_private on {t}")
    for t in PLATFORM_MANAGED_TABLES:
        op.execute(f"drop policy if exists platform_manage on {t}")
    for t in TENANT_TABLES:
        op.execute(f"drop policy if exists tenant_isolation on {t}")
        op.execute(f"alter table {t} disable row level security")
