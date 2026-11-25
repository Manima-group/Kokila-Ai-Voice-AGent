"""Authentication: register, login, refresh rotation with reuse detection, logout, MFA (§32.1)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update

from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import DbScope, set_context, unit_of_work
from app.core.deps import Tenant, UserSession
from app.core.errors import Forbidden, KokilaError, Unauthenticated
from app.core.ratelimit import hit
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    issue_access_token,
    needs_rehash,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.domain.constants import AuditAction, ErrorCode
from app.models import Membership, Organization, Plan, RefreshToken, Subscription, User
from app.platform.entitlements import policy_summary

router = APIRouter(prefix="/v1", tags=["auth"])

DEFAULT_PERSONAL_PLAN = "assistant-free"


class RegisterIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=256)]
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    locale: str = "en-IN"
    timezone: str = "Asia/Kolkata"

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v or re.search(r"[<>]", v):
            raise ValueError("invalid display name")
        return v


class AcceptedOut(BaseModel):
    status: str = "accepted"
    message: str


class LoginIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]
    workspace_id: uuid.UUID | None = None
    otp: Annotated[str | None, Field(max_length=10)] = None
    platform: bool = False


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    workspace_id: uuid.UUID | None
    platform: bool
    mfa: bool


class RefreshIn(BaseModel):
    refresh_token: Annotated[str, Field(min_length=20, max_length=200)]
    workspace_id: uuid.UUID | None = None


class MfaVerifyIn(BaseModel):
    code: Annotated[str, Field(min_length=6, max_length=10)]


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{uuid.uuid4().hex[:8]}"


@router.post("/auth/register", status_code=202, response_model=AcceptedOut, operation_id="auth_register")
async def register(body: RegisterIn, request: Request) -> AcceptedOut:
    await hit("register", request.client.host if request.client else "unknown", limit=10, window_s=3600)
    email = body.email.lower()
    neutral = AcceptedOut(message="If this address can be registered, you can now sign in.")
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    async with unit_of_work(scope=DbScope.TENANT, user_id=user_id, tenant_id=org_id) as db:
        if await db.scalar(select(User.id).where(User.email == email)):
            return neutral  # anti-enumeration: identical response
        db.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(body.password),
                display_name=body.display_name,
                locale=body.locale,
                timezone=body.timezone,
            )
        )
        db.add(
            Organization(
                id=org_id, name=f"{body.display_name}'s workspace", slug=_slug(body.display_name), type="personal"
            )
        )
        await db.flush()
        db.add(Membership(tenant_id=org_id, user_id=user_id, role="owner"))
        plan = await db.scalar(
            select(Plan)
            .where(Plan.code == DEFAULT_PERSONAL_PLAN, Plan.active.is_(True))
            .order_by(Plan.version.desc())
            .limit(1)
        )
        if plan is not None:
            db.add(Subscription(tenant_id=org_id, plan_id=plan.id, status="active", period_start=datetime.now(UTC)))
        audit(db, tenant_id=org_id, actor_id=user_id, action=AuditAction.USER_REGISTERED, target_ref=f"user:{user_id}")
    return neutral


async def _issue(
    db, user: User, tenant_id: uuid.UUID | None, *, mfa: bool, platform: bool, family_id: uuid.UUID | None = None
) -> TokenOut:
    s = get_settings()
    family_id = family_id or uuid.uuid4()
    raw, digest = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=digest,
            tenant_id=tenant_id,
            mfa=mfa,
            expires_at=datetime.now(UTC) + timedelta(seconds=s.refresh_token_ttl_s),
        )
    )
    access, exp = issue_access_token(
        user_id=user.id, tenant_id=tenant_id, mfa=mfa, family_id=family_id, platform=platform
    )
    return TokenOut(
        access_token=access, refresh_token=raw, expires_at=exp, workspace_id=tenant_id, platform=platform, mfa=mfa
    )


async def _pick_workspace(db, user: User, requested: uuid.UUID | None) -> uuid.UUID | None:
    await set_context(db, scope=DbScope.TENANT, user_id=user.id)
    rows = (
        await db.execute(
            select(Membership.tenant_id, Organization.type, Organization.status)
            .join(Organization, Organization.id == Membership.tenant_id)
            .where(Membership.user_id == user.id, Membership.status == "active")
            .order_by(Organization.type.desc(), Membership.created_at)
        )
    ).all()
    active = [r for r in rows if r.status == "active"]
    if requested is not None:
        if not any(r.tenant_id == requested for r in active):
            raise Forbidden("workspace access denied")
        return requested
    return active[0].tenant_id if active else None


_BAD_LOGIN = "invalid email, password or verification code"


@router.post("/auth/login", response_model=TokenOut, operation_id="auth_login")
async def login(body: LoginIn, request: Request) -> TokenOut:
    email = body.email.lower()
    ip = request.client.host if request.client else "unknown"
    await hit("login-ip", ip, limit=30, window_s=300)
    await hit("login-acct", email, limit=10, window_s=300)
    async with unit_of_work(scope=DbScope.ANONYMOUS) as db:
        user = await db.scalar(select(User).where(User.email == email))
        ok = verify_password(user.password_hash if user else None, body.password)
        if not ok or user is None or user.status != "active":
            raise Unauthenticated(_BAD_LOGIN)
        mfa = False
        if user.mfa_enabled:
            if not body.otp:
                raise KokilaError("verification code required", code=ErrorCode.MFA_REQUIRED, status_code=401)
            secret = decrypt_secret(user.mfa_secret_enc or "", aad=f"mfa:{user.id}")
            if not verify_totp(secret, body.otp):
                raise Unauthenticated(_BAD_LOGIN)
            mfa = True
        if user.password_hash and needs_rehash(user.password_hash):
            user.password_hash = hash_password(body.password)
        if body.platform:
            if not user.platform_role:
                raise Forbidden("platform access denied")
            if not mfa:
                raise KokilaError(
                    "platform administration requires multi-factor authentication",
                    code=ErrorCode.MFA_REQUIRED,
                    status_code=403,
                )
            return await _issue(db, user, None, mfa=True, platform=True)
        tenant_id = await _pick_workspace(db, user, body.workspace_id)
        if tenant_id is not None:
            await set_context(db, scope=DbScope.TENANT, user_id=user.id, tenant_id=tenant_id)
            audit(
                db, tenant_id=tenant_id, actor_id=user.id, action=AuditAction.USER_LOGIN, target_ref=f"user:{user.id}"
            )
        return await _issue(db, user, tenant_id, mfa=mfa, platform=False)


@router.post("/auth/refresh", response_model=TokenOut, operation_id="auth_refresh")
async def refresh(body: RefreshIn) -> TokenOut:
    digest = hash_token(body.refresh_token)
    reuse_family: uuid.UUID | None = None
    async with unit_of_work(scope=DbScope.ANONYMOUS) as db:
        tok = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update())
        now = datetime.now(UTC)
        if tok is None or tok.revoked_at is not None or tok.expires_at <= now:
            raise Unauthenticated("refresh token invalid")
        if tok.used_at is not None:
            reuse_family = tok.family_id
        else:
            tok.used_at = now
            user = await db.get(User, tok.user_id)
            if user is None or user.status != "active":
                raise Unauthenticated("refresh token invalid")
            platform = bool(user.platform_role) and tok.tenant_id is None and tok.mfa
            tenant = None if platform else await _pick_workspace(db, user, body.workspace_id or tok.tenant_id)
            return await _issue(db, user, tenant, mfa=tok.mfa, platform=platform, family_id=tok.family_id)
    # Reuse of a rotated token: revoke the whole family in its own committed transaction.
    async with unit_of_work(scope=DbScope.ANONYMOUS) as db:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == reuse_family, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    raise Unauthenticated("refresh token reuse detected; session revoked")


@router.post("/auth/logout", status_code=204, operation_id="auth_logout")
async def logout(session: UserSession) -> None:
    db, _user, claims = session
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == claims.session_family, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


class MfaEnrollOut(BaseModel):
    otpauth_uri: str
    secret: str


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut, operation_id="auth_mfa_enroll")
async def mfa_enroll(session: UserSession) -> MfaEnrollOut:
    db, user, _ = session
    if user.mfa_enabled:
        raise KokilaError("MFA already enabled", status_code=409, code=ErrorCode.STATE_CONFLICT)
    secret = new_totp_secret()
    user.mfa_secret_enc = encrypt_secret(secret, aad=f"mfa:{user.id}")
    return MfaEnrollOut(otpauth_uri=totp_uri(secret, user.email), secret=secret)


@router.post("/auth/mfa/verify", status_code=204, operation_id="auth_mfa_verify")
async def mfa_verify(body: MfaVerifyIn, session: UserSession) -> None:
    db, user, claims = session
    if user.mfa_enabled or not user.mfa_secret_enc:
        raise KokilaError("no pending MFA enrolment", status_code=409, code=ErrorCode.STATE_CONFLICT)
    if not verify_totp(decrypt_secret(user.mfa_secret_enc, aad=f"mfa:{user.id}"), body.code):
        raise KokilaError("invalid verification code", status_code=422)
    user.mfa_enabled = True
    if claims.tenant_id:
        audit(
            db,
            tenant_id=claims.tenant_id,
            actor_id=user.id,
            action=AuditAction.MFA_ENABLED,
            target_ref=f"user:{user.id}",
        )


# --- current user ----------------------------------------------------------------------------------------


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    locale: str
    timezone: str
    mfa_enabled: bool
    platform_role: str | None
    workspace_id: uuid.UUID | None
    role: str | None


@router.get("/me", response_model=MeOut, operation_id="me_get")
async def me(session: UserSession) -> MeOut:
    db, user, claims = session
    role = None
    if claims.tenant_id:
        role = await db.scalar(
            select(Membership.role).where(Membership.tenant_id == claims.tenant_id, Membership.user_id == user.id)
        )
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        timezone=user.timezone,
        mfa_enabled=user.mfa_enabled,
        platform_role=user.platform_role,
        workspace_id=claims.tenant_id,
        role=role,
    )


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    status: str
    role: str


@router.get("/me/workspaces", response_model=list[WorkspaceOut], operation_id="me_workspaces")
async def my_workspaces(session: UserSession) -> list[WorkspaceOut]:
    db, user, _ = session
    rows = (
        await db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.tenant_id == Organization.id)
            .where(Membership.user_id == user.id, Membership.status == "active")
        )
    ).all()
    return [WorkspaceOut(id=o.id, name=o.name, type=o.type, status=o.status, role=r) for o, r in rows]


@router.get("/me/capabilities", operation_id="me_capabilities")
async def my_capabilities(ctx: Tenant) -> dict:
    """Effective capabilities for rendering. Disabled capabilities are not executable (§26.2)."""
    summary = policy_summary(ctx.policy)
    return {
        "workspace_id": str(ctx.tenant_id),
        "revision": summary["revision"],
        "enabled": ctx.policy.enabled_keys(),
        "permissions": sorted(p.value for p in ctx.permissions),
        "capabilities": {
            k: {"enabled": v["enabled"], "reason": v["reason"]} for k, v in summary["capabilities"].items()
        },
    }
