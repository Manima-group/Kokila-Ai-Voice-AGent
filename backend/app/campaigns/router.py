import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability
from app.campaigns.models import CallAttempt, Campaign, CampaignContact
from app.campaigns.service import campaign_stats, dispatch_campaign, evaluate_contacts, start_campaign
from app.contacts.models import Contact
from app.core.errors import AppError
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.schemas.common import ORM, paginate
from app.telephony.models import PhoneNumber

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT, "voice.outbound"))])
HM = r"^([01]\d|2[0-3]):[0-5]\d$"


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    purpose: str = Field(min_length=2, max_length=60)
    agent_id: uuid.UUID
    from_phone_number_id: uuid.UUID
    window_start: str = Field(default="10:00", pattern=HM)
    window_end: str = Field(default="19:00", pattern=HM)
    timezone: str = "Asia/Kolkata"
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    max_concurrency: int = Field(default=2, ge=1, le=100)
    max_attempts: int = Field(default=2, ge=1, le=5)
    retry_delay_minutes: int = Field(default=120, ge=15, le=10080)
    start_at: datetime | None = None
    end_at: datetime | None = None
    description: str | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone")
        return v

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if not v or any(d not in range(7) for d in v):
            raise ValueError("days_of_week must contain 0-6")
        return sorted(set(v))

    @model_validator(mode="after")
    def _window(self) -> "CampaignIn":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class CampaignOut(ORM):
    id: uuid.UUID
    name: str
    purpose: str
    agent_id: uuid.UUID
    from_phone_number_id: uuid.UUID
    status: str
    window_start: str
    window_end: str
    timezone: str
    days_of_week: list
    max_concurrency: int
    max_attempts: int
    retry_delay_minutes: int
    start_at: datetime | None
    end_at: datetime | None
    created_at: datetime


class AddContactsIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20000)
    tag: str | None = None


class AttemptOut(ORM):
    id: uuid.UUID
    campaign_contact_id: uuid.UUID
    attempt_no: int
    status: str
    outcome: str | None
    error: str | None
    call_id: uuid.UUID | None
    dispatched_at: datetime | None
    created_at: datetime


def _owned_campaign(db: Session, cid: uuid.UUID, ctx: TenantContext) -> Campaign:
    return get_owned(db, Campaign, cid, ctx)


@router.get("", response_model=list[CampaignOut])
def list_campaigns(ctx: TenantContext = Depends(require("campaigns:read")), db: Session = Depends(get_db)):
    return db.scalars(select(Campaign).where(Campaign.tenant_id == ctx.tenant_id).order_by(Campaign.created_at.desc())).all()


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(body: CampaignIn, ctx: TenantContext = Depends(require("campaigns:write")), db: Session = Depends(get_db)):
    get_owned(db, Agent, body.agent_id, ctx)
    get_owned(db, PhoneNumber, body.from_phone_number_id, ctx)
    c = Campaign(tenant_id=ctx.tenant_id, status="draft", **body.model_dump())
    db.add(c)
    audit_ctx(db, ctx, "campaign.created", "campaign", None, name=body.name)
    db.commit()
    return c


@router.get("/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:read")), db: Session = Depends(get_db)) -> dict:
    c = _owned_campaign(db, campaign_id, ctx)
    return {**CampaignOut.model_validate(c).model_dump(mode="json"), "stats": campaign_stats(db, c.id)}


@router.post("/{campaign_id}/contacts")
def add_contacts(campaign_id: uuid.UUID, body: AddContactsIn, ctx: TenantContext = Depends(require("campaigns:write")), db: Session = Depends(get_db)) -> dict:
    c = _owned_campaign(db, campaign_id, ctx)
    if c.status in ("completed", "cancelled"):
        raise AppError("Campaign is closed", code="invalid_state", status_code=409)
    stmt = select(Contact.id).where(Contact.tenant_id == ctx.tenant_id)
    if body.contact_ids:
        stmt = stmt.where(Contact.id.in_(body.contact_ids))
    elif body.tag:
        stmt = stmt.where(Contact.tags.contains([body.tag]))
    else:
        raise AppError("Provide contact_ids or tag", code="invalid_request", status_code=422)
    ids = db.scalars(stmt).all()  # only this tenant's contacts can be added
    added = 0
    for cid in ids:
        res = db.execute(
            insert(CampaignContact)
            .values(id=uuid.uuid4(), tenant_id=ctx.tenant_id, campaign_id=c.id, contact_id=cid, status="pending", attempts=0)
            .on_conflict_do_nothing(index_elements=["campaign_id", "contact_id"])
        )
        added += res.rowcount or 0  # type: ignore[attr-defined]
    counts = evaluate_contacts(db, c)
    db.commit()
    return {"added": added, "ignored": len(body.contact_ids) - len(ids) if body.contact_ids else 0, **counts}


@router.get("/{campaign_id}/contacts")
def campaign_contacts(
    campaign_id: uuid.UUID,
    ctx: TenantContext = Depends(require("campaigns:read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> dict:
    _owned_campaign(db, campaign_id, ctx)
    stmt = select(CampaignContact, Contact).join(Contact, Contact.id == CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(CampaignContact.status == status)
    rows = db.execute(stmt.order_by(CampaignContact.created_at).limit(min(limit, 200)).offset(offset)).all()
    return {
        "items": [
            {
                "id": str(cc.id),
                "contact_id": str(ct.id),
                "name": ct.name,
                "phone": ct.phone_e164,
                "status": cc.status,
                "ineligible_reason": cc.ineligible_reason,
                "attempts": cc.attempts,
                "last_outcome": cc.last_outcome,
                "next_attempt_at": cc.next_attempt_at.isoformat() if cc.next_attempt_at else None,
            }
            for cc, ct in rows
        ]
    }


@router.get("/{campaign_id}/attempts")
def attempts(
    campaign_id: uuid.UUID,
    ctx: TenantContext = Depends(require("campaigns:read")),
    db: Session = Depends(get_db),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    _owned_campaign(db, campaign_id, ctx)
    return paginate(db, select(CallAttempt).where(CallAttempt.campaign_id == campaign_id).order_by(CallAttempt.created_at.desc()), limit, offset, AttemptOut)


@router.post("/{campaign_id}/start", response_model=CampaignOut)
def start(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)):
    c = _owned_campaign(db, campaign_id, ctx)
    if c.status not in ("draft", "scheduled"):
        raise AppError(f"Cannot start a {c.status} campaign", code="invalid_state", status_code=409)
    counts = start_campaign(db, c)
    audit_ctx(db, ctx, "campaign.started", "campaign", c.id, **counts)
    db.commit()
    return c


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
def pause(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)):
    c = _owned_campaign(db, campaign_id, ctx)
    if c.status != "running":
        raise AppError("Only running campaigns can be paused", code="invalid_state", status_code=409)
    c.status = "paused"
    audit_ctx(db, ctx, "campaign.paused", "campaign", c.id)
    db.commit()
    return c


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
def resume(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)):
    c = _owned_campaign(db, campaign_id, ctx)
    if c.status != "paused":
        raise AppError("Only paused campaigns can be resumed", code="invalid_state", status_code=409)
    c.status = "running"
    evaluate_contacts(db, c)
    audit_ctx(db, ctx, "campaign.resumed", "campaign", c.id)
    db.commit()
    return c


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
def cancel(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)):
    c = _owned_campaign(db, campaign_id, ctx)
    if c.status in ("completed", "cancelled"):
        raise AppError("Campaign already closed", code="invalid_state", status_code=409)
    c.status = "cancelled"
    for cc in db.scalars(select(CampaignContact).where(CampaignContact.campaign_id == c.id, CampaignContact.status.in_(("pending", "eligible")))):
        cc.status = "cancelled"
    audit_ctx(db, ctx, "campaign.cancelled", "campaign", c.id)
    db.commit()
    return c


@router.post("/{campaign_id}/dispatch-now")
def dispatch_now(campaign_id: uuid.UUID, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)) -> dict:
    """Run one dispatch tick immediately (same gates as the scheduler)."""
    c = _owned_campaign(db, campaign_id, ctx)
    return dispatch_campaign(db, c)
