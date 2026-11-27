import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Contact(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "contacts"
    # Same phone may exist in many tenants, but only once per tenant.
    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164"),)
    phone_e164: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    language: Mapped[str | None] = mapped_column(String(10))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(30), default="manual")


class Lead(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "leads"
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_outcome: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualification: Mapped[dict] = mapped_column(JSONB, default=dict)


class LeadActivity(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "lead_activities"
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # note | call | status_change | task | assignment
    body: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactConsent(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "contact_consents"
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(60))  # e.g. "sales", "service", "appointment_reminder"
    channel: Mapped[str] = mapped_column(String(20), default="voice")
    status: Mapped[str] = mapped_column(String(20), default="granted")  # granted | revoked
    source: Mapped[str] = mapped_column(String(60))  # web_form | ivr | written | call_recording | import
    evidence: Mapped[str | None] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_consent: Mapped[bool] = mapped_column(Boolean, default=False)


class SuppressionEntry(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164"),)
    phone_e164: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(40))  # opt_out | dnd | complaint | manual
    source: Mapped[str] = mapped_column(String(40), default="manual")
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
