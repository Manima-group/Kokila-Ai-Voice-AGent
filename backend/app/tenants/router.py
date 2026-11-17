import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require
from app.auth.rbac import Role
from app.billing.service import require_active
from app.core.errors import AppError, Conflict, PaymentRequired
from app.core.security import hash_password
from app.db.session import get_db
from app.tenants.models import TenantMembership, User

router = APIRouter(tags=["organization"])
ROLE_PATTERN = "^(COMPANY_ADMIN|MANAGER|OPERATOR|VIEWER)$"


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = None
    industry: str | None = None


class ComplianceIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    dlt_entity_id: str | None = Field(default=None, max_length=60)
    telemarketer_registration: str | None = Field(default=None, max_length=120)
    gstin: str | None = Field(default=None, max_length=20)
    attests_consent_collection: bool
    attests_recording_disclosure: bool


class InviteIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    role: str = Field(pattern=ROLE_PATTERN)


class RoleIn(BaseModel):
    role: str = Field(pattern=ROLE_PATTERN)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


@router.get("/tenants/current")
def current(ctx: TenantContext = Depends(require("agents:read"))) -> dict:
    t = ctx.tenant
    return {
        "id": str(t.id),
        "name": t.name,
        "slug": t.slug,
        "status": t.status,
        "timezone": t.timezone,
        "industry": t.industry,
        "outbound_paused": t.outbound_paused,
        "compliance": t.compliance or {},
        "role": ctx.role,
    }


@router.patch("/tenants/current")
def update_current(body: TenantPatch, ctx: TenantContext = Depends(require("tenant:write")), db: Session = Depends(get_db)) -> dict:
    t = db.merge(ctx.tenant)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "timezone":
            from app.appointments.service import zone

            zone(v)
        setattr(t, k, v)
    audit_ctx(db, ctx, "tenant.updated", "tenant", t.id)
    db.commit()
    return {"status": "updated"}


@router.put("/tenants/current/compliance")
def set_compliance(body: ComplianceIn, ctx: TenantContext = Depends(require("tenant:write")), db: Session = Depends(get_db)) -> dict:
    """Tenant submits its compliance profile. Outbound approval is granted only by a Super Admin review."""
    if not (body.attests_consent_collection and body.attests_recording_disclosure):
        raise AppError("Both attestations are required", code="attestation_required", status_code=422)
    t = db.merge(ctx.tenant)
    t.compliance = {**body.model_dump(), "submitted_by": str(ctx.user.id), "outbound_approved": False, "status": "pending_review"}
    audit_ctx(db, ctx, "tenant.compliance_submitted", "tenant", t.id)
    db.commit()
    return t.compliance


@router.post("/tenants/current/outbound-pause")
def pause_outbound(paused: bool, ctx: TenantContext = Depends(require("campaigns:control")), db: Session = Depends(get_db)) -> dict:
    """Tenant-level emergency stop for all outbound dialing."""
    t = db.merge(ctx.tenant)
    t.outbound_paused = paused
    audit_ctx(db, ctx, "tenant.outbound_paused" if paused else "tenant.outbound_resumed", "tenant", t.id)
    db.commit()
    return {"outbound_paused": paused}


@router.get("/users", response_model=list[MemberOut])
def members(ctx: TenantContext = Depends(require("users:read")), db: Session = Depends(get_db)):
    rows = db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == ctx.tenant_id)
        .order_by(TenantMembership.created_at)
    ).all()
    return [MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, is_active=m.is_active, created_at=m.created_at) for m, u in rows]


@router.post("/users", status_code=201)
def invite(body: InviteIn, ctx: TenantContext = Depends(require("users:write")), db: Session = Depends(get_db)) -> dict:
    ent = require_active(db, ctx.tenant_id)
    n = db.scalar(select(func.count()).select_from(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.is_active.is_(True)))
    if (n or 0) >= ent.plan.max_users:  # type: ignore[attr-defined]
        raise PaymentRequired("User limit reached for your plan", code="user_limit")
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    temp_password = None
    if user is None:
        temp_password = secrets.token_urlsafe(12) + "9a"
        user = User(email=email, full_name=body.full_name, password_hash=hash_password(temp_password))
        db.add(user)
        db.flush()
    elif db.scalar(select(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user.id)):
        raise Conflict("User is already a member")
    db.add(TenantMembership(tenant_id=ctx.tenant_id, user_id=user.id, role=Role(body.role).value))
    audit_ctx(db, ctx, "user.invited", "user", user.id, role=body.role)
    db.commit()
    # Temporary password is returned once for the admin to share securely (email delivery when SMTP is configured).
    return {"user_id": str(user.id), "temporary_password": temp_password}


@router.patch("/users/{user_id}/role")
def change_role(user_id: uuid.UUID, body: RoleIn, ctx: TenantContext = Depends(require("users:write")), db: Session = Depends(get_db)) -> dict:
    m = db.scalar(select(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user_id))
    if m is None:
        raise AppError("Member not found", code="not_found", status_code=404)
    if user_id == ctx.user.id and body.role != "COMPANY_ADMIN":
        raise AppError("You cannot demote yourself", code="self_demotion", status_code=409)
    m.role = body.role
    audit_ctx(db, ctx, "user.role_changed", "user", user_id, role=body.role)
    db.commit()
    return {"status": "updated"}


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, ctx: TenantContext = Depends(require("users:write")), db: Session = Depends(get_db)) -> dict:
    if user_id == ctx.user.id:
        raise AppError("You cannot deactivate yourself", code="self_deactivation", status_code=409)
    m = db.scalar(select(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user_id))
    if m is None:
        raise AppError("Member not found", code="not_found", status_code=404)
    m.is_active = False
    audit_ctx(db, ctx, "user.deactivated", "user", user_id)
    db.commit()
    return {"status": "deactivated"}


_ = get_owned  # re-exported helper used by other modules
