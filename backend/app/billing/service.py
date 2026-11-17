import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, PaymentRequired

TRIAL_DAYS = 14
ACTIVE_STATUSES = ("trialing", "active")
LIVE_CALL_STATUSES = ("queued", "provider_accepted", "ringing", "in_progress")


def _models():
    from app.billing.models import Plan, Subscription, UsageRecord

    return Plan, Subscription, UsageRecord


def start_trial(db: Session, tenant_id: uuid.UUID) -> None:
    Plan, Subscription, _ = _models()
    plan = db.scalar(select(Plan).where(Plan.code == "trial"))
    if plan is None:
        raise AppError("Trial plan not configured (run migrations)", code="plan_missing", status_code=500)
    now = datetime.now(UTC)
    db.add(
        Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="trialing",
            current_period_start=now,
            current_period_end=now + timedelta(days=TRIAL_DAYS),
            is_current=True,
        )
    )


@dataclass
class Entitlement:
    subscription: Any
    plan: Any
    minutes_used: float

    @property
    def minutes_remaining(self) -> float:
        return self.plan.included_minutes - self.minutes_used  # type: ignore[attr-defined]


def current_entitlement(db: Session, tenant_id: uuid.UUID) -> Entitlement | None:
    Plan, Subscription, UsageRecord = _models()
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id, Subscription.is_current.is_(True)))
    if sub is None:
        return None
    now = datetime.now(UTC)
    if sub.status in ACTIVE_STATUSES and sub.current_period_end < now:
        sub.status = "expired" if sub.status == "trialing" else "past_due"
        db.flush()
    plan = db.get(Plan, sub.plan_id)
    used = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.kind == "voice_minutes",
            UsageRecord.is_mock.is_(False),
            UsageRecord.occurred_at >= sub.current_period_start,
            UsageRecord.occurred_at < sub.current_period_end,
        )
    )
    return Entitlement(subscription=sub, plan=plan, minutes_used=float(used or 0))


def require_active(db: Session, tenant_id: uuid.UUID) -> Entitlement:
    ent = current_entitlement(db, tenant_id)
    if ent is None or ent.subscription.status not in ACTIVE_STATUSES:  # type: ignore[attr-defined]
        raise PaymentRequired("No active subscription", code="subscription_inactive")
    return ent


def require_feature(db: Session, tenant_id: uuid.UUID, feature: str) -> Entitlement:
    ent = require_active(db, tenant_id)
    if not ent.plan.features.get(feature, False):  # type: ignore[attr-defined]
        raise PaymentRequired(f"Your plan does not include '{feature}'", code="feature_not_in_plan")
    return ent


def check_call_allowed(db: Session, tenant_id: uuid.UUID) -> Entitlement:
    """Gate before any call is placed: subscription, minutes, concurrency."""
    from app.telephony.models import Call

    ent = require_active(db, tenant_id)
    if ent.minutes_remaining <= 0 and ent.plan.overage_per_minute_minor is None:  # type: ignore[attr-defined]
        raise PaymentRequired("Included minutes exhausted for this billing period", code="minutes_exhausted")
    live = db.scalar(select(func.count()).select_from(Call).where(Call.tenant_id == tenant_id, Call.status.in_(LIVE_CALL_STATUSES))) or 0
    if live >= ent.plan.max_concurrent_calls:  # type: ignore[attr-defined]
        raise PaymentRequired("Concurrent call limit reached", code="concurrency_limit")
    return ent


def billable_minutes(duration_seconds: int) -> float:
    return float(math.ceil(max(duration_seconds, 0) / 60)) if duration_seconds > 0 else 0.0


def record_call_usage(db: Session, call) -> None:
    """Idempotent: UNIQUE(call_id, kind) prevents double-metering on duplicate provider events."""
    _, _, UsageRecord = _models()
    exists = db.scalar(select(UsageRecord.id).where(UsageRecord.call_id == call.id, UsageRecord.kind == "voice_minutes"))
    if exists or not call.duration_seconds:
        return
    db.add(
        UsageRecord(
            tenant_id=call.tenant_id,
            call_id=call.id,
            kind="voice_minutes",
            quantity=billable_minutes(call.duration_seconds),
            provider_cost_minor=call.provider_cost_minor,
            is_mock=call.is_mock,
            occurred_at=call.ended_at or datetime.now(UTC),
        )
    )


def gst_breakup(subtotal_minor: int) -> tuple[int, int]:
    tax = round(subtotal_minor * get_settings().gst_rate_percent / 100)
    return tax, subtotal_minor + tax
