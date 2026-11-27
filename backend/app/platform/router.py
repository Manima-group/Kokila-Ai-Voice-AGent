"""Capability discovery (tenant users) and capability administration (Manima Super Admin)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.auth.deps import Principal, TenantContext, require_superadmin, tenant_context
from app.billing.models import Plan
from app.core.errors import AppError, Conflict, NotFound
from app.db.session import get_db
from app.platform.entitlements import evaluate
from app.platform.models import PlanCapability, PlatformCapabilityControl, TenantCapabilityOverride
from app.platform.registry import BY_KEY, CAPABILITIES, closure_problems
from app.tenants.models import Tenant

router = APIRouter(tags=["platform"])


def _catalog() -> list[dict]:
    return [
        {
            "key": c.key,
            "req_id": c.req_id,
            "product": c.product,
            "label": c.label,
            "description": c.description,
            "depends_on": list(c.depends_on),
            "quota_metric": c.quota_metric,
        }
        for c in CAPABILITIES
    ]


def _effective_view(db: Session, tenant_id: uuid.UUID) -> list[dict]:
    states = evaluate(db, tenant_id)
    return [
        {
            "key": k,
            "label": BY_KEY[k].label,
            "product": BY_KEY[k].product,
            "effective": s.effective,
            "source": s.source,
            "plan_enabled": s.plan_enabled,
            "override": s.override,
            "limits": s.limits,
        }
        for k, s in states.items()
    ]


@router.get("/me/capabilities")
def my_capabilities(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    states = evaluate(db, ctx.tenant_id)
    return {
        "tenant_id": str(ctx.tenant_id),
        "policy_revision": ctx.tenant.policy_revision,
        "capabilities": {k: s.effective for k, s in states.items()},
        "reasons": {k: s.source for k, s in states.items() if not s.effective},
    }


# ---- Super Admin --------------------------------------------------------------------------------------------------
class ChangeIn(BaseModel):
    key: str
    enabled: bool | None = Field(description="true/false to override; null removes the override (fall back to plan)")
    limits: dict = Field(default_factory=dict)
    expires_at: datetime | None = None


class TenantCapsIn(BaseModel):
    changes: list[ChangeIn] = Field(min_length=1, max_length=50)
    expected_revision: int
    reason: str = Field(min_length=3, max_length=500)
    cascade: bool = Field(default=True, description="Also disable capabilities that depend on a disabled one")


class PlanCapsIn(BaseModel):
    enabled: list[str]
    reason: str = Field(min_length=3, max_length=500)


class ControlIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


@router.get("/admin/capabilities")
def catalog(_: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    controls = {c.capability_key: c for c in db.scalars(select(PlatformCapabilityControl))}
    return {"capabilities": [{**c, "platform_enabled": controls[c["key"]].enabled if c["key"] in controls else True} for c in _catalog()]}


@router.put("/admin/capabilities/{key}/control")
def set_control(key: str, body: ControlIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    if key not in BY_KEY:
        raise NotFound("Unknown capability")
    ctl = db.get(PlatformCapabilityControl, key) or PlatformCapabilityControl(capability_key=key, revision=0)
    ctl.enabled, ctl.reason, ctl.updated_by, ctl.revision = body.enabled, body.reason, p.user.id, (ctl.revision or 0) + 1
    db.merge(ctl)
    audit(
        db,
        "admin.capability_platform_control",
        actor_user_id=p.user.id,
        actor_type="superadmin",
        ip=p.ip,
        details={"key": key, "enabled": body.enabled, "reason": body.reason},
    )
    db.commit()
    return {"key": key, "enabled": body.enabled}


@router.get("/admin/plans/{code}/capabilities")
def plan_caps(code: str, _: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise NotFound("Plan not found")
    enabled = [pc.capability_key for pc in db.scalars(select(PlanCapability).where(PlanCapability.plan_id == plan.id, PlanCapability.enabled.is_(True)))]
    return {"plan": code, "enabled": sorted(enabled)}


@router.put("/admin/plans/{code}/capabilities")
def set_plan_caps(code: str, body: PlanCapsIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise NotFound("Plan not found")
    problems = closure_problems(set(body.enabled))
    if problems:
        raise Conflict("Invalid package: " + "; ".join(problems), code="dependency_conflict")
    existing = {pc.capability_key: pc for pc in db.scalars(select(PlanCapability).where(PlanCapability.plan_id == plan.id))}
    for key in BY_KEY:
        on = key in body.enabled
        if key in existing:
            existing[key].enabled = on
        elif on:
            db.add(PlanCapability(plan_id=plan.id, capability_key=key, enabled=True, limits={}))
    audit(
        db,
        "admin.plan_capabilities_set",
        actor_user_id=p.user.id,
        actor_type="superadmin",
        ip=p.ip,
        details={"plan": code, "enabled": sorted(body.enabled), "reason": body.reason},
    )
    db.commit()
    return {"plan": code, "enabled": sorted(body.enabled)}


@router.get("/admin/tenants/{tenant_id}/capabilities")
def tenant_caps(tenant_id: uuid.UUID, _: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found")
    return {"tenant_id": str(tenant_id), "revision": tenant.policy_revision, "capabilities": _effective_view(db, tenant_id)}


@router.patch("/admin/tenants/{tenant_id}/capabilities")
def update_tenant_caps(tenant_id: uuid.UUID, body: TenantCapsIn, p: Principal = Depends(require_superadmin), db: Session = Depends(get_db)) -> dict:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise NotFound("Tenant not found")
    if tenant.policy_revision != body.expected_revision:
        raise Conflict(f"Revision changed (current {tenant.policy_revision}); reload and retry", code="revision_conflict")
    for ch in body.changes:
        if ch.key not in BY_KEY:
            raise AppError(f"Unknown capability '{ch.key}'", code="unknown_capability", status_code=422)
    # Simulate the result and reject dependency-invalid packages atomically.
    overrides = {o.capability_key: o for o in db.scalars(select(TenantCapabilityOverride).where(TenantCapabilityOverride.tenant_id == tenant_id))}
    granted = {k for k, s in evaluate(db, tenant_id).items() if (s.override if s.override is not None else s.plan_enabled)}
    changes = list(body.changes)
    for ch in body.changes:
        if ch.enabled is True:
            granted.add(ch.key)
        elif ch.enabled is False:
            granted.discard(ch.key)
    cascaded: list[str] = []
    if body.cascade:
        disabled = {c.key for c in body.changes if c.enabled is False}
        explicit_on = {c.key for c in body.changes if c.enabled is True}
        grew = True
        while grew:
            grew = False
            for cap in CAPABILITIES:
                if cap.key in granted and cap.key not in explicit_on and any(d in disabled for d in cap.depends_on):
                    granted.discard(cap.key)
                    disabled.add(cap.key)
                    cascaded.append(cap.key)
                    changes.append(ChangeIn(key=cap.key, enabled=False))
                    grew = True
    problems = closure_problems(granted)
    if problems:
        raise Conflict("Dependency conflict: " + "; ".join(problems), code="dependency_conflict")
    for ch in changes:
        ov = overrides.get(ch.key)
        if ch.enabled is None:
            if ov:
                db.delete(ov)
            continue
        if ov is None:
            db.add(
                TenantCapabilityOverride(
                    tenant_id=tenant_id,
                    capability_key=ch.key,
                    enabled=ch.enabled,
                    limits=ch.limits,
                    expires_at=ch.expires_at,
                    reason=body.reason,
                    updated_by=p.user.id,
                )
            )
        else:
            ov.enabled, ov.limits, ov.expires_at, ov.reason, ov.updated_by = ch.enabled, ch.limits, ch.expires_at, body.reason, p.user.id
    tenant.policy_revision += 1
    audit(
        db,
        "admin.tenant_capabilities_changed",
        tenant_id=tenant_id,
        actor_user_id=p.user.id,
        actor_type="superadmin",
        ip=p.ip,
        details={"changes": [c.model_dump(mode="json") for c in body.changes], "reason": body.reason, "revision": tenant.policy_revision, "cascaded": cascaded},
    )
    db.commit()
    return {"tenant_id": str(tenant_id), "revision": tenant.policy_revision, "cascaded": cascaded, "capabilities": _effective_view(db, tenant_id)}
