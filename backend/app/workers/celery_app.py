import logging

from celery import Celery
from celery.signals import task_failure

from app.core.config import get_settings

celery_app = Celery("kokila", broker=get_settings().redis_url, backend=None, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    timezone="UTC",
    beat_schedule={
        "dispatch-campaigns": {"task": "kokila.dispatch_campaigns", "schedule": 30.0},
        "process-outbox": {"task": "kokila.process_outbox", "schedule": 15.0},
        "deliver-reminders": {"task": "kokila.deliver_reminders", "schedule": 30.0},
        "retry-webhooks": {"task": "kokila.retry_failed_webhooks", "schedule": 60.0},
        "reconcile-appointments": {"task": "kokila.reconcile_appointments", "schedule": 300.0},
        "expire-subscriptions": {"task": "kokila.expire_subscriptions", "schedule": 3600.0},
        "apply-retention": {"task": "kokila.apply_retention", "schedule": 86400.0},
        "purge-raw-events": {"task": "kokila.purge_raw_events", "schedule": 86400.0},
    },
)

log = logging.getLogger("kokila.worker")


@task_failure.connect
def _record_failure(sender=None, task_id=None, exception=None, args=None, **_kw):  # pragma: no cover - signal glue
    from app.db.session import SessionLocal
    from app.integrations.models import BackgroundJobFailure

    try:
        with SessionLocal() as db:
            db.add(BackgroundJobFailure(task_name=getattr(sender, "name", "unknown"), reference=task_id, error=str(exception)[:2000]))
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("could not record task failure")
