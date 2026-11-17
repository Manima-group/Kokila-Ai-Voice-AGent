import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.models import AuditLog


def audit(
    db: Session,
    action: str,
    *,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_type: str = "user",
    resource_type: str | None = None,
    resource_id: Any = None,
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    """Add an audit row to the current transaction (caller commits)."""
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            ip_address=ip,
            details=details or {},
        )
    )


def audit_ctx(db: Session, ctx, action: str, resource_type: str | None = None, resource_id: Any = None, **details) -> None:
    audit(
        db,
        action,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=ctx.ip,
        details=details,
    )
