"""Authoritative commercial access tables (§25, §26.3).

The generic ``entitlements`` entity is a *projection* of plan_capabilities +
tenant_capability_overrides + platform_capability_controls, never a writable table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, uuid_pk


class CapabilityCatalog(Base, Timestamps):
    __tablename__ = "capability_catalog"
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(40), nullable=False)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    product: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quota_metric: Mapped[str | None] = mapped_column(String(64))
    purchasable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CapabilityDependency(Base):
    """Normalized dependency edges with referential integrity (§26.3)."""

    __tablename__ = "capability_dependencies"
    __table_args__ = (CheckConstraint("capability_key <> depends_on", name="no_self_edge"),)
    capability_key: Mapped[str] = mapped_column(
        ForeignKey("capability_catalog.key", ondelete="CASCADE"), primary_key=True
    )
    depends_on: Mapped[str] = mapped_column(ForeignKey("capability_catalog.key", ondelete="RESTRICT"), primary_key=True)


class PlatformCapabilityControl(Base):
    """Global kill switch per capability."""

    __tablename__ = "platform_capability_controls"
    capability_key: Mapped[str] = mapped_column(ForeignKey("capability_catalog.key"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Plan(Base, CreatedAt):
    """Immutable plan versions; subscriptions reference the actual version."""

    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_plans_code_version"),
        CheckConstraint("price_minor >= 0", name="price_nonneg"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    product: Mapped[str] = mapped_column(String(24), nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PlanCapability(Base):
    __tablename__ = "plan_capabilities"
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    capability_key: Mapped[str] = mapped_column(ForeignKey("capability_catalog.key"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Subscription(Base, Timestamps):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("status in ('trialing','active','past_due','cancelled')", name="status"),
        Index(
            "uq_subscriptions_one_active",
            "tenant_id",
            unique=True,
            postgresql_where="status in ('trialing','active','past_due')",
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(24))
    provider_ref: Mapped[str | None] = mapped_column(String(128))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class TenantCapabilityOverride(Base):
    __tablename__ = "tenant_capability_overrides"
    __table_args__ = (CheckConstraint("revision > 0", name="revision_positive"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    capability_key: Mapped[str] = mapped_column(ForeignKey("capability_catalog.key"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class PolicyRevision(Base, CreatedAt):
    """Append-only history of tenant policy changes (§27.2)."""

    __tablename__ = "policy_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "revision", name="uq_policy_revisions_tenant_revision"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
