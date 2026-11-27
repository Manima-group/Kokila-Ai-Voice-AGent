import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | system | provider | superadmin
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class DataRetentionPolicy(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "data_retention_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "resource"),)
    resource: Mapped[str] = mapped_column(String(40))  # transcripts | recordings | call_events | audit_logs
    retain_days: Mapped[int] = mapped_column(Integer)


class DeletionRequest(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "deletion_requests"
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | completed | failed
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
