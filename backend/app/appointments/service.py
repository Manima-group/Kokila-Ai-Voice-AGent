import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.appointments.calendar import CalendarError, calendar_for, event_id_for
from app.appointments.models import Appointment, CalendarConnection
from app.core.errors import AppError, Conflict, NotFound
from app.integrations.outbox import emit

ACTIVE = ("requested", "pending_confirmation", "confirmed")


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(f"Invalid timezone '{tz}'", code="invalid_timezone", status_code=422)


def default_connection(db: Session, tenant_id: uuid.UUID) -> CalendarConnection:
    conn = db.scalar(
        select(CalendarConnection)
        .where(CalendarConnection.tenant_id == tenant_id, CalendarConnection.status == "active")
        .order_by(CalendarConnection.created_at)
    )
    if not conn:
        raise AppError("No calendar connected", code="calendar_not_connected", status_code=409)
    return conn


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def available_slots(db: Session, conn: CalendarConnection, day: date) -> list[datetime]:
    tz = zone(conn.timezone)
    bh = conn.business_hours or {}
    if day.weekday() not in bh.get("days", [0, 1, 2, 3, 4, 5]):
        return []
    start = datetime.combine(day, _hhmm(bh.get("start", "10:00")), tz)
    end = datetime.combine(day, _hhmm(bh.get("end", "18:00")), tz)
    step = timedelta(minutes=conn.slot_minutes)
    busy = [
        (a.start_at, a.end_at)
        for a in db.scalars(
            select(Appointment).where(
                Appointment.calendar_connection_id == conn.id,
                Appointment.status.in_(ACTIVE),
                Appointment.start_at < end,
                Appointment.end_at > start,
            )
        )
    ]
    ext = calendar_for(conn)
    if ext is not None:
        busy += ext.busy(start, end)
    now = datetime.now(UTC)
    slots, cur = [], start
    while cur + step <= end:
        s_end = cur + step
        if cur > now and not any(b0 < s_end and b1 > cur for b0, b1 in busy):
            slots.append(cur)
        cur = s_end
    return slots


def _validate_slot(conn: CalendarConnection, start: datetime) -> datetime:
    if start.tzinfo is None:
        raise AppError("Start time must include a timezone offset", code="naive_datetime", status_code=422)
    tz = zone(conn.timezone)
    local = start.astimezone(tz)
    bh = conn.business_hours or {}
    if local.weekday() not in bh.get("days", [0, 1, 2, 3, 4, 5]):
        raise AppError("Outside business days", code="outside_hours", status_code=422)
    if not (_hhmm(bh.get("start", "10:00")) <= local.time() and (local + timedelta(minutes=conn.slot_minutes)).time() <= _hhmm(bh.get("end", "18:00"))):
        raise AppError("Outside business hours", code="outside_hours", status_code=422)
    if start <= datetime.now(UTC):
        raise AppError("Cannot book in the past", code="past_time", status_code=422)
    return local


def book(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    title: str,
    idempotency_key: str,
    contact_id=None,
    lead_id=None,
    call_id=None,
    connection: CalendarConnection | None = None,
    notes: str | None = None,
) -> Appointment:
    """Book a slot. Returns status 'confirmed' only after the authoritative calendar write succeeds."""
    existing = db.scalar(select(Appointment).where(Appointment.tenant_id == tenant_id, Appointment.idempotency_key == idempotency_key))
    if existing:
        return existing
    conn = connection or default_connection(db, tenant_id)
    local = _validate_slot(conn, start)
    ext = calendar_for(conn)
    appt = Appointment(
        tenant_id=tenant_id,
        calendar_connection_id=conn.id,
        contact_id=contact_id,
        lead_id=lead_id,
        call_id=call_id,
        title=title,
        start_at=local,
        end_at=local + timedelta(minutes=conn.slot_minutes),
        timezone=conn.timezone,
        status="pending_confirmation" if ext else "confirmed",
        idempotency_key=idempotency_key,
        notes=notes,
    )
    db.add(appt)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        dup = db.scalar(select(Appointment).where(Appointment.tenant_id == tenant_id, Appointment.idempotency_key == idempotency_key))
        if dup:
            return dup
        raise Conflict("That slot is no longer available", code="slot_unavailable") from exc
    if ext is None:
        emit(db, tenant_id, "appointment.confirmed", {"appointment_id": str(appt.id), "start": local.isoformat()})
        db.commit()
        return appt
    db.commit()  # reserve the slot locally (exclusion constraint) before the external call
    try:
        if ext.busy(appt.start_at, appt.end_at):
            appt.status, appt.failure_reason = "failed", "slot busy in external calendar"
            db.commit()
            raise Conflict("That slot is no longer available", code="slot_unavailable")
        appt.external_event_id = ext.create_event(event_id_for(appt.id), title, appt.start_at, appt.end_at, conn.timezone)
        appt.status = "confirmed"
        emit(db, tenant_id, "appointment.confirmed", {"appointment_id": str(appt.id), "start": local.isoformat()})
        db.commit()
    except CalendarError as exc:
        db.rollback()
        reloaded = db.get(Appointment, appt.id)
        assert reloaded is not None
        reloaded.status, reloaded.failure_reason = "failed", str(exc)
        db.commit()
        return reloaded
    return appt


def cancel(db: Session, appt: Appointment) -> Appointment:
    if appt.status == "cancelled":
        return appt
    conn = db.get(CalendarConnection, appt.calendar_connection_id)
    ext = calendar_for(conn) if conn else None
    if ext and appt.external_event_id:
        ext.delete_event(appt.external_event_id)
    appt.status = "cancelled"
    emit(db, appt.tenant_id, "appointment.cancelled", {"appointment_id": str(appt.id)})
    db.commit()
    return appt


def reschedule(db: Session, appt: Appointment, new_start: datetime) -> Appointment:
    if appt.status != "confirmed":
        raise AppError("Only confirmed appointments can be rescheduled", code="invalid_state", status_code=409)
    conn = db.get(CalendarConnection, appt.calendar_connection_id)
    if conn is None:
        raise NotFound("Calendar connection missing")
    local = _validate_slot(conn, new_start)
    old = (appt.start_at, appt.end_at)
    appt.start_at, appt.end_at = local, local + timedelta(minutes=conn.slot_minutes)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("That slot is no longer available", code="slot_unavailable") from exc
    ext = calendar_for(conn)
    if ext and appt.external_event_id:
        try:
            ext.update_event(appt.external_event_id, appt.start_at, appt.end_at, conn.timezone)
        except CalendarError as exc:
            db.rollback()
            raise AppError(f"Calendar update failed: {exc}", code="calendar_error", status_code=502)
    emit(db, appt.tenant_id, "appointment.rescheduled", {"appointment_id": str(appt.id), "old_start": old[0].isoformat(), "start": local.isoformat()})
    db.commit()
    return appt


def reconcile_pending(db: Session, older_than_minutes: int = 5) -> dict:
    """Resolve 'pending_confirmation' left by a crash between external success and local commit."""
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    result = {"confirmed": 0, "failed": 0, "errors": 0}
    for appt in db.scalars(select(Appointment).where(Appointment.status == "pending_confirmation", Appointment.updated_at < cutoff)):
        conn = db.get(CalendarConnection, appt.calendar_connection_id)
        ext = calendar_for(conn) if conn else None
        try:
            if ext and ext.event_exists(event_id_for(appt.id)):
                appt.status, appt.external_event_id = "confirmed", event_id_for(appt.id)
                result["confirmed"] += 1
            else:
                appt.status, appt.failure_reason = "failed", "reconciliation: event not found"
                result["failed"] += 1
        except CalendarError:
            result["errors"] += 1
    db.commit()
    return result
