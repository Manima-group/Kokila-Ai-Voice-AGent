import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.appointments.models import Appointment, CalendarConnection
from app.appointments.service import available_slots, book, cancel, reschedule, zone
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability
from app.contacts.models import Contact
from app.core.errors import AppError
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.schemas.common import ORM, paginate

router = APIRouter(tags=["appointments"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT))])


class ConnectionIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    timezone: str = "Asia/Kolkata"
    slot_minutes: int = Field(default=30, ge=10, le=240)
    business_hours: dict = Field(default_factory=lambda: {"start": "10:00", "end": "18:00", "days": [0, 1, 2, 3, 4, 5]})


class ConnectionOut(ORM):
    id: uuid.UUID
    provider: str
    label: str
    calendar_id: str
    status: str
    slot_minutes: int
    business_hours: dict
    timezone: str


class BookIn(BaseModel):
    start: datetime
    title: str = Field(min_length=2, max_length=200)
    contact_id: uuid.UUID | None = None
    calendar_connection_id: uuid.UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=120)
    notes: str | None = None


class RescheduleIn(BaseModel):
    start: datetime


class AppointmentOut(ORM):
    id: uuid.UUID
    calendar_connection_id: uuid.UUID
    contact_id: uuid.UUID | None
    call_id: uuid.UUID | None
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    status: str
    external_event_id: str | None
    failure_reason: str | None
    created_at: datetime


@router.get("/calendar-connections", response_model=list[ConnectionOut])
def list_connections(ctx: TenantContext = Depends(require("appointments:read")), db: Session = Depends(get_db)):
    return db.scalars(select(CalendarConnection).where(CalendarConnection.tenant_id == ctx.tenant_id)).all()


@router.post("/calendar-connections", response_model=ConnectionOut, status_code=201)
def create_internal(body: ConnectionIn, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)):
    """Kokila-managed calendar (DB authoritative). Google calendars are connected via OAuth (/integrations/google)."""
    zone(body.timezone)
    conn = CalendarConnection(
        tenant_id=ctx.tenant_id,
        provider="internal",
        label=body.label,
        calendar_id="kokila",
        timezone=body.timezone,
        slot_minutes=body.slot_minutes,
        business_hours=body.business_hours,
    )
    db.add(conn)
    audit_ctx(db, ctx, "calendar.created", "calendar_connection", None)
    db.commit()
    return conn


@router.get("/appointments")
def list_appointments(
    ctx: TenantContext = Depends(require("appointments:read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    start_from: datetime | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Appointment).where(Appointment.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if start_from:
        stmt = stmt.where(Appointment.start_at >= start_from)
    return paginate(db, stmt.order_by(Appointment.start_at), limit, offset, AppointmentOut)


@router.get("/appointments/availability")
def availability(
    day: date, calendar_connection_id: uuid.UUID | None = None, ctx: TenantContext = Depends(require("appointments:read")), db: Session = Depends(get_db)
) -> dict:
    from app.appointments.service import default_connection

    conn = get_owned(db, CalendarConnection, calendar_connection_id, ctx) if calendar_connection_id else default_connection(db, ctx.tenant_id)
    return {"timezone": conn.timezone, "slots": [s.isoformat() for s in available_slots(db, conn, day)]}


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(body: BookIn, ctx: TenantContext = Depends(require("appointments:write")), db: Session = Depends(get_db)):
    conn = get_owned(db, CalendarConnection, body.calendar_connection_id, ctx) if body.calendar_connection_id else None
    if body.contact_id:
        get_owned(db, Contact, body.contact_id, ctx)
    appt = book(
        db,
        ctx.tenant_id,
        start=body.start,
        title=body.title,
        idempotency_key=body.idempotency_key,
        contact_id=body.contact_id,
        connection=conn,
        notes=body.notes,
    )
    audit_ctx(db, ctx, "appointment.booked", "appointment", appt.id, status=appt.status)
    db.commit()
    return appt


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(appointment_id: uuid.UUID, ctx: TenantContext = Depends(require("appointments:write")), db: Session = Depends(get_db)):
    appt = get_owned(db, Appointment, appointment_id, ctx)
    audit_ctx(db, ctx, "appointment.cancelled", "appointment", appt.id)
    return cancel(db, appt)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(
    appointment_id: uuid.UUID, body: RescheduleIn, ctx: TenantContext = Depends(require("appointments:write")), db: Session = Depends(get_db)
):
    appt = get_owned(db, Appointment, appointment_id, ctx)
    if body.start.tzinfo is None:
        raise AppError("start must include timezone", code="naive_datetime", status_code=422)
    audit_ctx(db, ctx, "appointment.rescheduled", "appointment", appt.id)
    return reschedule(db, appt, body.start)
