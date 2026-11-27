import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability
from app.contacts.models import Contact, Lead, LeadActivity
from app.core.errors import AppError, Forbidden
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.schemas.common import ORM, paginate
from app.tenants.models import TenantMembership

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT))])
STATUSES = ("new", "contacted", "qualified", "unqualified", "converted", "lost")


class LeadIn(BaseModel):
    contact_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=5000)


class LeadPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(" + "|".join(STATUSES) + ")$")
    notes: str | None = Field(default=None, max_length=5000)
    next_follow_up_at: datetime | None = None
    score: int | None = Field(default=None, ge=0, le=100)


class AssignIn(BaseModel):
    user_id: uuid.UUID | None


class ActivityIn(BaseModel):
    kind: str = Field(pattern="^(note|task)$")
    body: str = Field(min_length=1, max_length=5000)
    due_at: datetime | None = None


class LeadOut(ORM):
    id: uuid.UUID
    contact_id: uuid.UUID
    status: str
    score: int
    source: str
    assigned_to: uuid.UUID | None
    last_outcome: str | None
    notes: str | None
    next_follow_up_at: datetime | None
    qualification: dict
    created_at: datetime
    updated_at: datetime


class ActivityOut(ORM):
    id: uuid.UUID
    kind: str
    body: str | None
    user_id: uuid.UUID | None
    call_id: uuid.UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


def _check_write(ctx: TenantContext, lead: Lead) -> None:
    if ctx.can("leads:write"):
        return
    if ctx.can("leads:write_assigned") and lead.assigned_to == ctx.user.id:
        return
    raise Forbidden("You can only update leads assigned to you")


@router.get("")
def list_leads(
    ctx: TenantContext = Depends(require("leads:read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    assigned_to_me: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Lead).where(Lead.tenant_id == ctx.tenant_id)
    if ctx.role == "OPERATOR" or assigned_to_me:  # operators see only their assigned leads
        stmt = stmt.where(Lead.assigned_to == ctx.user.id)
    if status:
        stmt = stmt.where(Lead.status == status)
    page = paginate(db, stmt.order_by(Lead.updated_at.desc()), limit, offset, LeadOut)
    ids = [i.contact_id for i in page.items]
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_(ids)))} if ids else {}
    page.items = [
        {
            **i.model_dump(mode="json"),
            "contact_name": contacts[i.contact_id].name if i.contact_id in contacts else None,
            "contact_phone": contacts[i.contact_id].phone_e164 if i.contact_id in contacts else None,
        }
        for i in page.items
    ]
    return page


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(body: LeadIn, ctx: TenantContext = Depends(require("leads:write")), db: Session = Depends(get_db)):
    get_owned(db, Contact, body.contact_id, ctx)
    lead = Lead(tenant_id=ctx.tenant_id, contact_id=body.contact_id, notes=body.notes, source="manual", qualification={})
    db.add(lead)
    db.commit()
    return lead


@router.get("/{lead_id}")
def get_lead(lead_id: uuid.UUID, ctx: TenantContext = Depends(require("leads:read")), db: Session = Depends(get_db)) -> dict:
    lead = get_owned(db, Lead, lead_id, ctx)
    if ctx.role == "OPERATOR" and lead.assigned_to != ctx.user.id:
        raise Forbidden("Lead not assigned to you")
    acts = db.scalars(select(LeadActivity).where(LeadActivity.lead_id == lead.id).order_by(LeadActivity.created_at.desc())).all()
    return {**LeadOut.model_validate(lead).model_dump(mode="json"), "activities": [ActivityOut.model_validate(a).model_dump(mode="json") for a in acts]}


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: uuid.UUID, body: LeadPatch, ctx: TenantContext = Depends(require("leads:read")), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lead_id, ctx)
    _check_write(ctx, lead)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != lead.status:
        db.add(LeadActivity(tenant_id=ctx.tenant_id, lead_id=lead.id, kind="status_change", body=f"{lead.status} -> {data['status']}", user_id=ctx.user.id))
    for k, v in data.items():
        setattr(lead, k, v)
    db.commit()
    return lead


@router.post("/{lead_id}/assign", response_model=LeadOut)
def assign(lead_id: uuid.UUID, body: AssignIn, ctx: TenantContext = Depends(require("leads:assign")), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lead_id, ctx)
    if body.user_id:
        member = db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == body.user_id, TenantMembership.is_active.is_(True)
            )
        )
        if not member:
            raise AppError("User is not a member of this organization", code="invalid_assignee", status_code=422)
    lead.assigned_to = body.user_id
    db.add(LeadActivity(tenant_id=ctx.tenant_id, lead_id=lead.id, kind="assignment", body=f"Assigned to {body.user_id}", user_id=ctx.user.id))
    audit_ctx(db, ctx, "lead.assigned", "lead", lead.id, assignee=str(body.user_id))
    db.commit()
    return lead


@router.post("/{lead_id}/activities", response_model=ActivityOut, status_code=201)
def add_activity(lead_id: uuid.UUID, body: ActivityIn, ctx: TenantContext = Depends(require("leads:read")), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lead_id, ctx)
    _check_write(ctx, lead)
    act = LeadActivity(tenant_id=ctx.tenant_id, lead_id=lead.id, kind=body.kind, body=body.body, user_id=ctx.user.id, due_at=body.due_at)
    db.add(act)
    if body.kind == "task" and body.due_at and (not lead.next_follow_up_at or body.due_at < lead.next_follow_up_at):
        lead.next_follow_up_at = body.due_at
    db.commit()
    return act


@router.post("/{lead_id}/activities/{activity_id}/complete", response_model=ActivityOut)
def complete_task(lead_id: uuid.UUID, activity_id: uuid.UUID, ctx: TenantContext = Depends(require("leads:read")), db: Session = Depends(get_db)):
    lead = get_owned(db, Lead, lead_id, ctx)
    _check_write(ctx, lead)
    act = get_owned(db, LeadActivity, activity_id, ctx)
    if act.lead_id != lead.id or act.kind != "task":
        raise AppError("Not a task of this lead", code="invalid_task", status_code=422)
    act.completed_at = datetime.now(UTC)
    db.commit()
    return act


@router.get("/tasks/open")
def open_tasks(ctx: TenantContext = Depends(require("leads:read")), db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(LeadActivity, Lead)
        .join(Lead, Lead.id == LeadActivity.lead_id)
        .where(LeadActivity.tenant_id == ctx.tenant_id, LeadActivity.kind == "task", LeadActivity.completed_at.is_(None))
    )
    if ctx.role == "OPERATOR":
        stmt = stmt.where(Lead.assigned_to == ctx.user.id)
    return [
        {"id": str(a.id), "lead_id": str(lead.id), "body": a.body, "due_at": a.due_at.isoformat() if a.due_at else None}
        for a, lead in db.execute(stmt.order_by(LeadActivity.due_at.nulls_last()).limit(200)).all()
    ]
