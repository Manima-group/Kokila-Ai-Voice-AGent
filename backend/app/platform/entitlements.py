"""Effective capability policy.

effective(key) = known key AND platform control not disabled AND (unexpired tenant override, else current plan)
                 AND subscription active AND all dependencies effective. Default deny.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import Subscription
from app.core.errors import AppError
from app.platform.models import PlanCapability, PlatformCapabilityControl, TenantCapabilityOverride
from app.platform.registry import BY_KEY, CAPABILITIES

ACTIVE = ("trialing", "active")


class CapabilityDisabled(AppError):
    status_code = 403
    code = "capability_disabled"


@dataclass
class CapabilityState:
    key: str
    effective: bool
    source: str  # plan | override | platform_disabled | dependency | subscription_inactive | not_licensed
    plan_enabled: bool
    override: bool | None
    limits: dict


def evaluate(db: Session, tenant_id: uuid.UUID) -> dict[str, CapabilityState]:
    now = datetime.now(UTC)
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id, Subscription.is_current.is_(True)))
    sub_active = bool(sub and sub.status in ACTIVE and sub.current_period_end > now)
    plan_caps = {p.capability_key: p for p in (db.scalars(select(PlanCapability).where(PlanCapability.plan_id == sub.plan_id)) if sub else [])}
    overrides = {
        o.capability_key: o
        for o in db.scalars(select(TenantCapabilityOverride).where(TenantCapabilityOverride.tenant_id == tenant_id))
        if o.expires_at is None or o.expires_at > now
    }
    platform_off = {c.capability_key for c in db.scalars(select(PlatformCapabilityControl).where(PlatformCapabilityControl.enabled.is_(False)))}

    raw: dict[str, CapabilityState] = {}
    for cap in CAPABILITIES:
        plan_on = bool(plan_caps.get(cap.key) and plan_caps[cap.key].enabled)
        ov = overrides.get(cap.key)
        granted = ov.enabled if ov is not None else plan_on
        limits = (ov.limits if ov is not None and ov.limits else None) or (plan_caps[cap.key].limits if cap.key in plan_caps else {}) or {}
        if cap.key in platform_off:
            state = CapabilityState(cap.key, False, "platform_disabled", plan_on, ov.enabled if ov else None, limits)
        elif not granted:
            state = CapabilityState(cap.key, False, "not_licensed", plan_on, ov.enabled if ov else None, limits)
        elif not sub_active:
            state = CapabilityState(cap.key, False, "subscription_inactive", plan_on, ov.enabled if ov else None, limits)
        else:
            state = CapabilityState(cap.key, True, "override" if ov is not None else "plan", plan_on, ov.enabled if ov else None, limits)
        raw[cap.key] = state

    # Dependencies: iterate to a fixed point (registry is a DAG).
    changed = True
    while changed:
        changed = False
        for cap in CAPABILITIES:
            st = raw[cap.key]
            if st.effective and any(not raw[d].effective for d in cap.depends_on):
                st.effective, st.source = False, "dependency"
                changed = True
    return raw


def has(db: Session, tenant_id: uuid.UUID, key: str) -> bool:
    if key not in BY_KEY:
        return False  # default deny for unknown keys
    return evaluate(db, tenant_id)[key].effective


def require(db: Session, tenant_id: uuid.UUID, key: str) -> None:
    states = evaluate(db, tenant_id)
    st = states.get(key)
    if st is not None and st.source == "subscription_inactive":
        from app.core.errors import PaymentRequired

        raise PaymentRequired("No active subscription", code="subscription_inactive")
    if st is None or not st.effective:
        label = BY_KEY[key].label if key in BY_KEY else key
        raise CapabilityDisabled(f"'{label}' is not enabled for your organization", code="capability_disabled")
