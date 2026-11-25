"""Single entitlement policy used by every surface (§25, §26.3, §27.6).

effective(cap) = catalog active
             AND platform control not disabled
             AND (in-effect tenant override if present, else plan capability)
             AND every dependency effective
Explicit deny wins. Unknown/missing mapping => deny. Infrastructure keys are
always on (they are mandatory platform security, not purchasable features).
"""

from __future__ import annotations

import hashlib
import uuid
import zlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import orjson
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, KokilaError, NotFound, QuotaExceeded, RevisionConflict
from app.domain.capabilities import CAPABILITIES, INFRASTRUCTURE_KEYS
from app.domain.constants import ErrorCode, EventType
from app.models import (
    CapabilityCatalog,
    CapabilityDependency,
    Organization,
    OutboxEvent,
    PlanCapability,
    PlatformCapabilityControl,
    PolicyRevision,
    Subscription,
    TenantCapabilityOverride,
    UsageEvent,
)


@dataclass(slots=True)
class EffectiveCapability:
    key: str
    enabled: bool
    source: str  # plan | override | infrastructure | none
    reason: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EffectivePolicy:
    tenant_id: uuid.UUID
    revision: int
    tenant_active: bool
    capabilities: dict[str, EffectiveCapability]

    def allows(self, key: str) -> bool:
        cap = self.capabilities.get(key)
        return bool(self.tenant_active and cap and cap.enabled)

    def enabled_keys(self) -> list[str]:
        return sorted(k for k, c in self.capabilities.items() if c.enabled) if self.tenant_active else []


async def _catalog(session: AsyncSession) -> tuple[dict[str, CapabilityCatalog], dict[str, list[str]]]:
    cats = {c.key: c for c in (await session.scalars(select(CapabilityCatalog))).all()}
    deps: dict[str, list[str]] = {k: [] for k in cats}
    for e in (await session.scalars(select(CapabilityDependency))).all():
        deps.setdefault(e.capability_key, []).append(e.depends_on)
    return cats, deps


def _in_effect(o: TenantCapabilityOverride, now: datetime) -> bool:
    return (o.effective_at is None or o.effective_at <= now) and (o.expires_at is None or now < o.expires_at)


def _resolve(
    cats: dict[str, CapabilityCatalog],
    deps: dict[str, list[str]],
    plan: dict[str, PlanCapability],
    overrides: dict[str, TenantCapabilityOverride],
    controls: dict[str, PlatformCapabilityControl],
    now: datetime,
) -> dict[str, EffectiveCapability]:
    base: dict[str, EffectiveCapability] = {}
    for key, cat in cats.items():
        if key in INFRASTRUCTURE_KEYS or not cat.purchasable:
            base[key] = EffectiveCapability(key, True, "infrastructure")
            continue
        if not cat.active:
            base[key] = EffectiveCapability(key, False, "none", "catalog_inactive")
            continue
        ctl = controls.get(key)
        if ctl is not None and not ctl.enabled:
            base[key] = EffectiveCapability(key, False, "platform", "platform_disabled")
            continue
        ov = overrides.get(key)
        if ov is not None and _in_effect(ov, now):
            base[key] = EffectiveCapability(
                key, ov.enabled, "override", None if ov.enabled else "tenant_override_denied", dict(ov.limits)
            )
            continue
        pc = plan.get(key)
        if pc is not None:
            base[key] = EffectiveCapability(
                key, pc.enabled, "plan", None if pc.enabled else "plan_disabled", dict(pc.limits)
            )
        else:
            base[key] = EffectiveCapability(key, False, "none", "not_entitled")

    resolved: dict[str, bool] = {}

    def ok(k: str, seen: frozenset[str] = frozenset()) -> bool:
        if k in resolved:
            return resolved[k]
        if k in seen or k not in base:
            return False  # cycles and unknown keys fail closed
        v = base[k].enabled and all(ok(d, seen | {k}) for d in deps.get(k, []))
        resolved[k] = v
        return v

    for k, cap in base.items():
        if cap.enabled and not ok(k):
            cap.enabled, cap.reason = False, "dependency_disabled"
    return base


async def effective_policy(session: AsyncSession, tenant_id: uuid.UUID, now: datetime | None = None) -> EffectivePolicy:
    now = now or datetime.now(UTC)
    org = await session.get(Organization, tenant_id)
    if org is None:
        raise NotFound("tenant not found")
    cats, deps = await _catalog(session)
    sub = await session.scalar(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id, Subscription.status.in_(("trialing", "active", "past_due"))
        )
    )
    plan: dict[str, PlanCapability] = {}
    if sub is not None:
        plan = {
            p.capability_key: p
            for p in (await session.scalars(select(PlanCapability).where(PlanCapability.plan_id == sub.plan_id))).all()
        }
    overrides = {
        o.capability_key: o
        for o in (
            await session.scalars(
                select(TenantCapabilityOverride).where(TenantCapabilityOverride.tenant_id == tenant_id)
            )
        ).all()
    }
    controls = {c.capability_key: c for c in (await session.scalars(select(PlatformCapabilityControl))).all()}
    caps = _resolve(cats, deps, plan, overrides, controls, now)
    return EffectivePolicy(tenant_id, org.policy_revision, org.status == "active", caps)


@dataclass(slots=True)
class EntitlementChange:
    key: str
    enabled: bool
    limits: dict[str, Any] | None = None
    expires_at: datetime | None = None


async def apply_entitlement_changes(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    changes: list[EntitlementChange],
    expected_revision: int,
    reason: str,
    actor_id: uuid.UUID,
) -> tuple[EffectivePolicy, list[dict[str, Any]]]:
    """Atomically apply overrides. Rejects the whole request on any conflict (§26.5)."""
    org = await session.scalar(select(Organization).where(Organization.id == tenant_id).with_for_update())
    if org is None:
        raise NotFound("tenant not found")
    if org.policy_revision != expected_revision:
        raise RevisionConflict(
            "tenant policy changed; reload and retry", details={"current_revision": org.policy_revision}
        )
    cats, deps = await _catalog(session)
    for ch in changes:
        if ch.key not in cats:
            raise KokilaError(f"unknown capability {ch.key}", status_code=422)
        if ch.key in INFRASTRUCTURE_KEYS or not cats[ch.key].purchasable:
            raise KokilaError(f"{ch.key} is mandatory platform infrastructure and cannot be toggled", status_code=422)
    now = datetime.now(UTC)
    before = await effective_policy(session, tenant_id, now)
    disabling = {ch.key for ch in changes if not ch.enabled}
    existing = {
        o.capability_key: o
        for o in (
            await session.scalars(
                select(TenantCapabilityOverride).where(TenantCapabilityOverride.tenant_id == tenant_id)
            )
        ).all()
    }
    for ch in changes:
        o = existing.get(ch.key)
        if o is None:
            o = TenantCapabilityOverride(tenant_id=tenant_id, capability_key=ch.key, revision=1)
            session.add(o)
            existing[ch.key] = o
        else:
            o.revision += 1
        o.enabled, o.limits, o.expires_at = ch.enabled, ch.limits or {}, ch.expires_at
        o.effective_at, o.reason, o.updated_by, o.updated_at = now, reason, actor_id, now
    await session.flush()

    prospective = await effective_policy(session, tenant_id, now)
    conflicts = [
        {
            "key": ch.key,
            "missing_dependencies": [d for d in deps.get(ch.key, []) if not prospective.capabilities[d].enabled],
        }
        for ch in changes
        if ch.enabled
        and not prospective.capabilities[ch.key].enabled
        and prospective.capabilities[ch.key].reason == "dependency_disabled"
    ]
    # Disabling a capability others depend on is also a conflict unless those are disabled too.
    for ch in changes:
        if ch.enabled:
            continue
        dependants = sorted(
            k for k, ds in deps.items() if ch.key in ds and before.capabilities[k].enabled and k not in disabling
        )
        if dependants:
            conflicts.append({"key": ch.key, "required_by": dependants})
    if conflicts:
        raise Conflict(
            "capability dependency conflict; no changes applied",
            code=ErrorCode.DEPENDENCY_CONFLICT,
            details={"dependency_conflicts": conflicts},
        )

    await bump_policy_revision(session, org, actor_id=actor_id, reason=reason, policy=prospective)
    prospective.revision = org.policy_revision
    return prospective, []


async def bump_policy_revision(
    session: AsyncSession, org: Organization, *, actor_id: uuid.UUID, reason: str, policy: EffectivePolicy | None = None
) -> None:
    """Policy revision + snapshot + outbox in the same transaction (§27.6)."""
    org.policy_revision += 1
    policy = policy or await effective_policy(session, org.id)
    snap = {"enabled": policy.enabled_keys(), "tenant_status": org.status}
    blob = orjson.dumps(snap, option=orjson.OPT_SORT_KEYS)
    now = datetime.now(UTC)
    session.add(
        PolicyRevision(
            tenant_id=org.id,
            revision=org.policy_revision,
            changed_by=actor_id,
            reason=reason,
            snapshot=snap,
            snapshot_hash=hashlib.sha256(blob).hexdigest(),
            effective_at=now,
        )
    )
    session.add(
        OutboxEvent(
            tenant_id=org.id,
            event_type=EventType.POLICY_CHANGED,
            payload={"tenant_id": str(org.id), "revision": org.policy_revision},
        )
    )
    await session.flush()


def policy_summary(p: EffectivePolicy) -> dict[str, Any]:
    return {
        "revision": p.revision,
        "tenant_active": p.tenant_active,
        "capabilities": {k: asdict(v) for k, v in sorted(p.capabilities.items())},
    }


async def consume_quota(
    session: AsyncSession,
    policy: EffectivePolicy,
    *,
    capability: str,
    user_id: uuid.UUID,
    source_event_id: str,
    quantity: Decimal = Decimal(1),
) -> None:
    """Serialize per tenant+metric with a transaction advisory lock, check monthly limit, record usage."""
    cdef = CAPABILITIES.get(capability)
    metric = cdef.quota_metric if cdef else None
    if not metric:
        return
    cap = policy.capabilities.get(capability)
    limit = (cap.limits or {}).get("monthly") if cap else None
    lock_key = zlib.crc32(f"{policy.tenant_id}:{metric}".encode())
    await session.execute(text("select pg_advisory_xact_lock(:k)"), {"k": lock_key})
    now = datetime.now(UTC)
    if limit is not None:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = await session.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.tenant_id == policy.tenant_id,
                UsageEvent.metric == metric,
                UsageEvent.occurred_at >= month_start,
            )
        )
        if Decimal(used or 0) + quantity > Decimal(str(limit)):
            raise QuotaExceeded(f"monthly quota for {metric} exhausted", details={"metric": metric, "limit": limit})
    session.add(
        UsageEvent(
            tenant_id=policy.tenant_id,
            user_id=user_id,
            source_event_id=source_event_id,
            metric=metric,
            quantity=quantity,
            occurred_at=now,
        )
    )
