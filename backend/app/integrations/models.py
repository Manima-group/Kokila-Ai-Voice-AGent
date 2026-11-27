import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class IntegrationConnection(IdMixin, TimestampMixin, TenantMixin, Base):
    """Outbound webhook / n8n endpoints that receive signed Kokila events."""

    __tablename__ = "integration_connections"
    kind: Mapped[str] = mapped_column(String(20))  # webhook | n8n | email
    name: Mapped[str] = mapped_column(String(120))
    target_url: Mapped[str | None] = mapped_column(Text)
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    event_types: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")


class WebhookEvent(IdMixin, TimestampMixin, Base):
    """Inbound provider webhook ledger (deduplicated). tenant_id is nullable until resolved."""

    __tablename__ = "webhook_events"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(30))  # retell | mock | razorpay
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|processed|failed|ignored
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(IdMixin, TimestampMixin, Base):
    """Transactional outbox: written in the same transaction as the business change."""

    __tablename__ = "outbox_events"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|sent|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)


class BackgroundJobFailure(IdMixin, TimestampMixin, Base):
    __tablename__ = "background_job_failures"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    task_name: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(default=False)
