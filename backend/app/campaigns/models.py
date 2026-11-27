import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Campaign(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(60))  # must match a consent purpose
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"))
    from_phone_number_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    window_start: Mapped[str] = mapped_column(String(5), default="10:00")
    window_end: Mapped[str] = mapped_column(String(5), default="19:00")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    days_of_week: Mapped[list] = mapped_column(JSONB, default=lambda: [0, 1, 2, 3, 4, 5])
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    retry_delay_minutes: Mapped[int] = mapped_column(Integer, default=120)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)


class CampaignContact(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (UniqueConstraint("campaign_id", "contact_id"),)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | eligible | ineligible | in_progress | completed | exhausted | cancelled
    ineligible_reason: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_outcome: Mapped[str | None] = mapped_column(String(40))


class CallAttempt(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "call_attempts"
    __table_args__ = (UniqueConstraint("campaign_contact_id", "attempt_no"),)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_contacts.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | dispatched | in_progress | completed | failed
    provider_call_id: Mapped[str | None] = mapped_column(String(120))
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    outcome: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
