"""Signed provider webhooks: call events, inbound routing, and agent tool calls."""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.billing.service import check_call_allowed
from app.calls.service import EventRejected, apply_event, ensure_call
from app.calls.tools import execute_tool
from app.core.errors import AppError, NotFound, Unauthorized
from app.core.phone import try_normalize
from app.core.ratelimit import webhook_rate_limit
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.integrations.models import WebhookEvent
from app.telephony.models import PhoneNumber, ProviderAccount
from app.tenants.models import Tenant
from app.voice.base import VoiceProvider
from app.voice.registry import get_provider

log = logging.getLogger("kokila.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(webhook_rate_limit)])
SIG_HEADER = "x-retell-signature"
VOICE_PROVIDERS = ("retell", "mock")


def _provider_for(db: Session, provider: str, account_id: uuid.UUID | None) -> tuple[VoiceProvider, str]:
    if provider not in VOICE_PROVIDERS:
        raise NotFound("Unknown provider")
    if account_id is None:
        return get_provider(provider), f"{provider}:platform"
    acct = db.get(ProviderAccount, account_id)
    if acct is None or acct.provider != provider or acct.status != "active":
        raise NotFound("Unknown provider account")
    return get_provider(provider, decrypt_secret(acct.encrypted_api_key)), f"{provider}:{acct.id}"


def _verified_payload(provider: VoiceProvider, raw: bytes, signature: str | None) -> dict:
    body = raw.decode("utf-8", errors="strict")
    if not provider.verify_webhook(body, signature):
        raise Unauthorized("Invalid webhook signature", code="invalid_signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise AppError("Malformed JSON", code="malformed_payload")
    if not isinstance(payload, dict):
        raise AppError("Malformed payload", code="malformed_payload")
    return payload


def _handle_inbound(db: Session, provider: VoiceProvider, route_key: str, payload: dict) -> dict:
    ev = provider.normalize_event(payload)
    to_number = try_normalize(ev.to_number)
    number = (
        db.scalar(select(PhoneNumber).where(PhoneNumber.route_key == route_key, PhoneNumber.e164 == to_number, PhoneNumber.status == "active"))
        if to_number
        else None
    )
    if number is None or number.inbound_agent_id is None:
        return {"call_inbound": {}}
    tenant = db.get(Tenant, number.tenant_id)
    agent = db.get(Agent, number.inbound_agent_id)
    if tenant is None or tenant.status != "active" or agent is None or agent.status != "published" or not agent.provider_agent_id:
        return {"call_inbound": {}}
    from app.platform.entitlements import has as has_capability

    if not has_capability(db, tenant.id, "voice.inbound"):
        log.warning("inbound call blocked: voice.inbound not enabled")
        return {"call_inbound": {}}
    try:
        check_call_allowed(db, tenant.id)
    except AppError as exc:
        log.warning("inbound call blocked by entitlement: %s", exc.code)
        return {"call_inbound": {}}
    return {
        "call_inbound": {
            "override_agent_id": agent.provider_agent_id,
            "dynamic_variables": {"company_name": tenant.name},
            "metadata": {"kokila_tenant_id": str(tenant.id), "kokila_phone_number_id": str(number.id)},
        }
    }


def process_stored_event(db: Session, event_id: uuid.UUID) -> str:
    """Process a persisted WebhookEvent (used inline and by the retry worker)."""
    we = db.get(WebhookEvent, event_id)
    if we is None or we.status in ("processed", "ignored"):
        return "skipped"
    provider_name, route_key = we.source, we.payload.get("_route_key", f"{we.source}:platform")
    provider = get_provider(provider_name) if provider_name == "mock" or route_key.endswith(":platform") else None
    if provider is None:
        acct = db.get(ProviderAccount, uuid.UUID(route_key.split(":", 1)[1]))
        provider = get_provider(provider_name, decrypt_secret(acct.encrypted_api_key)) if acct else get_provider(provider_name)
    we.attempts += 1
    try:
        ev = provider.normalize_event(we.payload)
        call, _ = apply_event(db, provider_name, route_key, ev, is_mock=provider_name == "mock")
        we.tenant_id, we.status, we.processed_at, we.error = call.tenant_id, "processed", datetime.now(UTC), None
        db.commit()
        return "processed"
    except EventRejected as exc:
        db.rollback()
        we = db.get(WebhookEvent, event_id)
        assert we is not None
        we.status, we.error = "ignored", str(exc)
        db.commit()
        return "ignored"
    except Exception as exc:  # noqa: BLE001 - durable retry via worker
        db.rollback()
        log.exception("webhook processing failed")
        we = db.get(WebhookEvent, event_id)
        assert we is not None
        we.status, we.error = "failed", f"{exc.__class__.__name__}: {str(exc)[:400]}"
        we.attempts += 1
        db.commit()
        return "failed"


def _receive(provider_name: str, account_id: uuid.UUID | None, raw: bytes, signature: str | None) -> dict:
    with SessionLocal() as db:
        provider, route_key = _provider_for(db, provider_name, account_id)
        payload = _verified_payload(provider, raw, signature)
        if payload.get("event") == "call_inbound":
            return _handle_inbound(db, provider, route_key, payload)
        try:
            ev = provider.normalize_event(payload)
        except ValueError as exc:
            raise AppError(f"Malformed event: {exc}", code="malformed_payload")
        we = WebhookEvent(source=provider_name, dedupe_key=ev.dedupe_key, event_type=ev.event_type, payload={**payload, "_route_key": route_key})
        db.add(we)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"status": "duplicate"}
        return {"status": process_stored_event(db, we.id)}


@router.post("/{provider}")
async def provider_webhook(provider: str, request: Request) -> dict:
    raw = await request.body()
    return await run_in_threadpool(_receive, provider, None, raw, request.headers.get(SIG_HEADER))


@router.post("/{provider}/accounts/{account_id}")
async def provider_account_webhook(provider: str, account_id: uuid.UUID, request: Request) -> dict:
    raw = await request.body()
    return await run_in_threadpool(_receive, provider, account_id, raw, request.headers.get(SIG_HEADER))


def _tool(provider_name: str, tool: str, raw: bytes, signature: str | None) -> dict:
    with SessionLocal() as db:
        provider, route_key = _provider_for(db, provider_name, None)
        payload = _verified_payload(provider, raw, signature)
        call_obj = payload.get("call")
        if not isinstance(call_obj, dict):
            raise AppError("Missing call", code="malformed_payload")
        ev = provider.normalize_event({"event": "tool_call", "call": call_obj})
        try:
            call = ensure_call(db, provider_name, route_key, ev, is_mock=provider_name == "mock")
        except EventRejected as exc:
            raise AppError(str(exc), code="unknown_call", status_code=404)
        result = execute_tool(db, call, tool, payload.get("args") or {})
        db.commit()
        return result


@router.post("/{provider}/tools/{tool}")
async def tool_call(provider: str, tool: str, request: Request) -> dict:
    raw = await request.body()
    return await run_in_threadpool(_tool, provider, tool, raw, request.headers.get(SIG_HEADER))
