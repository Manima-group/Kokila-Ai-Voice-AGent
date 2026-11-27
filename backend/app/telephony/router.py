import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability
from app.core.config import get_settings
from app.core.errors import AppError, Conflict
from app.core.phone import normalize_e164
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.schemas.common import ORM
from app.telephony.models import PhoneNumber, ProviderAccount
from app.voice.base import ProviderError
from app.voice.registry import get_provider

router = APIRouter(tags=["telephony"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT, "voice.agents"))])


class AccountIn(BaseModel):
    provider: str = Field(pattern="^(retell)$")
    label: str = Field(min_length=2, max_length=120)
    api_key: str = Field(min_length=8, max_length=500)


class AccountOut(ORM):
    id: uuid.UUID
    provider: str
    label: str
    status: str
    created_at: datetime


class NumberIn(BaseModel):
    e164: str
    label: str | None = None
    provider_account_id: uuid.UUID | None = None
    number_type: str = Field(default="service", pattern="^(service|promotional|other)$")
    inbound_agent_id: uuid.UUID | None = None
    outbound_enabled: bool = False


class NumberPatch(BaseModel):
    label: str | None = None
    inbound_agent_id: uuid.UUID | None = None
    outbound_enabled: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class NumberOut(ORM):
    id: uuid.UUID
    e164: str
    label: str | None
    provider: str
    provider_account_id: uuid.UUID | None
    number_type: str
    inbound_agent_id: uuid.UUID | None
    outbound_enabled: bool
    status: str
    created_at: datetime


@router.get("/provider-accounts", response_model=list[AccountOut])
def list_accounts(ctx: TenantContext = Depends(require("phone_numbers:read")), db: Session = Depends(get_db)):
    return db.scalars(select(ProviderAccount).where(ProviderAccount.tenant_id == ctx.tenant_id)).all()


@router.post("/provider-accounts", response_model=AccountOut, status_code=201)
def add_account(body: AccountIn, ctx: TenantContext = Depends(require("phone_numbers:write")), db: Session = Depends(get_db)):
    acct = ProviderAccount(tenant_id=ctx.tenant_id, provider=body.provider, label=body.label, encrypted_api_key=encrypt_secret(body.api_key))
    db.add(acct)
    audit_ctx(db, ctx, "provider_account.created", "provider_account", None, provider=body.provider)
    db.commit()
    return acct


@router.get("/phone-numbers", response_model=list[NumberOut])
def list_numbers(ctx: TenantContext = Depends(require("phone_numbers:read")), db: Session = Depends(get_db)):
    return db.scalars(select(PhoneNumber).where(PhoneNumber.tenant_id == ctx.tenant_id).order_by(PhoneNumber.created_at)).all()


def _sync_route(db: Session, number: PhoneNumber) -> None:
    agent = db.get(Agent, number.inbound_agent_id) if number.inbound_agent_id else None
    api_key = None
    if number.provider_account_id:
        acct = db.get(ProviderAccount, number.provider_account_id)
        api_key = decrypt_secret(acct.encrypted_api_key) if acct else None
    base = get_settings().public_base_url.rstrip("/")
    hook = f"{base}/api/v1/webhooks/{number.provider}" + (f"/accounts/{number.provider_account_id}" if number.provider_account_id else "")
    try:
        get_provider(number.provider, api_key).configure_inbound_route(number.e164, agent.provider_agent_id if agent else None, hook)
    except ProviderError as exc:
        raise AppError(f"Provider rejected number configuration: {exc}", code="provider_error", status_code=502)


@router.post("/phone-numbers", response_model=NumberOut, status_code=201)
def add_number(body: NumberIn, ctx: TenantContext = Depends(require("phone_numbers:write")), db: Session = Depends(get_db)):
    e164 = normalize_e164(body.e164)
    provider: str = get_settings().voice_provider
    if body.provider_account_id:
        acct = get_owned(db, ProviderAccount, body.provider_account_id, ctx)
        provider = acct.provider
    if body.inbound_agent_id:
        get_owned(db, Agent, body.inbound_agent_id, ctx)
    route_key = f"{provider}:{body.provider_account_id or 'platform'}"
    number = PhoneNumber(
        tenant_id=ctx.tenant_id,
        provider=provider,
        provider_account_id=body.provider_account_id,
        route_key=route_key,
        e164=e164,
        label=body.label,
        number_type=body.number_type,
        inbound_agent_id=body.inbound_agent_id,
        outbound_enabled=body.outbound_enabled,
    )
    db.add(number)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("This number is already registered on this provider account")
    _sync_route(db, number)
    audit_ctx(db, ctx, "phone_number.added", "phone_number", number.id)
    db.commit()
    return number


@router.patch("/phone-numbers/{number_id}", response_model=NumberOut)
def update_number(number_id: uuid.UUID, body: NumberPatch, ctx: TenantContext = Depends(require("phone_numbers:write")), db: Session = Depends(get_db)):
    number = get_owned(db, PhoneNumber, number_id, ctx)
    data = body.model_dump(exclude_unset=True)
    if data.get("inbound_agent_id"):
        get_owned(db, Agent, data["inbound_agent_id"], ctx)
    for k, v in data.items():
        setattr(number, k, v)
    if "inbound_agent_id" in data:
        _sync_route(db, number)
    audit_ctx(db, ctx, "phone_number.updated", "phone_number", number.id, fields=list(data))
    db.commit()
    return number
