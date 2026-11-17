import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.audit.models import AuditLog, DataRetentionPolicy, DeletionRequest
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require
from app.contacts.models import Contact
from app.contacts.service import suppress
from app.db.session import get_db
from app.schemas.common import ORM, paginate
from app.telephony.models import Call, CallEvent

router = APIRouter(tags=["audit"])
RESOURCES = ("transcripts", "recordings", "call_events")


class AuditOut(ORM):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    details: dict
    created_at: datetime


class RetentionIn(BaseModel):
    resource: str = Field(pattern="^(transcripts|recordings|call_events)$")
    retain_days: int = Field(ge=7, le=3650)


class DeletionIn(BaseModel):
    contact_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=1000)


@router.get("/audit-logs")
def audit_logs(
    ctx: TenantContext = Depends(require("audit:read")),
    db: Session = Depends(get_db),
    action: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return paginate(db, stmt.order_by(AuditLog.created_at.desc()), limit, offset, AuditOut)


@router.get("/retention-policies")
def list_policies(ctx: TenantContext = Depends(require("audit:read")), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"resource": p.resource, "retain_days": p.retain_days}
        for p in db.scalars(select(DataRetentionPolicy).where(DataRetentionPolicy.tenant_id == ctx.tenant_id))
    ]


@router.put("/retention-policies")
def set_policy(body: RetentionIn, ctx: TenantContext = Depends(require("retention:write")), db: Session = Depends(get_db)) -> dict:
    p = db.scalar(select(DataRetentionPolicy).where(DataRetentionPolicy.tenant_id == ctx.tenant_id, DataRetentionPolicy.resource == body.resource))
    if p:
        p.retain_days = body.retain_days
    else:
        db.add(DataRetentionPolicy(tenant_id=ctx.tenant_id, resource=body.resource, retain_days=body.retain_days))
    audit_ctx(db, ctx, "retention.updated", "retention", body.resource, days=body.retain_days)
    db.commit()
    return body.model_dump()


def erase_contact(db: Session, tenant_id: uuid.UUID, contact: Contact) -> dict:
    """Right-to-erasure: remove PII, redact call content, keep a suppression entry so the person is never re-dialled."""
    phone = contact.phone_e164
    calls = db.execute(
        update(Call)
        .where(Call.tenant_id == tenant_id, Call.contact_id == contact.id)
        .values(transcript=None, transcript_segments=None, summary=None, recording_url=None, extracted={}, from_number=None, to_number=None, contact_id=None)
    ).rowcount  # type: ignore[attr-defined]
    suppress(db, tenant_id, phone, "opt_out", "erasure_request")
    db.delete(contact)  # cascades leads, activities, consents, campaign membership
    return {"calls_redacted": calls}


@router.post("/deletion-requests", status_code=201)
def request_deletion(body: DeletionIn, ctx: TenantContext = Depends(require("contacts:delete")), db: Session = Depends(get_db)) -> dict:
    contact = get_owned(db, Contact, body.contact_id, ctx)
    req = DeletionRequest(tenant_id=ctx.tenant_id, contact_id=contact.id, phone_e164=None, requested_by=ctx.user.id, reason=body.reason)
    db.add(req)
    summary = erase_contact(db, ctx.tenant_id, contact)
    req.status, req.completed_at, req.summary = "completed", datetime.now(UTC), summary
    audit_ctx(db, ctx, "contact.erased", "contact", body.contact_id, **summary)
    db.commit()
    return {"id": str(req.id), "status": req.status, **summary}


def apply_retention(db: Session) -> dict:
    """Purge data older than each tenant's policy (worker job)."""
    out = {"transcripts": 0, "recordings": 0, "call_events": 0}
    now = datetime.now(UTC)
    for p in db.scalars(select(DataRetentionPolicy)):
        cutoff = now - timedelta(days=p.retain_days)
        if p.resource == "transcripts":
            out["transcripts"] += db.execute(
                update(Call)
                .where(Call.tenant_id == p.tenant_id, Call.created_at < cutoff, Call.transcript.is_not(None))
                .values(transcript=None, transcript_segments=None, summary=None)
            ).rowcount  # type: ignore[attr-defined]
        elif p.resource == "recordings":
            out["recordings"] += db.execute(
                update(Call).where(Call.tenant_id == p.tenant_id, Call.created_at < cutoff, Call.recording_url.is_not(None)).values(recording_url=None)
            ).rowcount  # type: ignore[attr-defined]
        elif p.resource == "call_events":
            out["call_events"] += db.execute(delete(CallEvent).where(CallEvent.tenant_id == p.tenant_id, CallEvent.created_at < cutoff)).rowcount  # type: ignore[attr-defined]
    db.commit()
    return out
