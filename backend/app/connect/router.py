import ipaddress
import json
import socket
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.appointments.models import CalendarConnection
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability, tenant_context
from app.connect.adapters import ConnectorError, ERPNextAdapter, ManimaHubAdapter
from app.connect.metrics import METRICS, run_metric
from app.connect.models import ConnectorConnection
from app.connect.registry import BY_KEY, CONNECTORS
from app.core.config import get_settings
from app.core.errors import AppError, Conflict
from app.core.security import encrypt_secret
from app.db.session import get_db
from app.integrations.models import IntegrationConnection
from app.platform.entitlements import has as has_capability

router = APIRouter(prefix="/connect", tags=["connect"])


class ConnectionIn(BaseModel):
    connector_key: str
    name: str = Field(min_length=2, max_length=120)
    base_url: str = Field(min_length=8, max_length=500)
    credentials: dict[str, str]


class MetricRunIn(BaseModel):
    metric_key: str
    params: dict = Field(default_factory=dict)


def _out(c: ConnectorConnection) -> dict:
    return {
        "id": str(c.id),
        "connector_key": c.connector_key,
        "name": c.name,
        "base_url": c.base_url,
        "status": c.status,
        "read_only": c.read_only,
        "scopes": c.scopes,
        "last_verified_at": c.last_verified_at.isoformat() if c.last_verified_at else None,
        "last_error": c.last_error,
        "verified_identity": c.verified_identity,
        "created_at": c.created_at.isoformat(),
    }


def validate_base_url(url: str) -> str:
    """Block SSRF: require http(s); in production require HTTPS and a public address."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise AppError("base_url must be an http(s) URL", code="invalid_url", status_code=422)
    if get_settings().environment == "production":
        if p.scheme != "https":
            raise AppError("base_url must use HTTPS", code="invalid_url", status_code=422)
        try:
            addrs = {ai[4][0] for ai in socket.getaddrinfo(p.hostname, p.port or 443)}
        except socket.gaierror:
            raise AppError("base_url host cannot be resolved", code="invalid_url", status_code=422)
        for a in addrs:
            ip = ipaddress.ip_address(a)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise AppError("base_url must resolve to a public address", code="invalid_url", status_code=422)
    return url.rstrip("/")


def _verify(conn: ConnectorConnection) -> None:
    try:
        adapter = ERPNextAdapter(conn) if conn.connector_key == "erpnext" else ManimaHubAdapter(conn)
        conn.verified_identity = adapter.verify()[:200]
        conn.status, conn.last_error, conn.last_verified_at = "connected", None, datetime.now(UTC)
    except ConnectorError as exc:
        conn.status, conn.last_error = "failed", str(exc)[:500]


@router.get("/connectors")
def connectors(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    conns = db.scalars(select(ConnectorConnection).where(ConnectorConnection.tenant_id == ctx.tenant_id)).all()
    gcal = db.scalar(
        select(CalendarConnection.id).where(
            CalendarConnection.tenant_id == ctx.tenant_id, CalendarConnection.provider == "google", CalendarConnection.status == "active"
        )
    )
    n8n = db.scalar(
        select(IntegrationConnection.id).where(
            IntegrationConnection.tenant_id == ctx.tenant_id, IntegrationConnection.kind == "n8n", IntegrationConnection.status == "active"
        )
    )
    out = []
    for spec in CONNECTORS:
        mine = [c for c in conns if c.connector_key == spec.key]
        if spec.key == "google_calendar":
            status = "connected" if gcal else "not_connected"
        elif spec.key == "n8n":
            status = "configured" if n8n else "not_connected"
        elif spec.adapter == "planned":
            status = "not_available"
        else:
            status = "connected" if any(c.status == "connected" for c in mine) else ("failed" if any(c.status == "failed" for c in mine) else "not_connected")
        out.append(
            {
                "key": spec.key,
                "name": spec.name,
                "category": spec.category,
                "auth": spec.auth,
                "adapter": spec.adapter,
                "description": spec.description,
                "credential_fields": list(spec.credential_fields),
                "status": status,
                "read_scopes": list(spec.read_scopes),
                "write_scopes": list(spec.write_scopes),
                "connections": len(mine),
            }
        )
    return out


@router.get("/connections")
def list_connections(ctx: TenantContext = Depends(require("integrations:read")), db: Session = Depends(get_db)) -> list[dict]:
    return [
        _out(c) for c in db.scalars(select(ConnectorConnection).where(ConnectorConnection.tenant_id == ctx.tenant_id).order_by(ConnectorConnection.created_at))
    ]


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionIn, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)) -> dict:
    spec = BY_KEY.get(body.connector_key)
    if spec is None:
        raise AppError("Unknown connector", code="unknown_connector", status_code=422)
    if spec.adapter != "implemented" or spec.key not in ("erpnext", "manima_hub"):
        raise AppError(f"{spec.name} cannot be connected here yet", code="connector_not_available", status_code=409)
    missing = [f for f in spec.credential_fields if f != "base_url" and not body.credentials.get(f)]
    if missing:
        raise AppError(f"Missing credentials: {', '.join(missing)}", code="missing_credentials", status_code=422)
    creds = {f: body.credentials[f] for f in spec.credential_fields if f != "base_url"}
    conn = ConnectorConnection(
        tenant_id=ctx.tenant_id,
        connector_key=spec.key,
        name=body.name,
        base_url=validate_base_url(body.base_url),
        encrypted_credentials=encrypt_secret(json.dumps(creds)),
        scopes=list(spec.read_scopes),
        read_only=True,
        status="pending",
        created_by=ctx.user.id,
    )
    db.add(conn)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A connection with this name already exists")
    _verify(conn)
    audit_ctx(db, ctx, "connect.connection_created", "connector_connection", conn.id, connector=spec.key, status=conn.status)
    db.commit()
    return _out(conn)


@router.post("/connections/{connection_id}/verify")
def verify(connection_id: uuid.UUID, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)) -> dict:
    conn = get_owned(db, ConnectorConnection, connection_id, ctx)
    if conn.status == "revoked":
        raise AppError("Connection is revoked", code="invalid_state", status_code=409)
    _verify(conn)
    audit_ctx(db, ctx, "connect.connection_verified", "connector_connection", conn.id, status=conn.status)
    db.commit()
    return _out(conn)


@router.post("/connections/{connection_id}/revoke")
def revoke(connection_id: uuid.UUID, ctx: TenantContext = Depends(require("integrations:write")), db: Session = Depends(get_db)) -> dict:
    conn = get_owned(db, ConnectorConnection, connection_id, ctx)
    conn.status, conn.encrypted_credentials = "revoked", None
    audit_ctx(db, ctx, "connect.connection_revoked", "connector_connection", conn.id)
    db.commit()
    return _out(conn)


@router.get("/metrics")
def metrics(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    connected = set(
        db.scalars(select(ConnectorConnection.connector_key).where(ConnectorConnection.tenant_id == ctx.tenant_id, ConnectorConnection.status == "connected"))
    )
    calling = has_capability(db, ctx.tenant_id, "product.calling_agent")
    return [
        {
            "key": m.key,
            "title": m.title,
            "source": m.source,
            "description": m.description,
            "params": list(m.params),
            "available": (calling if m.source == "kokila" else m.source in connected),
        }
        for m in METRICS
    ]


@router.post("/metrics/run", dependencies=[Depends(require_capability("product.business_assistant", "connect.analytics"))])
def run(body: MetricRunIn, ctx: TenantContext = Depends(require("analytics:read")), db: Session = Depends(get_db)) -> dict:
    result = run_metric(db, ctx.tenant_id, body.metric_key, body.params)
    audit_ctx(db, ctx, "connect.metric_run", "metric", body.metric_key)
    db.commit()
    return result
