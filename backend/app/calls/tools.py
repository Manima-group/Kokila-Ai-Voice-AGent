"""Server-side implementations of agent tools. Arguments come from an LLM and are treated as untrusted."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.models import Agent, AgentVersion
from app.appointments.service import available_slots, book, default_connection
from app.contacts.models import Contact, Lead, LeadActivity
from app.contacts.service import suppress
from app.core.errors import AppError
from app.integrations.outbox import emit
from app.telephony.models import Call


def _s(args: dict, key: str, maxlen: int = 300) -> str | None:
    v = args.get(key)
    if v is None:
        return None
    return str(v).strip()[:maxlen] or None


def _allowed(db: Session, call: Call, tool: str) -> bool:
    if not call.agent_id:
        return False
    agent = db.get(Agent, call.agent_id)
    if not agent or agent.tenant_id != call.tenant_id:
        return False
    version = db.get(AgentVersion, call.agent_version_id or agent.published_version_id) if (call.agent_version_id or agent.published_version_id) else None
    return bool(version and tool in version.config.get("allowed_tools", []))


def _lead(db: Session, call: Call, contact: Contact) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.tenant_id == call.tenant_id, Lead.contact_id == contact.id).order_by(Lead.created_at.desc()))
    if lead is None:
        lead = Lead(tenant_id=call.tenant_id, contact_id=contact.id, source=f"{call.direction}_call", qualification={})
        db.add(lead)
        db.flush()
    return lead


def execute_tool(db: Session, call: Call, name: str, args: dict) -> dict:
    if not isinstance(args, dict):
        args = {}
    if name not in ("record_opt_out",) and not _allowed(db, call, name):
        # Opt-out is always honoured, even if not configured on the agent.
        return {"status": "error", "message": "This action is not available. Offer a human follow-up."}
    contact = db.get(Contact, call.contact_id) if call.contact_id else None

    if name == "record_opt_out":
        if contact:
            suppress(db, call.tenant_id, contact.phone_e164, "opt_out", "voice_agent")
        call.outcome = "do_not_call"
        emit(db, call.tenant_id, "contact.opted_out", {"call_id": str(call.id)})
        return {"status": "opted_out", "message": "The number has been removed from future calls."}

    if contact is None:
        return {"status": "error", "message": "Caller number unavailable; offer a human follow-up."}

    if name == "capture_lead":
        if _s(args, "name") and not contact.name:
            contact.name = _s(args, "name", 200)
        email = _s(args, "email", 320)
        if email and "@" in email and not contact.email:
            contact.email = email
        lead = _lead(db, call, contact)
        lead.qualification = {**(lead.qualification or {}), **{k: _s(args, k) for k in ("interest", "budget", "timeline") if _s(args, k)}}
        db.add(LeadActivity(tenant_id=call.tenant_id, lead_id=lead.id, kind="note", body="Details captured by voice agent", call_id=call.id))
        return {"status": "saved"}

    if name == "check_availability":
        try:
            day = date.fromisoformat(_s(args, "date", 10) or "")
        except ValueError:
            return {"status": "error", "message": "Please ask for the date again (YYYY-MM-DD)."}
        if day > datetime.now(UTC).date() + timedelta(days=90):
            return {"status": "error", "message": "Bookings are only available up to 90 days ahead."}
        try:
            conn = default_connection(db, call.tenant_id)
            slots = available_slots(db, conn, day)
        except AppError as exc:
            return {"status": "unavailable", "message": "Booking is not available right now. Offer a callback.", "code": exc.code}
        except Exception:  # noqa: BLE001 - external calendar down
            return {"status": "unavailable", "message": "The calendar is unavailable. Offer a callback."}
        return {"status": "ok", "timezone": conn.timezone, "slots": [s.isoformat() for s in slots[:8]]}

    if name == "book_appointment":
        raw = _s(args, "start", 40) or ""
        try:
            start = datetime.fromisoformat(raw)
        except ValueError:
            return {"status": "error", "message": "Invalid time; check availability again."}
        if _s(args, "name") and not contact.name:
            contact.name = _s(args, "name", 200)
        lead = _lead(db, call, contact)
        try:
            appt = book(
                db,
                call.tenant_id,
                start=start,
                title=f"{_s(args, 'purpose', 120) or 'Appointment'} - {contact.name or contact.phone_e164}",
                idempotency_key=f"call:{call.id}:{start.isoformat()}",
                contact_id=contact.id,
                lead_id=lead.id,
                call_id=call.id,
            )
        except AppError as exc:
            return {"status": "not_booked", "reason": exc.code, "message": "That slot could not be booked. Offer another slot."}
        if appt.status == "confirmed":
            call.outcome = "appointment_confirmed"
            return {"status": "confirmed", "appointment_id": str(appt.id), "start": appt.start_at.isoformat()}
        return {"status": appt.status, "message": "The booking is not confirmed yet. Tell the caller the team will confirm."}

    if name == "request_human_transfer":
        call.handoff_requested = True
        lead = _lead(db, call, contact)
        db.add(
            LeadActivity(
                tenant_id=call.tenant_id,
                lead_id=lead.id,
                kind="task",
                call_id=call.id,
                body=f"Human handoff requested: {_s(args, 'reason', 300) or 'n/a'}",
                due_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        emit(db, call.tenant_id, "call.handoff_requested", {"call_id": str(call.id), "reason": _s(args, "reason", 300)})
        from app.assistant.models import Notification

        db.add(
            Notification(
                tenant_id=call.tenant_id,
                user_id=None,
                kind="handoff",
                title="Caller asked for a human",
                body=_s(args, "reason", 300),
                link=f"/calling-agent/calls/{call.id}",
            )
        )
        return {"status": "requested", "message": "A team member has been notified and will follow up."}

    return {"status": "error", "message": "Unknown action"}
