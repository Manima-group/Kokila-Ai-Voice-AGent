from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.appointments.service import reconcile_pending
from app.audit.router import apply_retention as _apply_retention
from app.billing.models import Subscription
from app.calls.webhooks import process_stored_event
from app.campaigns.service import dispatch_all
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.models import WebhookEvent
from app.integrations.outbox import process_outbox as _process_outbox
from app.workers.celery_app import celery_app

MAX_WEBHOOK_ATTEMPTS = 6


@celery_app.task(name="kokila.dispatch_campaigns")
def dispatch_campaigns() -> dict:
    with SessionLocal() as db:
        return dispatch_all(db)


@celery_app.task(name="kokila.process_outbox")
def process_outbox() -> dict:
    with SessionLocal() as db:
        return _process_outbox(db)


@celery_app.task(name="kokila.retry_failed_webhooks")
def retry_failed_webhooks() -> dict:
    out: dict[str, int] = {}
    with SessionLocal() as db:
        ids = db.scalars(
            select(WebhookEvent.id)
            .where(WebhookEvent.status == "failed", WebhookEvent.attempts < MAX_WEBHOOK_ATTEMPTS, WebhookEvent.source.in_(("retell", "mock")))
            .limit(200)
        ).all()
        for i in ids:
            r = process_stored_event(db, i)
            out[r] = out.get(r, 0) + 1
    return out


@celery_app.task(name="kokila.reconcile_appointments")
def reconcile_appointments() -> dict:
    with SessionLocal() as db:
        return reconcile_pending(db)


@celery_app.task(name="kokila.expire_subscriptions")
def expire_subscriptions() -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        n = db.execute(
            update(Subscription)
            .where(Subscription.is_current.is_(True), Subscription.current_period_end < now, Subscription.status == "trialing")
            .values(status="expired")
        ).rowcount  # type: ignore[attr-defined]
        n += db.execute(
            update(Subscription)
            .where(Subscription.is_current.is_(True), Subscription.current_period_end < now, Subscription.status == "active")
            .values(status="past_due")
        ).rowcount  # type: ignore[attr-defined]
        db.commit()
        return n


@celery_app.task(name="kokila.apply_retention")
def apply_retention() -> dict:
    with SessionLocal() as db:
        return _apply_retention(db)


@celery_app.task(name="kokila.purge_raw_events")
def purge_raw_events() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().raw_event_retention_days)
    with SessionLocal() as db:
        n = db.execute(delete(WebhookEvent).where(WebhookEvent.created_at < cutoff, WebhookEvent.status.in_(("processed", "ignored")))).rowcount  # type: ignore[attr-defined]
        db.commit()
        return n


@celery_app.task(name="kokila.deliver_reminders")
def deliver_reminders() -> int:
    from app.assistant.service import deliver_due_reminders

    with SessionLocal() as db:
        return deliver_due_reminders(db)
