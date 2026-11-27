import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.appointments.calendar import CalendarError, google_authorize_url, google_exchange_code
from app.appointments.models import CalendarConnection
from app.audit.service import audit, audit_ctx
from app.auth.deps import TenantContext, get_owned, require
from app.core.config import get_settings
from app.core.errors import AppError, ServiceUnavailable
from app.core.security import encrypt_secret
from app.db.session import get_db
from app.integrations.models import IntegrationConnection, OutboxEvent
from app.schemas.common import ORM, paginate

router = APIRouter(prefix="/integrations", tags=["integrations"])
EVENT_TYPES = [
    "call.started",
    "call.ended",
    "call.analyzed",
    "call.handoff_requested",
    "appointment.confirmed",
    "appointment.cancelled",
    "appointment.rescheduled",
    "contact.opted_out",
]


class ConnectionIn(BaseModel):
    kind: str = Field(pattern="^(webhook|n8n)$")
    name: str = Field(min_length=2, max_length=120)
    target_url: HttpUrl
    event_types: list[str] = Field(default_factory=list)


class ConnectionOut(ORM):
    id: uuid.UUID
    kind: str
    name: str
    target_url: str | None
    event_types: list
    status: str
    created_at: datetime


class OutboxOut(ORM):
    id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime


@router.get("/event-types")
def event_types(_: TenantContext = Depends(require("integrations:read"))) -> list[str]:
    return EVENT_TYPES


@router.get("", response_model=list[ConnectionOut])
def list_connections(ctx: TenantContext = Depends(require("integrations:read")), db: Session = Depends(get_db)):
    return db.scalars(select(IntegrationConnection).where(IntegrationConnection.tenant_id == ctx.tenant_id)).all()


@router.post("", status_code=201)
def create_connection(body: ConnectionIn, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)) -> dict:
    url = str(body.target_url)
    if get_settings().environment == "production" and not url.startswith("https://"):
        raise AppError("Webhook URLs must use HTTPS", code="insecure_url", status_code=422)
    bad = [e for e in body.event_types if e not in EVENT_TYPES]
    if bad:
        raise AppError(f"Unknown event types: {bad}", code="invalid_event_types", status_code=422)
    secret = "whsec_" + secrets.token_urlsafe(32)
    conn = IntegrationConnection(
        tenant_id=ctx.tenant_id, kind=body.kind, name=body.name, target_url=url, encrypted_secret=encrypt_secret(secret), event_types=body.event_types
    )
    db.add(conn)
    audit_ctx(db, ctx, "integration.created", "integration", None, kind=body.kind)
    db.commit()
    # The signing secret is shown exactly once.
    return {**ConnectionOut.model_validate(conn).model_dump(mode="json"), "signing_secret": secret}


@router.post("/{connection_id}/disable", response_model=ConnectionOut)
def disable(connection_id: uuid.UUID, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)):
    conn = get_owned(db, IntegrationConnection, connection_id, ctx)
    conn.status = "disabled"
    audit_ctx(db, ctx, "integration.disabled", "integration", conn.id)
    db.commit()
    return conn


@router.get("/deliveries")
def deliveries(
    ctx: TenantContext = Depends(require("integrations:read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(OutboxEvent).where(OutboxEvent.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(OutboxEvent.status == status)
    return paginate(db, stmt.order_by(OutboxEvent.created_at.desc()), limit, offset, OutboxOut)


# ---- Google Calendar OAuth --------------------------------------------------------------------------------------
@router.get("/google/authorize")
def google_authorize(ctx: TenantContext = Depends(require("integrations:write"))) -> dict:
    s = get_settings()
    if not s.google_configured:
        raise ServiceUnavailable("Google Calendar is not configured (GOOGLE_CLIENT_ID/SECRET)")
    state = jwt.encode(
        {"t": str(ctx.tenant_id), "u": str(ctx.user.id), "typ": "gcal_state", "exp": datetime.now(UTC) + timedelta(minutes=10)}, s.jwt_secret, algorithm="HS256"
    )
    return {"authorize_url": google_authorize_url(state)}


@router.get("/google/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    s = get_settings()
    try:
        data = jwt.decode(state, s.jwt_secret, algorithms=["HS256"])
        if data.get("typ") != "gcal_state":
            raise jwt.InvalidTokenError
    except jwt.InvalidTokenError:
        raise AppError("Invalid OAuth state", code="invalid_state", status_code=400)
    try:
        tokens = google_exchange_code(code)
    except CalendarError:
        return RedirectResponse(f"{s.frontend_url}/integrations?google=error")
    tenant_id = uuid.UUID(data["t"])
    conn = CalendarConnection(
        tenant_id=tenant_id,
        provider="google",
        label="Google Calendar",
        calendar_id="primary",
        encrypted_tokens=encrypt_secret(json.dumps({"access_token": tokens.get("access_token"), "refresh_token": tokens.get("refresh_token")})),
        token_expires_at=datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600))),
    )
    db.add(conn)
    audit(db, "calendar.google_connected", tenant_id=tenant_id, actor_user_id=uuid.UUID(data["u"]))
    db.commit()
    return RedirectResponse(f"{s.frontend_url}/integrations?google=connected")
