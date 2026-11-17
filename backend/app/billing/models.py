import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Plan(IdMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    price_minor: Mapped[int] = mapped_column(Integer)  # paise per period, excl. GST
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    interval_months: Mapped[int] = mapped_column(Integer, default=1)
    included_minutes: Mapped[int] = mapped_column(Integer)
    overage_per_minute_minor: Mapped[int | None] = mapped_column(Integer)  # None = hard cap, no overage
    max_agents: Mapped[int] = mapped_column(Integer)
    max_concurrent_calls: Mapped[int] = mapped_column(Integer)
    max_users: Mapped[int] = mapped_column(Integer)
    features: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"outbound": true, "calendar": true, ...}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "subscriptions"
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), index=True)  # trialing|active|past_due|cancelled|expired
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class UsageRecord(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("call_id", "kind"),)
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30), default="voice_minutes")
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))  # billable minutes (rounded up per call)
    provider_cost_minor: Mapped[int | None] = mapped_column(Integer)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PaymentTransaction(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "payment_transactions"
    razorpay_order_id: Mapped[str] = mapped_column(String(60), unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(60), unique=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(25), default="created")
    # created | client_verified | captured | failed
    purpose: Mapped[str] = mapped_column(String(30), default="subscription")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class Invoice(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "invoices"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payment_transactions.id", ondelete="SET NULL"), unique=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subtotal_minor: Mapped[int] = mapped_column(Integer)
    tax_minor: Mapped[int] = mapped_column(Integer)
    total_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="paid")
    line_items: Mapped[list] = mapped_column(JSONB, default=list)
