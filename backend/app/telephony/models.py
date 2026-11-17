import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class ProviderAccount(IdMixin, TimestampMixin, TenantMixin, Base):
    """Tenant-owned voice provider credentials (encrypted)."""

    __tablename__ = "provider_accounts"
    provider: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(120))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")


class PhoneNumber(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "phone_numbers"
    # route_key = "<provider>:<provider_account_id|platform>". A number routes to exactly one tenant per account.
    __table_args__ = (UniqueConstraint("route_key", "e164"),)
    provider: Mapped[str] = mapped_column(String(30))
    provider_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("provider_accounts.id", ondelete="SET NULL"))
    route_key: Mapped[str] = mapped_column(String(80))
    e164: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    number_type: Mapped[str] = mapped_column(String(20), default="service")  # service(1600-series) | promotional(140-series) | other
    inbound_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    outbound_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Call(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (UniqueConstraint("provider", "provider_call_id"),)
    provider: Mapped[str] = mapped_column(String(30))
    provider_call_id: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(10))  # inbound | outbound
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="SET NULL"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    call_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    from_number: Mapped[str | None] = mapped_column(String(20))
    to_number: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    disconnection_reason: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str | None] = mapped_column(String(40), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_segments: Mapped[list | None] = mapped_column(JSONB)
    extracted: Mapped[dict] = mapped_column(JSONB, default=dict)
    language: Mapped[str | None] = mapped_column(String(10))
    recording_url: Mapped[str | None] = mapped_column(Text)
    provider_cost_minor: Mapped[int | None] = mapped_column(Integer)  # paise; None = unknown (never assumed zero)
    handoff_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": row_version}


class CallEvent(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "call_events"
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200))


class CallRecording(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "call_recordings"
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    storage_url: Mapped[str] = mapped_column(Text)
    consent_obtained: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
