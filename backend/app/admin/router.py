"""Super Admin (platform) operations. Every action is audited."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.auth.deps import Principal, require_superadmin
from app.billing.models import Plan, Subscription
from app.core.errors import AppError, NotFound
from app.core.ratelimit import get_redis
from app.db.session import get_db
from app.integrations.models import BackgroundJobFailure, OutboxEvent, WebhookEvent
from app.telephony.models import Call
from app.tenants.models import PlatformSetting, Tenant, TenantMembership

router = APIRouter(prefix="/admin", tags=["admin"])


class PlanIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    name: str = Field(min_length=2, max_length=100)
    price_minor: int = Field(ge=0)
    interval_months: int = Field(default=1, ge=1, le=12)
    included_minutes: int = Field(ge=0)
    overage_per_minute_minor: int | None = Field(default=None, ge=0)
    max_agents: int = Field(ge=1)
    max_concurrent_calls: int = Field(ge=1)
    max_users: int = Field(ge=1)
    features: dict = Field(default_factory=dict)
    is_public: bool = True
    is_active: bool = True


class TenantStatusIn(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")
    reason: str = Field(min_length=3, max_length=500)


class ComplianceDecisionIn(BaseModel):
    approved: bool
    note: str = Field(min_length=3, max_length=1000)


class KillSwitchIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


class AssignPlanIn(BaseModel):
    plan_code: str
    days: int = Field(default=30, ge=1, le=366)
    reason: str = Field(min_length=3, max_length=500)


def _a(db: Session, p: Principal, action: str, **kw) -> None:
    audit(db, action, actor_user_id=p.user.id, actor_type="superadmin", ip=p.ip, **kw)


@router.get("/tenants")
def tenants(
    p: Principal = Depends(require_superadmin), db: Session = Depends(get_db), q: str | None = None, limit: int = Query(50, le=200), offset: int = 0
) -> dict:
    stmt = select(Tenant)
    if q:
        stmt = stmt.where(Tenant.name.ilike(f"%{q[:100]}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)).all()
    ids = [t.id for t in rows]
    users = (
        dict(db.execute(select(TenantMembership.tenant_id, func.count()).where(TenantMembership.tenant_id.in_(ids)).group_by(TenantMembership.tenant_id)).all())
        if ids
        else {}
    )
    calls = (
        dict(
            db.execute(
                select(Call.tenant_id, func.count())
                .where(Call.tenant_id.in_(ids), Call.created_at >= datetime.now(UTC) - timedelta(days=30))
                .group_by(Call.tenant_id)
            ).all()
        )
        if ids
        else {}
    )
    subs = {s.tenant_id: s for s in db.scalars(select(Subscription).where(Subscription.tenant_id.in_(ids), Subscription.is_current.is_(True)))} if ids else {}
    plans = {pl.id: pl.code for pl in db.scalars(select(Plan))}
    return {
        "total": total,
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "slug": t.slug,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
                "users": users.get(t.id, 0),
                "calls_30d": calls.get(t.id, 0),
                "outbound_paused": t.outbound_paused,
                "plan": plans.get(subs[t.id].plan_id) if t.id in subs else None,
                "subscription_status": subs[t.id].status if t.id in subs else None,
                "compliance_status": (t.compliance or {}).get("status", "not_submitted"),
            }
            for t in rows
        ],
    }


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: uuid.UUID, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise NotFound("Tenant not found")
    _a(db, p, "admin.tenant_viewed", tenant_id=t.id)
    db.commit()
    return {
        "id": str(t.id),
        "name": t.name,
        "status": t.status,
        "compliance": t.compliance,
        "outbound_paused": t.outbound_paused,
        "industry": t.industry,
        "created_at": t.created_at.isoformat(),
    }


@router.post("/tenants/{tenant_id}/status")
def set_status(tenant_id: uuid.UUID, body: TenantStatusIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise NotFound("Tenant not found")
    t.status = body.status
    _a(db, p, f"admin.tenant_{body.status}", tenant_id=t.id, details={"reason": body.reason})
    db.commit()
    return {"status": t.status}


@router.post("/tenants/{tenant_id}/compliance-decision")
def compliance_decision(tenant_id: uuid.UUID, body: ComplianceDecisionIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, tenant_id)
    if not t:
        raise NotFound("Tenant not found")
    if not (t.compliance or {}).get("legal_name"):
        raise AppError("Tenant has not submitted a compliance profile", code="not_submitted", status_code=409)
    t.compliance = {
        **t.compliance,
        "outbound_approved": body.approved,
        "status": "approved" if body.approved else "rejected",
        "reviewed_by": str(p.user.id),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "review_note": body.note,
    }
    _a(db, p, "admin.compliance_decision", tenant_id=t.id, details={"approved": body.approved})
    db.commit()
    return t.compliance


@router.post("/tenants/{tenant_id}/plan")
def assign_plan(tenant_id: uuid.UUID, body: AssignPlanIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    """Audited support operation: grant a plan (e.g. enterprise contract billed offline)."""
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    if not plan or not db.get(Tenant, tenant_id):
        raise NotFound("Tenant or plan not found")
    for s in db.scalars(select(Subscription).where(Subscription.tenant_id == tenant_id, Subscription.is_current.is_(True))):
        s.is_current = False
    db.flush()
    now = datetime.now(UTC)
    db.add(
        Subscription(
            tenant_id=tenant_id, plan_id=plan.id, status="active", current_period_start=now, current_period_end=now + timedelta(days=body.days), is_current=True
        )
    )
    _a(db, p, "admin.plan_assigned", tenant_id=tenant_id, details={"plan": plan.code, "days": body.days, "reason": body.reason})
    db.commit()
    return {"status": "assigned"}


@router.get("/plans")
def list_plans(_: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {c.name: getattr(pl, c.name) for c in Plan.__table__.columns if c.name not in ("created_at", "updated_at")} | {"id": str(pl.id)}
        for pl in db.scalars(select(Plan).order_by(Plan.price_minor))
    ]


@router.put("/plans")
def upsert_plan(body: PlanIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == body.code))
    if plan is None:
        plan = Plan(**body.model_dump())
        db.add(plan)
    else:
        for k, v in body.model_dump().items():
            setattr(plan, k, v)
    _a(db, p, "admin.plan_upserted", details={"code": body.code})
    db.commit()
    return {"code": plan.code, "id": str(plan.id)}


@router.get("/kill-switch")
def get_kill_switch(_: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    s = db.get(PlatformSetting, "outbound_kill_switch")
    return s.value if s else {"enabled": False}


@router.put("/kill-switch")
def set_kill_switch(body: KillSwitchIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    """Platform-wide emergency stop for ALL outbound dialing."""
    s = db.get(PlatformSetting, "outbound_kill_switch") or PlatformSetting(key="outbound_kill_switch", value={})
    s.value = {"enabled": body.enabled, "reason": body.reason, "by": str(p.user.id), "at": datetime.now(UTC).isoformat()}
    db.merge(s)
    _a(db, p, "admin.kill_switch", details={"enabled": body.enabled, "reason": body.reason})
    db.commit()
    return s.value


@router.get("/health")
def platform_health(_: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:  # noqa: BLE001
        redis_ok = False
    day = datetime.now(UTC) - timedelta(days=1)
    return {
        "database": "ok",
        "redis": "ok" if redis_ok else "unavailable",
        "tenants": {
            "active": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.status == "active")),
            "suspended": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.status == "suspended")),
        },
        "calls_24h": db.scalar(select(func.count()).select_from(Call).where(Call.created_at >= day)),
        "live_calls": db.scalar(select(func.count()).select_from(Call).where(Call.status.in_(("queued", "provider_accepted", "ringing", "in_progress")))),
        "webhooks_failed": db.scalar(select(func.count()).select_from(WebhookEvent).where(WebhookEvent.status == "failed")),
        "outbox_pending": db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status.in_(("pending", "failed")))),
        "outbox_dead": db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "dead")),
        "job_failures_open": db.scalar(select(func.count()).select_from(BackgroundJobFailure).where(BackgroundJobFailure.resolved.is_(False))),
    }


@router.get("/audit-logs")
def platform_audit(_: Principal = Depends(require_superadmin), db: Session = Depends(get_db), limit: int = Query(100, le=500)) -> list[dict]:
    from app.audit.models import AuditLog

    return [
        {
            "id": str(a.id),
            "tenant_id": str(a.tenant_id) if a.tenant_id else None,
            "actor": str(a.actor_user_id) if a.actor_user_id else None,
            "actor_type": a.actor_type,
            "action": a.action,
            "details": a.details,
            "at": a.created_at.isoformat(),
        }
        for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    ]
