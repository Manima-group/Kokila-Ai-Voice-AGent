import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class CalendarConnection(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "calendar_connections"
    provider: Mapped[str] = mapped_column(String(20))  # google | internal
    label: Mapped[str] = mapped_column(String(120))
    calendar_id: Mapped[str] = mapped_column(String(300), default="primary")
    encrypted_tokens: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    business_hours: Mapped[dict] = mapped_column(JSONB, default=lambda: {"start": "10:00", "end": "18:00", "days": [0, 1, 2, 3, 4, 5]})
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")


class Appointment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    # Overlap protection: an EXCLUDE constraint on (calendar_connection_id, tstzrange(start_at,end_at))
    # for active statuses is created in the migration (requires btree_gist).
    calendar_connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calendar_connections.id", ondelete="RESTRICT"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"))
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(25), default="requested", index=True)
    # requested | pending_confirmation | confirmed | cancelled | failed
    idempotency_key: Mapped[str] = mapped_column(String(120))
    external_event_id: Mapped[str | None] = mapped_column(String(200))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
