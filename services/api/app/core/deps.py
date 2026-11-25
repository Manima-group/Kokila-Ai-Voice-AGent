"""Request principals. Membership, tenant status and entitlements are revalidated per request (§32.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import DbScope, set_context, unit_of_work
from app.core.errors import CapabilityDisabled, Forbidden, MfaRequired, Unauthenticated
from app.core.security import AccessClaims, decode_access_token
from app.domain.constants import (
    PLATFORM_ROLE_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    PlatformPermission,
    PlatformRole,
    TenantRole,
)
from app.models import Membership, Organization, RefreshToken, User
from app.platform.entitlements import EffectivePolicy, effective_policy


def _bearer(authorization: str | None) -> AccessClaims:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated("missing bearer token")
    return decode_access_token(authorization.split(" ", 1)[1].strip())


async def _family_active(db: AsyncSession, claims: AccessClaims) -> bool:
    """Access tokens die with their refresh family (logout / reuse detection / suspension)."""
    row = await db.scalar(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == claims.session_family, RefreshToken.revoked_at.is_(None))
        .limit(1)
    )
    return row is not None


@dataclass(slots=True)
class TenantContext:
    db: AsyncSession
    user: User
    tenant: Organization
    membership: Membership
    policy: EffectivePolicy
    claims: AccessClaims

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[TenantRole(self.membership.role)]

    def require(self, perm: Permission) -> None:
        if perm not in self.permissions:
            raise Forbidden("permission denied", details={"permission": perm.value})

    def require_capability(self, key: str) -> None:
        if not self.policy.allows(key):
            cap = self.policy.capabilities.get(key)
            raise CapabilityDisabled(
                f"capability {key} is not enabled for this workspace",
                details={"capability": key, "reason": cap.reason if cap else "unknown"},
            )

    async def release(self) -> None:
        """Commit and end the transaction before slow external calls (§29.3: never hold a
        transaction across provider calls). Call ``reattach`` before touching the DB again."""
        await self.db.commit()

    async def reattach(self) -> None:
        await set_context(self.db, scope=DbScope.TENANT, user_id=self.user.id, tenant_id=self.tenant.id)
        await self.refresh_policy()
        membership = await self.db.scalar(
            select(Membership).where(Membership.tenant_id == self.tenant.id, Membership.user_id == self.user.id)
        )
        if membership is None or membership.status != "active" or not self.policy.tenant_active:
            raise Forbidden("workspace access revoked")

    async def refresh_policy(self) -> None:
        """Re-evaluate immediately before side effects (§25, §27.6)."""
        self.policy = await effective_policy(self.db, self.tenant.id)


async def tenant_context(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> AsyncIterator[TenantContext]:
    claims = _bearer(authorization)
    if claims.tenant_id is None:
        raise Forbidden("token has no active workspace")
    async with unit_of_work(scope=DbScope.TENANT, user_id=claims.user_id, tenant_id=claims.tenant_id) as db:
        user = await db.get(User, claims.user_id)
        if user is None or user.status != "active" or not await _family_active(db, claims):
            raise Unauthenticated("session is no longer valid")
        membership = await db.scalar(
            select(Membership).where(Membership.tenant_id == claims.tenant_id, Membership.user_id == user.id)
        )
        tenant = await db.get(Organization, claims.tenant_id)
        if membership is None or membership.status != "active" or tenant is None:
            raise Forbidden("workspace access denied")
        policy = await effective_policy(db, tenant.id)
        if not policy.tenant_active:
            raise Forbidden("workspace is suspended", details={"tenant_status": tenant.status})
        request.state.tenant_id = str(tenant.id)
        yield TenantContext(db, user, tenant, membership, policy, claims)


Tenant = Annotated[TenantContext, Depends(tenant_context, scope="function")]


def capability(key: str) -> Callable[[TenantContext], Coroutine[Any, Any, TenantContext]]:
    async def _dep(ctx: Tenant) -> TenantContext:
        ctx.require_capability(key)
        return ctx

    return _dep


@dataclass(slots=True)
class PlatformContext:
    db: AsyncSession
    user: User
    role: PlatformRole
    claims: AccessClaims

    def require(self, perm: PlatformPermission) -> None:
        if perm not in PLATFORM_ROLE_PERMISSIONS[self.role]:
            raise Forbidden("platform permission denied", details={"permission": perm.value})


async def platform_context(authorization: Annotated[str | None, Header()] = None) -> AsyncIterator[PlatformContext]:
    claims = _bearer(authorization)
    if not claims.platform:
        raise Forbidden("platform access requires a platform session")
    async with unit_of_work(scope=DbScope.PLATFORM, user_id=claims.user_id) as db:
        user = await db.get(User, claims.user_id)
        if user is None or user.status != "active" or not user.platform_role or not await _family_active(db, claims):
            raise Forbidden("platform access denied")
        if not (user.mfa_enabled and claims.mfa):
            raise MfaRequired("multi-factor authentication is required for platform administration")
        yield PlatformContext(db, user, PlatformRole(user.platform_role), claims)


Platform = Annotated[PlatformContext, Depends(platform_context, scope="function")]


async def user_session(
    authorization: Annotated[str | None, Header()] = None,
) -> AsyncIterator[tuple[AsyncSession, User, AccessClaims]]:
    """Authenticated user without an active-workspace requirement (MFA enrolment, workspace list)."""
    claims = _bearer(authorization)
    async with unit_of_work(scope=DbScope.TENANT, user_id=claims.user_id, tenant_id=claims.tenant_id) as db:
        user = await db.get(User, claims.user_id)
        if user is None or user.status != "active" or not await _family_active(db, claims):
            raise Unauthenticated("session is no longer valid")
        yield db, user, claims


UserSession = Annotated[tuple[AsyncSession, User, AccessClaims], Depends(user_session, scope="function")]
