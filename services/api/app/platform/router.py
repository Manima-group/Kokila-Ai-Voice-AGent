"""Manima Super Admin control plane (§25, §26.5). Never exposes tenant conversations or credentials."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.core.audit import platform_audit
from app.core.deps import Platform
from app.core.errors import KokilaError, NotFound, RevisionConflict
from app.domain.constants import AuditAction, PlatformPermission
from app.models import (
    CapabilityCatalog,
    CapabilityDependency,
    Membership,
    Organization,
    Plan,
    PlanCapability,
    PlatformAuditEvent,
    PlatformCapabilityControl,
    Subscription,
    TenantCapabilityOverride,
    User,
)
from app.platform.entitlements import (
    EntitlementChange,
    apply_entitlement_changes,
    bump_policy_revision,
    effective_policy,
    policy_summary,
)

router = APIRouter(prefix="/v1/platform", tags=["platform"])

Reason = Annotated[str, Field(min_length=3, max_length=500)]


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    type: str
    status: str
    policy_revision: int
    revision: int
    created_at: datetime
    plan_code: str | None = None
    enabled_count: int | None = None


class Page(BaseModel):
    items: list[Any]
    next_cursor: str | None


@router.get("/tenants", operation_id="platform_tenants_list")
async def list_tenants(
    ctx: Platform, cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50, q: str | None = None
) -> Page:
    ctx.require(PlatformPermission.TENANTS_READ)
    stmt = select(Organization).order_by(Organization.created_at.desc(), Organization.id.desc())
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q.replace('%', '')}%"))
    if cursor:
        ts, cid = cursor.split("|", 1)
        c_at = datetime.fromisoformat(ts)
        stmt = stmt.where(
            (Organization.created_at < c_at) | ((Organization.created_at == c_at) & (Organization.id < uuid.UUID(cid)))
        )
    rows = (await ctx.db.scalars(stmt.limit(limit + 1))).all()
    items = []
    for o in rows[:limit]:
        pol = await effective_policy(ctx.db, o.id)
        plan_code = await ctx.db.scalar(
            select(Plan.code)
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(Subscription.tenant_id == o.id, Subscription.status.in_(("trialing", "active", "past_due")))
        )
        purch = [k for k, c in pol.capabilities.items() if c.enabled and c.source != "infrastructure"]
        items.append(
            TenantOut(
                id=o.id,
                name=o.name,
                slug=o.slug,
                type=o.type,
                status=o.status,
                policy_revision=o.policy_revision,
                revision=o.revision,
                created_at=o.created_at,
                plan_code=plan_code,
                enabled_count=len(purch),
            )
        )
    nxt = f"{rows[limit - 1].created_at.isoformat()}|{rows[limit - 1].id}" if len(rows) > limit else None
    return Page(items=items, next_cursor=nxt)


class TenantCreateIn(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=160)]
    type: Literal["business", "personal"] = "business"
    owner_email: EmailStr
    plan_code: str | None = None
    reason: Reason


@router.post("/tenants", status_code=201, response_model=TenantOut, operation_id="platform_tenants_create")
async def create_tenant(body: TenantCreateIn, ctx: Platform) -> TenantOut:
    ctx.require(PlatformPermission.TENANTS_MANAGE)
    owner = await ctx.db.scalar(select(User).where(User.email == body.owner_email.lower()))
    if owner is None:
        raise KokilaError("owner must register before a workspace can be provisioned", status_code=422)
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:40] + "-" + uuid.uuid4().hex[:6]
    org = Organization(name=body.name, slug=slug, type=body.type)
    ctx.db.add(org)
    await ctx.db.flush()
    ctx.db.add(Membership(tenant_id=org.id, user_id=owner.id, role="owner"))
    plan_code = None
    if body.plan_code:
        plan = await _latest_plan(ctx, body.plan_code)
        ctx.db.add(Subscription(tenant_id=org.id, plan_id=plan.id, status="active", period_start=datetime.now(UTC)))
        plan_code = plan.code
    platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.TENANT_CREATED,
        target_ref=f"tenant:{org.id}",
        target_tenant_id=org.id,
        reason=body.reason,
        detail={"plan": plan_code},
    )
    await ctx.db.flush()
    await ctx.db.refresh(org)
    return TenantOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        type=org.type,
        status=org.status,
        policy_revision=org.policy_revision,
        revision=org.revision,
        created_at=org.created_at,
        plan_code=plan_code,
    )


async def _latest_plan(ctx: Platform, code: str) -> Plan:
    plan = await ctx.db.scalar(
        select(Plan).where(Plan.code == code, Plan.active.is_(True)).order_by(Plan.version.desc()).limit(1)
    )
    if plan is None:
        raise NotFound(f"plan {code} not found")
    return plan


async def _org(ctx: Platform, tenant_id: uuid.UUID, lock: bool = False) -> Organization:
    stmt = select(Organization).where(Organization.id == tenant_id)
    org = await ctx.db.scalar(stmt.with_for_update() if lock else stmt)
    if org is None:
        raise NotFound("tenant not found")
    return org


@router.get("/tenants/{tenant_id}", operation_id="platform_tenants_get")
async def get_tenant(tenant_id: uuid.UUID, ctx: Platform) -> dict:
    ctx.require(PlatformPermission.TENANTS_READ)
    org = await _org(ctx, tenant_id)
    sub = await ctx.db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id, Subscription.status.in_(("trialing", "active", "past_due"))
        )
    )
    plan = await ctx.db.get(Plan, sub.plan_id) if sub else None
    members = (
        await ctx.db.execute(select(Membership.role, Membership.status).where(Membership.tenant_id == tenant_id))
    ).all()
    return {
        "tenant": TenantOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            type=org.type,
            status=org.status,
            policy_revision=org.policy_revision,
            revision=org.revision,
            created_at=org.created_at,
            plan_code=plan.code if plan else None,
        ).model_dump(),
        "subscription": None
        if sub is None
        else {
            "id": str(sub.id),
            "status": sub.status,
            "plan_id": str(sub.plan_id),
            "revision": sub.revision,
            "plan_code": plan.code if plan else None,
            "plan_version": plan.version if plan else None,
        },
        "member_count": len(members),
        "policy": policy_summary(await effective_policy(ctx.db, tenant_id)),
    }


class TenantStatusIn(BaseModel):
    status: Literal["active", "suspended"]
    expected_revision: int
    reason: Reason


@router.patch("/tenants/{tenant_id}/status", operation_id="platform_tenants_status")
async def set_tenant_status(tenant_id: uuid.UUID, body: TenantStatusIn, ctx: Platform) -> dict:
    ctx.require(PlatformPermission.TENANTS_MANAGE)
    org = await _org(ctx, tenant_id, lock=True)
    if org.revision != body.expected_revision:
        raise RevisionConflict("tenant changed; reload and retry", details={"current_revision": org.revision})
    previous, org.status, org.revision = org.status, body.status, org.revision + 1
    await bump_policy_revision(ctx.db, org, actor_id=ctx.user.id, reason=body.reason)
    ev = platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.TENANT_STATUS_CHANGED,
        target_ref=f"tenant:{org.id}",
        target_tenant_id=org.id,
        reason=body.reason,
        detail={"from": previous, "to": body.status},
    )
    await ctx.db.flush()
    return {
        "id": str(org.id),
        "status": org.status,
        "revision": org.revision,
        "policy_revision": org.policy_revision,
        "audit_id": str(ev.id),
    }


@router.get("/capabilities", operation_id="platform_capabilities_list")
async def list_capabilities(ctx: Platform) -> dict:
    ctx.require(PlatformPermission.TENANTS_READ)
    cats = (await ctx.db.scalars(select(CapabilityCatalog).order_by(CapabilityCatalog.key))).all()
    deps: dict[str, list[str]] = {}
    for e in (await ctx.db.scalars(select(CapabilityDependency))).all():
        deps.setdefault(e.capability_key, []).append(e.depends_on)
    ctl = {c.capability_key: c for c in (await ctx.db.scalars(select(PlatformCapabilityControl))).all()}
    return {
        "items": [
            {
                "key": c.key,
                "requirement_id": c.requirement_id,
                "module": c.module,
                "product": c.product,
                "description": c.description,
                "purchasable": c.purchasable,
                "active": c.active,
                "quota_metric": c.quota_metric,
                "dependencies": sorted(deps.get(c.key, [])),
                "platform_enabled": ctl[c.key].enabled if c.key in ctl else True,
                "control_revision": ctl[c.key].revision if c.key in ctl else 0,
            }
            for c in cats
        ]
    }


class ControlIn(BaseModel):
    enabled: bool
    expected_revision: int = Field(ge=0)
    reason: Reason


@router.patch("/capabilities/{key}", operation_id="platform_capabilities_control")
async def set_platform_control(key: str, body: ControlIn, ctx: Platform) -> dict:
    """Global kill switch. Effective immediately: policy is evaluated live on every request."""
    ctx.require(PlatformPermission.CONTROLS_MANAGE)
    cat = await ctx.db.get(CapabilityCatalog, key)
    if cat is None:
        raise NotFound("capability not found")
    if not cat.purchasable:
        raise KokilaError("mandatory infrastructure capabilities cannot be disabled", status_code=422)
    ctl = await ctx.db.scalar(
        select(PlatformCapabilityControl).where(PlatformCapabilityControl.capability_key == key).with_for_update()
    )
    current = ctl.revision if ctl else 0
    if current != body.expected_revision:
        raise RevisionConflict("control changed; reload and retry", details={"current_revision": current})
    now = datetime.now(UTC)
    if ctl is None:
        ctl = PlatformCapabilityControl(
            capability_key=key,
            enabled=body.enabled,
            revision=1,
            reason=body.reason,
            updated_by=ctx.user.id,
            updated_at=now,
        )
        ctx.db.add(ctl)
    else:
        ctl.enabled, ctl.revision, ctl.reason, ctl.updated_by, ctl.updated_at = (
            body.enabled,
            ctl.revision + 1,
            body.reason,
            ctx.user.id,
            now,
        )
    ev = platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.PLATFORM_CONTROL_CHANGED,
        target_ref=f"capability:{key}",
        reason=body.reason,
        detail={"enabled": body.enabled},
    )
    await ctx.db.flush()
    return {"key": key, "enabled": ctl.enabled, "revision": ctl.revision, "audit_id": str(ev.id)}


class PlanCapIn(BaseModel):
    key: str
    enabled: bool = True
    limits: dict[str, Any] = Field(default_factory=dict)


class PlanIn(BaseModel):
    code: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    name: Annotated[str, Field(min_length=2, max_length=120)]
    product: Literal["assistant", "voice", "connect", "pro", "custom"]
    price_minor: int = Field(ge=0)
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "INR"
    limits: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[PlanCapIn]
    reason: Reason


@router.post("/plans", status_code=201, operation_id="platform_plans_create")
async def create_plan(body: PlanIn, ctx: Platform) -> dict:
    """Creates a new immutable plan version; existing subscriptions keep their version."""
    ctx.require(PlatformPermission.PLANS_MANAGE)
    cats = {c.key: c for c in (await ctx.db.scalars(select(CapabilityCatalog))).all()}
    deps: dict[str, list[str]] = {}
    for e in (await ctx.db.scalars(select(CapabilityDependency))).all():
        deps.setdefault(e.capability_key, []).append(e.depends_on)
    enabled = {c.key for c in body.capabilities if c.enabled}
    conflicts = []
    for c in body.capabilities:
        if c.key not in cats or not cats[c.key].purchasable:
            raise KokilaError(f"{c.key} is not a purchasable capability", status_code=422)
        missing = [d for d in deps.get(c.key, []) if c.enabled and d not in enabled]
        if missing:
            conflicts.append({"key": c.key, "missing_dependencies": missing})
    if conflicts:
        raise KokilaError("plan has dependency conflicts", status_code=409, details={"dependency_conflicts": conflicts})
    latest = await ctx.db.scalar(
        select(Plan.version).where(Plan.code == body.code).order_by(Plan.version.desc()).limit(1)
    )
    plan = Plan(
        code=body.code,
        version=(latest or 0) + 1,
        name=body.name,
        product=body.product,
        price_minor=body.price_minor,
        currency=body.currency,
        limits=body.limits,
    )
    ctx.db.add(plan)
    await ctx.db.flush()
    for c in body.capabilities:
        ctx.db.add(PlanCapability(plan_id=plan.id, capability_key=c.key, enabled=c.enabled, limits=c.limits))
    platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.PLAN_CREATED,
        target_ref=f"plan:{plan.id}",
        reason=body.reason,
        detail={"code": plan.code, "version": plan.version},
    )
    await ctx.db.flush()
    return {"id": str(plan.id), "code": plan.code, "version": plan.version}


@router.get("/plans", operation_id="platform_plans_list")
async def list_plans(ctx: Platform) -> dict:
    ctx.require(PlatformPermission.TENANTS_READ)
    plans = (await ctx.db.scalars(select(Plan).order_by(Plan.code, Plan.version.desc()))).all()
    out = []
    for p in plans:
        caps = (await ctx.db.scalars(select(PlanCapability).where(PlanCapability.plan_id == p.id))).all()
        out.append(
            {
                "id": str(p.id),
                "code": p.code,
                "version": p.version,
                "name": p.name,
                "product": p.product,
                "price_minor": p.price_minor,
                "currency": p.currency,
                "active": p.active,
                "capabilities": sorted(c.capability_key for c in caps if c.enabled),
            }
        )
    return {"items": out}


class SubscriptionIn(BaseModel):
    plan_code: str
    expected_revision: int
    reason: Reason


@router.put("/tenants/{tenant_id}/subscription", operation_id="platform_tenants_subscription")
async def set_subscription(tenant_id: uuid.UUID, body: SubscriptionIn, ctx: Platform) -> dict:
    """Plan change. Billing proration is reconciled by the billing module; no charge is made here."""
    ctx.require(PlatformPermission.PLANS_MANAGE)
    org = await _org(ctx, tenant_id, lock=True)
    if org.policy_revision != body.expected_revision:
        raise RevisionConflict("tenant policy changed", details={"current_revision": org.policy_revision})
    plan = await _latest_plan(ctx, body.plan_code)
    sub = await ctx.db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id, Subscription.status.in_(("trialing", "active", "past_due"))
        )
    )
    if sub is not None:
        sub.status = "cancelled"
        sub.period_end = datetime.now(UTC)
        await ctx.db.flush()
    ctx.db.add(Subscription(tenant_id=tenant_id, plan_id=plan.id, status="active", period_start=datetime.now(UTC)))
    await ctx.db.flush()
    await bump_policy_revision(ctx.db, org, actor_id=ctx.user.id, reason=body.reason)
    ev = platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.ENTITLEMENTS_CHANGED,
        target_ref=f"tenant:{tenant_id}",
        target_tenant_id=tenant_id,
        reason=body.reason,
        detail={"plan": plan.code, "plan_version": plan.version},
    )
    pol = await effective_policy(ctx.db, tenant_id)
    return {"revision": org.policy_revision, "effective_capabilities": pol.enabled_keys(), "audit_id": str(ev.id)}


@router.get("/tenants/{tenant_id}/entitlements", operation_id="platform_entitlements_get")
async def get_entitlements(tenant_id: uuid.UUID, ctx: Platform) -> dict:
    ctx.require(PlatformPermission.TENANTS_READ)
    await _org(ctx, tenant_id)
    overrides = (
        await ctx.db.scalars(select(TenantCapabilityOverride).where(TenantCapabilityOverride.tenant_id == tenant_id))
    ).all()
    pol = await effective_policy(ctx.db, tenant_id)
    return {
        **policy_summary(pol),
        "overrides": [
            {
                "key": o.capability_key,
                "enabled": o.enabled,
                "limits": o.limits,
                "reason": o.reason,
                "expires_at": o.expires_at,
                "revision": o.revision,
            }
            for o in overrides
        ],
    }


class ChangeIn(BaseModel):
    key: str
    enabled: bool
    limits: dict[str, Any] | None = None
    expires_at: datetime | None = None


class EntitlementsPatchIn(BaseModel):
    changes: Annotated[list[ChangeIn], Field(min_length=1, max_length=100)]
    expected_revision: int
    reason: Reason


@router.patch("/tenants/{tenant_id}/entitlements", operation_id="platform_entitlements_patch")
async def patch_entitlements(tenant_id: uuid.UUID, body: EntitlementsPatchIn, ctx: Platform) -> dict:
    ctx.require(PlatformPermission.ENTITLEMENTS_MANAGE)
    pol, conflicts = await apply_entitlement_changes(
        ctx.db,
        tenant_id=tenant_id,
        expected_revision=body.expected_revision,
        reason=body.reason,
        actor_id=ctx.user.id,
        changes=[EntitlementChange(c.key, c.enabled, c.limits, c.expires_at) for c in body.changes],
    )
    ev = platform_audit(
        ctx.db,
        actor_id=ctx.user.id,
        action=AuditAction.ENTITLEMENTS_CHANGED,
        target_ref=f"tenant:{tenant_id}",
        target_tenant_id=tenant_id,
        reason=body.reason,
        detail={"changes": [c.model_dump(mode="json") for c in body.changes]},
    )
    await ctx.db.flush()
    return {
        "revision": pol.revision,
        "effective_capabilities": pol.enabled_keys(),
        "dependency_conflicts": conflicts,
        "audit_id": str(ev.id),
    }


@router.get("/audit", operation_id="platform_audit_list")
async def list_audit(
    ctx: Platform,
    tenant_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> Page:
    ctx.require(PlatformPermission.AUDIT_READ)
    stmt = select(PlatformAuditEvent).order_by(PlatformAuditEvent.created_at.desc(), PlatformAuditEvent.id.desc())
    if tenant_id:
        stmt = stmt.where(PlatformAuditEvent.target_tenant_id == tenant_id)
    if cursor:
        ts, cid = cursor.split("|", 1)
        c_at = datetime.fromisoformat(ts)
        stmt = stmt.where(
            (PlatformAuditEvent.created_at < c_at)
            | ((PlatformAuditEvent.created_at == c_at) & (PlatformAuditEvent.id < uuid.UUID(cid)))
        )
    rows = (await ctx.db.scalars(stmt.limit(limit + 1))).all()
    items = [
        {
            "id": str(e.id),
            "actor_id": str(e.actor_id) if e.actor_id else None,
            "action": e.action,
            "target_ref": e.target_ref,
            "target_tenant_id": str(e.target_tenant_id) if e.target_tenant_id else None,
            "outcome": e.outcome,
            "reason": e.reason,
            "detail": e.detail,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows[:limit]
    ]
    nxt = f"{rows[limit - 1].created_at.isoformat()}|{rows[limit - 1].id}" if len(rows) > limit else None
    return Page(items=items, next_cursor=nxt)
