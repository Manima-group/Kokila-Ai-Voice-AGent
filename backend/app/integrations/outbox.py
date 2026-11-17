import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.integrations.models import IntegrationConnection, OutboxEvent

MAX_ATTEMPTS = 8


def emit(db: Session, tenant_id: uuid.UUID | None, event_type: str, payload: dict) -> None:
    """Write an outbox row in the caller's transaction (transactional outbox)."""
    db.add(OutboxEvent(tenant_id=tenant_id, event_type=event_type, payload=payload))


def sign_payload(secret: str, body: bytes, ts: int) -> str:
    return hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def _deliver(conn: IntegrationConnection, event: OutboxEvent, http: httpx.Client) -> None:
    body = json.dumps(
        {"id": str(event.id), "type": event.event_type, "tenant_id": str(event.tenant_id), "created_at": event.created_at.isoformat(), "data": event.payload}
    ).encode()
    ts = int(datetime.now(UTC).timestamp())
    headers = {"Content-Type": "application/json", "X-Kokila-Event": event.event_type, "X-Kokila-Timestamp": str(ts), "X-Kokila-Delivery": str(event.id)}
    if conn.encrypted_secret:
        headers["X-Kokila-Signature"] = "sha256=" + sign_payload(decrypt_secret(conn.encrypted_secret), body, ts)
    r = http.post(conn.target_url or "", content=body, headers=headers, timeout=10)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code}")


def process_outbox(db: Session, http: httpx.Client | None = None, batch: int = 100) -> dict:
    """Deliver pending events to subscribed webhook/n8n endpoints with exponential backoff and dead-lettering."""
    http = http or httpx.Client()
    now = datetime.now(UTC)
    stats = {"sent": 0, "failed": 0, "dead": 0}
    events = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status.in_(("pending", "failed")), OutboxEvent.next_attempt_at <= now)
        .order_by(OutboxEvent.created_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for ev in events:
        targets = [
            c
            for c in db.scalars(
                select(IntegrationConnection).where(
                    IntegrationConnection.tenant_id == ev.tenant_id,
                    IntegrationConnection.status == "active",
                    IntegrationConnection.kind.in_(("webhook", "n8n")),
                )
            )
            if not c.event_types or ev.event_type in c.event_types
        ]
        try:
            for c in targets:
                _deliver(c, ev, http)
            ev.status = "sent"
            stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001
            ev.attempts += 1
            ev.last_error = str(exc)[:500]
            if ev.attempts >= MAX_ATTEMPTS:
                ev.status = "dead"
                stats["dead"] += 1
            else:
                ev.status = "failed"
                ev.next_attempt_at = now + timedelta(seconds=min(3600, 30 * 2**ev.attempts))
                stats["failed"] += 1
    db.commit()
    return stats
