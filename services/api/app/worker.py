"""Celery worker: transactional-outbox dispatch (§24.2, §32.2).

Run:  celery -A app.worker worker -B --loglevel=INFO   (single beat scheduler per deployment)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import orjson
from celery import Celery
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import DbScope, dispose_engine, unit_of_work
from app.core.ratelimit import close_redis, redis_client
from app.models import OutboxEvent

log = logging.getLogger("kokila.worker")
settings = get_settings()
celery_app = Celery("kokila", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    beat_schedule={"dispatch-outbox": {"task": "kokila.dispatch_outbox", "schedule": 2.0}},
    timezone="UTC",
)

BATCH = 200
MAX_ATTEMPTS = 10


def channel_for(tenant_id: str) -> str:
    return f"kokila:{settings.env.value}:events:v1:{tenant_id}"


async def dispatch_outbox_once() -> int:
    """Claim pending events with SKIP LOCKED so concurrent workers never double-publish a row."""
    sent = 0
    async with unit_of_work(scope=DbScope.SYSTEM) as db:
        rows = (
            await db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending", OutboxEvent.next_attempt_at <= datetime.now(UTC))
                .order_by(OutboxEvent.created_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        r = redis_client()
        for ev in rows:
            try:
                await r.publish(
                    channel_for(str(ev.tenant_id)),
                    orjson.dumps(
                        {
                            "id": str(ev.id),
                            "type": ev.event_type,
                            "payload": ev.payload,
                            "created_at": ev.created_at.isoformat(),
                        }
                    ),
                )
            except OSError:
                ev.attempts += 1
                ev.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(300, 2**ev.attempts))
                if ev.attempts >= MAX_ATTEMPTS:
                    ev.status = "failed"
                continue
            ev.status, ev.dispatched_at = "dispatched", datetime.now(UTC)
            sent += 1
    return sent


async def _run(coro_fn) -> int:
    try:
        return await coro_fn()
    finally:
        await close_redis()
        await dispose_engine()


@celery_app.task(name="kokila.dispatch_outbox")
def dispatch_outbox() -> int:
    return asyncio.run(_run(dispatch_outbox_once))
