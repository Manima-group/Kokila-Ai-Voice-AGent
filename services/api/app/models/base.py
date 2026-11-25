from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def tenant_fk(local: str, remote_table: str) -> ForeignKeyConstraint:
    """Composite tenant-aware FK (tenant_id, X) -> remote(tenant_id, id) (§24.2)."""
    return ForeignKeyConstraint(
        ["tenant_id", local], [f"{remote_table}.tenant_id", f"{remote_table}.id"], ondelete="CASCADE"
    )


# Tables protected by tenant RLS. Kept here so migrations and tests share one list.
TENANT_TABLES: tuple[str, ...] = (
    "memberships",
    "subscriptions",
    "tenant_capability_overrides",
    "policy_revisions",
    "conversations",
    "messages",
    "assistant_sessions",
    "memory_items",
    "assistant_identity_preferences",
    "tool_runs",
    "approval_requests",
    "usage_events",
    "audit_events",
    "outbox_events",
)
# Tables whose rows are additionally private to one user inside the tenant.
USER_PRIVATE_TABLES: tuple[str, ...] = ("conversations", "messages", "assistant_sessions", "memory_items")
# Control-plane tenant tables the platform scope may manage across tenants (no customer content).
PLATFORM_MANAGED_TABLES: tuple[str, ...] = (
    "memberships",
    "subscriptions",
    "tenant_capability_overrides",
    "policy_revisions",
    "audit_events",
    "outbox_events",
    "usage_events",
)
