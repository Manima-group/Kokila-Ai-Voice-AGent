from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, tenant_fk, uuid_pk

_STATUSES = (
    "requested",
    "validating",
    "awaiting_approval",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "unknown_outcome",
)


class ToolRun(Base, Timestamps):
    """Durable tool action ledger (§15, §24.2)."""

    __tablename__ = "tool_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tool_runs_tenant_id_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tool_runs_tenant_idempotency"),
        CheckConstraint("status in (" + ",".join(f"'{s}'" for s in _STATUSES) + ")", name="status"),
        Index("ix_tool_runs_tenant_status_created", "tenant_id", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tool_key: Mapped[str] = mapped_column(String(96), nullable=False)
    tool_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    capability_key: Mapped[str] = mapped_column(String(96), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(16), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class ApprovalRequest(Base, Timestamps):
    """Approval bound to identity, exact args hash, scope and expiry (§15)."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        tenant_fk("run_id", "tool_runs"),
        UniqueConstraint("run_id", name="uq_approval_requests_one_per_run"),
        CheckConstraint("decision in ('pending','approved','denied','expired')", name="decision"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
