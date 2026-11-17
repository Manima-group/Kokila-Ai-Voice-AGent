import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.rbac import has_permission
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import decode_access_token
from app.db.session import get_db
from app.tenants.models import Tenant, TenantMembership, User


@dataclass
class Principal:
    user: User
    ip: str


@dataclass
class TenantContext:
    user: User
    tenant: Tenant
    role: str
    ip: str

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    def can(self, permission: str) -> bool:
        return has_permission(self.role, permission)


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    try:
        payload = decode_access_token(auth[7:])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Access token expired", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid access token")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise Unauthorized("User inactive")
    return Principal(user=user, ip=request.client.host if request.client else "")


def tenant_context(
    principal: Principal = Depends(current_principal),
    x_tenant_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> TenantContext:
    """Resolve tenant from the X-Tenant-ID header, validated against the user's active membership."""
    q = (
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == principal.user.id, TenantMembership.is_active.is_(True))
    )
    if x_tenant_id:
        try:
            tid = uuid.UUID(x_tenant_id)
        except ValueError:
            raise Forbidden("Invalid tenant")
        q = q.where(TenantMembership.tenant_id == tid)
    rows = db.execute(q).all()
    if not rows:
        raise Forbidden("No access to this tenant")
    if len(rows) > 1:
        raise Forbidden("Multiple tenants: send X-Tenant-ID", code="tenant_required")
    membership, tenant = rows[0]
    if tenant.status != "active":
        raise Forbidden("Tenant is suspended", code="tenant_suspended")
    return TenantContext(user=principal.user, tenant=tenant, role=membership.role, ip=principal.ip)


def require(permission: str):
    def _dep(ctx: TenantContext = Depends(tenant_context)) -> TenantContext:
        if not ctx.can(permission):
            raise Forbidden(f"Missing permission: {permission}")
        return ctx

    return _dep


def require_superadmin(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.user.is_superadmin:
        raise Forbidden("Super admin only")
    return principal


def get_owned[T](db: Session, model: type[T], obj_id: uuid.UUID, ctx: TenantContext) -> T:
    """Fetch a tenant-owned row; returns 404 (not 403) for other tenants to avoid existence leaks."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "tenant_id", None) != ctx.tenant_id:
        raise NotFound(f"{model.__name__} not found")
    return obj
