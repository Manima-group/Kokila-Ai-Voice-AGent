"""Call state machine and provider event processing (idempotent, order-tolerant)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.agents.templates import OUTCOMES
from app.billing.service import record_call_usage
from app.contacts.service import apply_outcome_to_lead, get_or_create_contact, suppress
from app.core.phone import try_normalize
from app.integrations.outbox import emit
from app.telephony.models import Call, CallEvent, PhoneNumber
from app.voice.base import NormalizedEvent

log = logging.getLogger("kokila.calls")

RANK = {"created": 0, "queued": 1, "provider_accepted": 2, "ringing": 3, "in_progress": 4}
TERMINAL = {"completed", "failed", "cancelled"}

# Retell disconnection_reason -> (call status, outcome)
DISCONNECT_MAP: dict[str, tuple[str, str | None]] = {
    "dial_busy": ("failed", "busy"),
    "dial_no_answer": ("failed", "no_answer"),
    "dial_failed": ("failed", "failed"),
    "voicemail_reached": ("completed", "voicemail"),
    "call_transfer": ("completed", "human_transfer"),
}


class EventRejected(Exception):
    pass


def can_transition(current: str, new: str) -> bool:
    if current in TERMINAL:
        return False
    if new in TERMINAL:
        return True
    return RANK.get(new, -1) > RANK.get(current, -1)


def transition(call: Call, new: str) -> bool:
    if can_transition(call.status, new):
        call.status = new
        return True
    return False


def resolve_tenant_for_new_call(db: Session, provider: str, route_key: str, ev: NormalizedEvent) -> tuple[uuid.UUID, dict]:
    """Determine the owning tenant for a call we have not seen. Never trusts unverifiable input."""
    meta = ev.metadata or {}
    attempt_id = meta.get("kokila_attempt_id")
    if attempt_id:
        from app.campaigns.models import CallAttempt

        attempt = db.get(CallAttempt, uuid.UUID(str(attempt_id)))
        if attempt is None or str(attempt.tenant_id) != str(meta.get("kokila_tenant_id")):
            raise EventRejected("attempt metadata does not match a known attempt")
        return attempt.tenant_id, {"campaign_id": attempt.campaign_id, "call_attempt_id": attempt.id, "direction": "outbound"}
    if meta.get("kokila_test_call") and meta.get("kokila_tenant_id"):
        return uuid.UUID(str(meta["kokila_tenant_id"])), {"direction": ev.direction or "outbound"}
    to_number = try_normalize(ev.to_number)
    if not to_number:
        raise EventRejected("cannot resolve tenant: missing/invalid to_number")
    number = db.scalar(select(PhoneNumber).where(PhoneNumber.route_key == route_key, PhoneNumber.e164 == to_number, PhoneNumber.status == "active"))
    if number is None:
        raise EventRejected("no active phone number mapping for inbound call")
    extra: dict = {"phone_number_id": number.id, "direction": "inbound"}
    if ev.provider_agent_id:
        agent = db.scalar(select(Agent).where(Agent.provider == provider, Agent.provider_agent_id == ev.provider_agent_id))
        if agent is not None and agent.tenant_id != number.tenant_id:
            raise EventRejected("agent/number tenant mismatch")
    return number.tenant_id, extra


def ensure_call(db: Session, provider: str, route_key: str, ev: NormalizedEvent, *, is_mock: bool) -> Call:
    assert ev.provider_call_id
    call = db.scalar(select(Call).where(Call.provider == provider, Call.provider_call_id == ev.provider_call_id).with_for_update())
    if call:
        return call
    tenant_id, extra = resolve_tenant_for_new_call(db, provider, route_key, ev)
    agent = None
    if ev.provider_agent_id:
        agent = db.scalar(select(Agent).where(Agent.tenant_id == tenant_id, Agent.provider_agent_id == ev.provider_agent_id))
    if agent is None and extra.get("phone_number_id"):
        num = db.get(PhoneNumber, extra["phone_number_id"])
        agent = db.get(Agent, num.inbound_agent_id) if num and num.inbound_agent_id else None
    direction = extra.pop("direction", ev.direction or "inbound")
    remote = ev.from_number if direction == "inbound" else ev.to_number
    remote_e164 = try_normalize(remote)
    contact = get_or_create_contact(db, tenant_id, remote_e164, source=f"{direction}_call") if remote_e164 else None
    call = Call(
        tenant_id=tenant_id,
        provider=provider,
        provider_call_id=ev.provider_call_id,
        direction=direction,
        agent_id=agent.id if agent else None,
        agent_version_id=agent.published_version_id if agent else None,
        from_number=try_normalize(ev.from_number),
        to_number=try_normalize(ev.to_number),
        contact_id=contact.id if contact else None,
        status="created",
        is_mock=is_mock,
        extracted={},
        **extra,
    )
    try:
        with db.begin_nested():
            db.add(call)
            db.flush()
    except IntegrityError:
        # Concurrent event created the same call; lock and return it.
        call = db.scalar(select(Call).where(Call.provider == provider, Call.provider_call_id == ev.provider_call_id).with_for_update())
        assert call is not None
    return call


def apply_event(db: Session, provider: str, route_key: str, ev: NormalizedEvent, *, is_mock: bool = False) -> tuple[Call, bool]:
    """Apply one provider event. Returns (call, applied). Duplicate events are no-ops."""
    call = ensure_call(db, provider, route_key, ev, is_mock=is_mock)
    try:
        with db.begin_nested():
            db.add(
                CallEvent(
                    tenant_id=call.tenant_id, call_id=call.id, event_type=ev.event_type, dedupe_key=ev.dedupe_key, occurred_at=ev.ended_at or ev.started_at
                )
            )
            db.flush()
    except IntegrityError:
        return call, False  # duplicate delivery

    now = datetime.now(UTC)
    applied = True
    if ev.event_type == "call_started":
        applied = transition(call, "in_progress")
        call.started_at = call.started_at or ev.started_at or now
    elif ev.event_type == "call_ended":
        _apply_end(call, ev)
    elif ev.event_type == "call_analyzed":
        _apply_analysis(call, ev)
        if call.status not in TERMINAL and ev.ended_at:
            _apply_end(call, ev)
    elif ev.event_type in ("transfer_started", "transfer_bridged"):
        call.handoff_requested = True
    else:
        applied = False
    call.last_event_at = now
    if not applied:
        db.execute(update(CallEvent).where(CallEvent.dedupe_key == ev.dedupe_key).values(applied=False, note="stale_or_unsupported"))
    if ev.event_type in ("call_ended", "call_analyzed"):
        _post_process(db, call, ev)
    return call, applied


def _apply_end(call: Call, ev: NormalizedEvent) -> None:
    status, outcome = DISCONNECT_MAP.get(ev.disconnection_reason or "", (None, None))
    if status is None:
        status = "failed" if (ev.disconnection_reason or "").startswith("error") else "completed"
    transition(call, status)
    call.started_at = call.started_at or ev.started_at
    call.ended_at = ev.ended_at or call.ended_at or datetime.now(UTC)
    if ev.duration_seconds is not None:
        call.duration_seconds = ev.duration_seconds
    call.disconnection_reason = ev.disconnection_reason
    if outcome and not call.outcome:
        call.outcome = outcome
    if ev.transcript:
        call.transcript, call.transcript_segments = ev.transcript, ev.segments
    if ev.recording_url:
        call.recording_url = ev.recording_url
    if ev.cost_minor is not None:
        call.provider_cost_minor = ev.cost_minor
    if call.analysis_status == "pending":
        call.analysis_status = "processing"


def _apply_analysis(call: Call, ev: NormalizedEvent) -> None:
    call.summary = ev.summary or call.summary
    call.sentiment = (ev.sentiment or "").lower() or call.sentiment
    data = dict(ev.analysis or {})
    outcome = data.get("outcome")
    if outcome in OUTCOMES and call.outcome not in ("voicemail", "busy", "no_answer"):
        call.outcome = outcome
    call.extracted = {**(call.extracted or {}), **data}
    if ev.transcript:
        call.transcript, call.transcript_segments = ev.transcript, ev.segments
    if ev.cost_minor is not None:
        call.provider_cost_minor = ev.cost_minor
    call.analysis_status = "completed"


def _post_process(db: Session, call: Call, ev: NormalizedEvent) -> None:
    from app.campaigns.service import on_call_finished
    from app.contacts.models import Contact

    if call.status in TERMINAL:
        record_call_usage(db, call)
    contact = db.get(Contact, call.contact_id) if call.contact_id else None
    if call.outcome == "do_not_call" and contact:
        suppress(db, call.tenant_id, contact.phone_e164, "opt_out", "call")
    ready = ev.event_type == "call_analyzed" or (call.status in TERMINAL and call.outcome is not None)
    if contact and ready and not (call.extracted or {}).get("_crm_applied"):
        apply_outcome_to_lead(
            db, call.tenant_id, contact, call.outcome, call.id, "inbound_call" if call.direction == "inbound" else "campaign", call.summary, ev.analysis
        )
        call.extracted = {**(call.extracted or {}), "_crm_applied": True}
    if call.campaign_id:
        on_call_finished(db, call)
    emit(
        db,
        call.tenant_id,
        f"call.{ev.event_type.removeprefix('call_')}",
        {
            "call_id": str(call.id),
            "status": call.status,
            "outcome": call.outcome,
            "direction": call.direction,
            "duration_seconds": call.duration_seconds,
            "handoff_requested": call.handoff_requested,
        },
    )
