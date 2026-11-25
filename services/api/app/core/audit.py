from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import current_trace_id
from app.models import AuditEvent, PlatformAuditEvent


def audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    target_ref: str,
    outcome: str = "success",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        target_ref=target_ref,
        outcome=outcome,
        trace_id=current_trace_id(),
        detail=detail or {},
    )
    db.add(ev)
    return ev


def platform_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_ref: str,
    reason: str = "",
    target_tenant_id: uuid.UUID | None = None,
    outcome: str = "success",
    detail: dict[str, Any] | None = None,
) -> PlatformAuditEvent:
    ev = PlatformAuditEvent(
        actor_id=actor_id,
        action=action,
        target_tenant_id=target_tenant_id,
        target_ref=target_ref,
        outcome=outcome,
        reason=reason,
        trace_id=current_trace_id(),
        detail=detail or {},
    )
    db.add(ev)
    return ev
