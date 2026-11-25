"""KOK-20 identity preference APIs (§28.2)."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.audit import audit
from app.core.deps import Tenant, TenantContext, capability
from app.core.errors import Forbidden, NotFound, RevisionConflict
from app.domain.capabilities import CapabilityKey
from app.domain.constants import SUPPORTED_LOCALES, AuditAction, EventType, Permission
from app.identity.service import clean_name, resolve_identity
from app.models import AssistantIdentityPreference, OutboxEvent

router = APIRouter(prefix="/v1", tags=["assistant-identity"])
IdCtx = Annotated[TenantContext, Depends(capability(CapabilityKey.ASSISTANT_IDENTITY))]

USER_FIELDS = (
    "display_name",
    "spoken_name",
    "aliases",
    "pronunciation_hint",
    "wake_phrase",
    "locale",
    "response_length",
    "speaking_rate",
    "voice_profile_id",
)


class IdentityPatch(BaseModel):
    display_name: str | None = None
    spoken_name: str | None = None
    aliases: Annotated[list[str] | None, Field(max_length=8)] = None
    pronunciation_hint: Annotated[str | None, Field(max_length=120)] = None
    wake_phrase: str | None = None
    locale: str | None = None
    response_length: Literal["short", "medium", "long"] | None = None
    speaking_rate: Annotated[float | None, Field(ge=0.5, le=2.0)] = None
    voice_profile_id: Annotated[str | None, Field(max_length=64, pattern=r"^[a-z0-9_-]+$")] = None
    allow_personal_override: bool | None = None
    expected_revision: int = Field(ge=0, description="0 when no preference exists yet")

    @field_validator("display_name", "spoken_name", "wake_phrase")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [clean_name(a) for a in v]

    @field_validator("locale")
    @classmethod
    def _locale(cls, v: str | None) -> str | None:
        if v is not None and v != "auto" and v not in SUPPORTED_LOCALES:
            raise ValueError("unsupported locale")
        return v


async def _upsert(
    ctx: TenantContext, *, scope: str, body: IdentityPatch, user_id: uuid.UUID | None, allowed: tuple[str, ...]
) -> AssistantIdentityPreference:
    stmt = select(AssistantIdentityPreference).where(
        AssistantIdentityPreference.tenant_id == ctx.tenant_id, AssistantIdentityPreference.scope == scope
    )
    if scope == "user":
        stmt = stmt.where(AssistantIdentityPreference.user_id == user_id)
    pref = await ctx.db.scalar(stmt.with_for_update())
    current = pref.revision if pref else 0
    if current != body.expected_revision:
        raise RevisionConflict("identity preference changed", details={"current_revision": current})
    data = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if set(data) - set(allowed):
        raise Forbidden("field not editable at this scope", details={"fields": sorted(set(data) - set(allowed))})
    if pref is None:
        name = data.get("display_name", "Kokila")
        pref = AssistantIdentityPreference(
            tenant_id=ctx.tenant_id,
            scope=scope,
            user_id=user_id,
            display_name=name,
            spoken_name=data.get("spoken_name", name),
            updated_by=ctx.user_id,
            revision=0,
        )
        ctx.db.add(pref)
    for k, v in data.items():
        setattr(pref, k, v)
    if "wake_phrase" in data:
        # A display-name change is not proof of detector support (§28.3).
        pref.wake_status = "pending" if data["wake_phrase"] else "disabled"
    pref.revision += 1
    pref.updated_by = ctx.user_id
    ctx.db.add(
        OutboxEvent(
            tenant_id=ctx.tenant_id,
            event_type=EventType.IDENTITY_CHANGED,
            payload={"scope": scope, "user_id": str(user_id) if user_id else None, "revision": pref.revision},
        )
    )
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.IDENTITY_UPDATED,
        target_ref=f"identity:{scope}",
        detail={"fields": sorted(data)},
    )
    await ctx.db.flush()
    return pref


async def _view(ctx: TenantContext, own: AssistantIdentityPreference | None, editable: list[str]) -> dict:
    eff = await resolve_identity(ctx.db, ctx.policy, ctx.tenant_id, ctx.user_id)
    return {
        "effective": asdict(eff),
        "editable_fields": editable,
        "revision": own.revision if own else 0,
        "source_scope": eff.source_scope,
    }


@router.get("/assistant/preferences", operation_id="assistant_preferences_get")
async def get_preferences(ctx: Tenant) -> dict:
    """Always readable so clients render the effective name, even without customization rights."""
    own = await ctx.db.scalar(
        select(AssistantIdentityPreference).where(
            AssistantIdentityPreference.tenant_id == ctx.tenant_id,
            AssistantIdentityPreference.scope == "user",
            AssistantIdentityPreference.user_id == ctx.user_id,
        )
    )
    eff = await resolve_identity(ctx.db, ctx.policy, ctx.tenant_id, ctx.user_id)
    editable = list(USER_FIELDS) if eff.customization_enabled and eff.personal_override_allowed else []
    return await _view(ctx, own, editable)


@router.patch("/assistant/preferences", operation_id="assistant_preferences_patch")
async def patch_preferences(body: IdentityPatch, ctx: IdCtx) -> dict:
    eff = await resolve_identity(ctx.db, ctx.policy, ctx.tenant_id, ctx.user_id)
    if not eff.personal_override_allowed:
        raise Forbidden("your workspace administrator has locked the assistant identity")
    pref = await _upsert(ctx, scope="user", body=body, user_id=ctx.user_id, allowed=USER_FIELDS)
    return await _view(ctx, pref, list(USER_FIELDS))


@router.get("/tenants/{tenant_id}/assistant-identity", operation_id="tenant_identity_get")
async def get_tenant_identity(tenant_id: uuid.UUID, ctx: IdCtx) -> dict:
    if tenant_id != ctx.tenant_id:
        raise NotFound("not found")
    ctx.require(Permission.TENANT_IDENTITY_MANAGE)
    pref = await ctx.db.scalar(
        select(AssistantIdentityPreference).where(
            AssistantIdentityPreference.tenant_id == ctx.tenant_id, AssistantIdentityPreference.scope == "tenant"
        )
    )
    return await _view(ctx, pref, [*USER_FIELDS, "allow_personal_override"])


@router.patch("/tenants/{tenant_id}/assistant-identity", operation_id="tenant_identity_patch")
async def patch_tenant_identity(tenant_id: uuid.UUID, body: IdentityPatch, ctx: IdCtx) -> dict:
    if tenant_id != ctx.tenant_id:
        raise NotFound("not found")
    ctx.require(Permission.TENANT_IDENTITY_MANAGE)
    pref = await _upsert(
        ctx, scope="tenant", body=body, user_id=None, allowed=(*USER_FIELDS, "allow_personal_override")
    )
    return await _view(ctx, pref, [*USER_FIELDS, "allow_personal_override"])


class WakeValidateIn(BaseModel):
    phrase: str
    locale: str = "en-IN"

    @field_validator("phrase")
    @classmethod
    def _p(cls, v: str) -> str:
        return clean_name(v)


@router.post("/assistant/preferences/wake-word/validate", operation_id="wake_word_validate")
async def validate_wake_word(body: WakeValidateIn, ctx: Tenant) -> dict:
    """No wake-word detector is installed and benchmarked yet, so every phrase reports `unsupported`.

    Clients must fall back to push-to-talk / explicit activation (§23.1, §28.3).
    """
    ctx.require_capability(CapabilityKey.ASSISTANT_HANDSFREE)
    return {
        "phrase": body.phrase,
        "locale": body.locale,
        "wake_status": "unsupported",
        "reason": "no validated wake-word detector is configured for this deployment",
        "fallback": "push_to_talk",
    }
