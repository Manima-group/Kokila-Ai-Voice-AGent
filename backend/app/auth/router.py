import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.auth.deps import Principal, current_principal
from app.billing.service import start_trial
from app.core.config import get_settings
from app.core.errors import Conflict, Unauthorized
from app.core.ratelimit import auth_rate_limit, client_ip
from app.core.security import (
    create_access_token,
    hash_password,
    new_refresh_token,
    sha256_hex,
    verify_password,
)
from app.db.session import get_db
from app.tenants.models import RefreshToken, Tenant, TenantMembership, User

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "kokila_refresh"
MAX_FAILED = 5


class RegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    industry: str | None = None

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain letters and digits")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _issue(db: Session, response: Response, user: User, family: uuid.UUID | None = None) -> TokenOut:
    s = get_settings()
    raw, digest = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            family_id=family or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_ttl_days),
        )
    )
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        max_age=s.refresh_token_ttl_days * 86400,
        path="/api/v1/auth",
    )
    return TokenOut(access_token=create_access_token(user.id, user.is_superadmin), expires_in=s.access_token_ttl_minutes * 60)


@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(auth_rate_limit)])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("An account with this email already exists")
    tenant = Tenant(name=body.company_name, slug=_slugify(body.company_name), industry=body.industry, compliance={}, settings={})
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add_all([tenant, user])
    db.flush()
    db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="COMPANY_ADMIN"))
    start_trial(db, tenant.id)
    audit(db, "tenant.registered", tenant_id=tenant.id, actor_user_id=user.id, ip=client_ip(request))
    out = _issue(db, response, user)
    db.commit()
    return out


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    now = datetime.now(UTC)
    if user and user.locked_until and user.locked_until > now:
        raise Unauthorized("Account temporarily locked. Try again later.", code="account_locked")
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_logins = 0
            audit(db, "auth.login_failed", actor_user_id=user.id, ip=client_ip(request))
            db.commit()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    user.failed_logins = 0
    user.last_login_at = now
    audit(db, "auth.login", actor_user_id=user.id, ip=client_ip(request))
    out = _issue(db, response, user)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthorized("Missing refresh token")
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)).with_for_update())
    now = datetime.now(UTC)
    if not token:
        raise Unauthorized("Invalid refresh token")
    if token.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family (possible theft).
        for t in db.scalars(select(RefreshToken).where(RefreshToken.family_id == token.family_id)):
            t.revoked_at = t.revoked_at or now
        audit(db, "auth.refresh_reuse_detected", actor_user_id=token.user_id, ip=client_ip(request))
        db.commit()
        raise Unauthorized("Refresh token reuse detected")
    if token.expires_at < now:
        raise Unauthorized("Refresh token expired", code="token_expired")
    user = db.get(User, token.user_id)
    if not user or not user.is_active:
        raise Unauthorized("User inactive")
    token.revoked_at = now
    out = _issue(db, response, user, family=token.family_id)
    db.commit()
    return out


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
        if token:
            for t in db.scalars(select(RefreshToken).where(RefreshToken.family_id == token.family_id)):
                t.revoked_at = t.revoked_at or datetime.now(UTC)
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


@router.get("/me")
def me(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == principal.user.id, TenantMembership.is_active.is_(True))
    ).all()
    from app.auth.rbac import ROLE_PERMISSIONS, Role

    return {
        "id": str(principal.user.id),
        "email": principal.user.email,
        "full_name": principal.user.full_name,
        "is_superadmin": principal.user.is_superadmin,
        "memberships": [
            {
                "tenant_id": str(t.id),
                "tenant_name": t.name,
                "role": m.role,
                "tenant_status": t.status,
                "permissions": sorted(ROLE_PERMISSIONS[Role(m.role)]),
            }
            for m, t in rows
        ],
    }
