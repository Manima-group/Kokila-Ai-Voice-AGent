import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.models import Agent
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, get_owned, require, require_capability
from app.billing.service import check_call_allowed
from app.calls.service import TERMINAL, apply_event
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.phone import mask_phone, normalize_e164
from app.db.session import get_db
from app.platform.registry import PRODUCT_CALLING_AGENT
from app.schemas.common import ORM, paginate
from app.telephony.models import Call, CallEvent
from app.voice.base import ProviderError
from app.voice.providers.mock import MockVoiceProvider
from app.voice.registry import get_provider

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[Depends(require_capability(PRODUCT_CALLING_AGENT, "voice.agents"))])


class CallOut(ORM):
    id: uuid.UUID
    direction: str
    provider: str
    status: str
    analysis_status: str
    from_number: str | None
    to_number: str | None
    agent_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    outcome: str | None
    sentiment: str | None
    handoff_requested: bool
    is_mock: bool
    created_at: datetime


@router.get("")
def list_calls(
    ctx: TenantContext = Depends(require("calls:read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    outcome: str | None = None,
    direction: str | None = None,
    campaign_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Call).where(Call.tenant_id == ctx.tenant_id)
    for col, val in (
        (Call.status, status),
        (Call.outcome, outcome),
        (Call.direction, direction),
        (Call.campaign_id, campaign_id),
        (Call.contact_id, contact_id),
    ):
        if val is not None:
            stmt = stmt.where(col == val)
    page = paginate(db, stmt.order_by(Call.created_at.desc()), limit, offset, CallOut)
    if not ctx.can("calls:transcript"):  # viewers see masked numbers
        for item in page.items:
            item.from_number, item.to_number = mask_phone(item.from_number), mask_phone(item.to_number)
    return page


@router.get("/{call_id}")
def get_call(call_id: uuid.UUID, ctx: TenantContext = Depends(require("calls:read")), db: Session = Depends(get_db)) -> dict:
    call = get_owned(db, Call, call_id, ctx)
    out = CallOut.model_validate(call).model_dump(mode="json")
    events = db.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.created_at)).all()
    out["events"] = [{"type": e.event_type, "applied": e.applied, "at": e.created_at.isoformat()} for e in events]
    out["disconnection_reason"] = call.disconnection_reason
    if ctx.can("calls:transcript"):
        out.update(
            summary=call.summary,
            transcript=call.transcript,
            transcript_segments=call.transcript_segments,
            extracted={k: v for k, v in (call.extracted or {}).items() if not k.startswith("_")},
            recording_url=call.recording_url,
            provider_cost_minor=call.provider_cost_minor,
        )
    else:
        out.update(from_number=mask_phone(call.from_number), to_number=mask_phone(call.to_number), transcript=None)
    return out


@router.post("/{call_id}/terminate")
def terminate(call_id: uuid.UUID, ctx: TenantContext = Depends(require("calls:handoff")), db: Session = Depends(get_db)) -> dict:
    call = get_owned(db, Call, call_id, ctx)
    if call.status in TERMINAL:
        raise AppError("Call already ended", code="invalid_state", status_code=409)
    try:
        get_provider(call.provider).terminate_call(call.provider_call_id)
    except ProviderError as exc:
        raise AppError(f"Provider error: {exc}", code="provider_error", status_code=502)
    audit_ctx(db, ctx, "call.terminate_requested", "call", call.id)
    db.commit()
    return {"status": "termination_requested"}  # final state arrives via the signed call_ended webhook


@router.post("/{call_id}/handoff")
def mark_handoff(call_id: uuid.UUID, ctx: TenantContext = Depends(require("calls:handoff")), db: Session = Depends(get_db)) -> dict:
    call = get_owned(db, Call, call_id, ctx)
    call.handoff_requested = False
    call.extracted = {**(call.extracted or {}), "_handoff_handled_by": str(ctx.user.id)}
    audit_ctx(db, ctx, "call.handoff_resolved", "call", call.id)
    db.commit()
    return {"status": "resolved"}


# ---- Voice testing ------------------------------------------------------------------------------------------------
class TestCallIn(BaseModel):
    agent_id: uuid.UUID
    to_number: str
    from_number: str


class SimulateIn(BaseModel):
    agent_id: uuid.UUID
    caller_number: str = "+919000000001"
    utterances: list[str] = Field(default_factory=lambda: ["Hello, I want to know about your services."], max_length=20)
    outcome: str = "interested"
    language: str = "en"


@router.post("/test")
def test_call(body: TestCallIn, ctx: TenantContext = Depends(require("agents:test")), db: Session = Depends(get_db)) -> dict:
    """Place a real outbound test call to the requester's own number via the configured provider."""
    agent = get_owned(db, Agent, body.agent_id, ctx)
    if agent.status != "published" or not agent.provider_agent_id:
        raise AppError("Publish the agent first", code="agent_not_published", status_code=409)
    check_call_allowed(db, ctx.tenant_id)
    from app.voice.base import OutboundRequest

    provider = get_provider(agent.provider)
    key = f"test-{uuid.uuid4().hex}"
    try:
        pcid = provider.initiate_outbound_call(
            OutboundRequest(
                from_number=normalize_e164(body.from_number),
                to_number=normalize_e164(body.to_number),
                provider_agent_id=agent.provider_agent_id,
                idempotency_key=key,
                metadata={"kokila_tenant_id": str(ctx.tenant_id), "kokila_test_call": "1"},
            )
        )
    except ProviderError as exc:
        raise AppError(f"Provider error: {exc}", code="provider_error", status_code=502)
    audit_ctx(db, ctx, "call.test_placed", "agent", agent.id, provider=provider.name)
    db.commit()
    return {"provider": provider.name, "provider_call_id": pcid, "is_mock": provider.name == "mock"}


@router.post("/simulate")
def simulate(body: SimulateIn, ctx: TenantContext = Depends(require("agents:test")), db: Session = Depends(get_db)) -> dict:
    """MOCK MODE ONLY: run a simulated inbound conversation through the real event pipeline. Not a phone call."""
    s = get_settings()
    if s.voice_provider != "mock" or s.environment == "production":
        raise AppError("Simulation is only available in mock mode", code="mock_only", status_code=409)
    agent = get_owned(db, Agent, body.agent_id, ctx)
    if agent.status != "published":
        raise AppError("Publish the agent first", code="agent_not_published", status_code=409)
    provider = get_provider("mock")
    assert isinstance(provider, MockVoiceProvider)
    caller = normalize_e164(body.caller_number)
    call_id = f"mock_sim_{uuid.uuid4().hex[:16]}"
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    lines, segments = [], []
    from app.agents.models import AgentVersion

    version = db.get(AgentVersion, agent.published_version_id)
    greeting = version.config.get("greeting", "") if version else ""
    lines.append(f"Agent: {greeting}")
    segments.append({"role": "agent", "content": greeting})
    for u in body.utterances:
        lines.append(f"User: {u}")
        lines.append("Agent: [MOCK] Thank you. A team member will follow up with accurate details.")
        segments += [{"role": "user", "content": u}, {"role": "agent", "content": "[MOCK] Thank you."}]
    base = {
        "call_id": call_id,
        "agent_id": agent.provider_agent_id,
        "direction": "inbound",
        "from_number": caller,
        "to_number": None,
        "start_timestamp": now_ms - 60000,
        "metadata": {"kokila_tenant_id": str(ctx.tenant_id), "kokila_test_call": "1"},
    }
    events = [
        {"event": "call_started", "call": {**base, "call_status": "ongoing"}},
        {
            "event": "call_ended",
            "call": {
                **base,
                "call_status": "ended",
                "end_timestamp": now_ms,
                "duration_ms": 60000,
                "transcript": "\n".join(lines),
                "transcript_object": segments,
                "disconnection_reason": "user_hangup",
            },
        },
        {
            "event": "call_analyzed",
            "call": {
                **base,
                "call_status": "ended",
                "end_timestamp": now_ms,
                "duration_ms": 60000,
                "transcript": "\n".join(lines),
                "transcript_object": segments,
                "call_analysis": {
                    "call_summary": f"[MOCK] Simulated call ({body.language}).",
                    "user_sentiment": "Neutral",
                    "custom_analysis_data": {"outcome": body.outcome},
                },
            },
        },
    ]
    call = None
    for payload in events:
        ev = provider.normalize_event(payload)
        call, _ = apply_event(db, "mock", "mock:platform", ev, is_mock=True)
    db.commit()
    assert call is not None
    return {"call_id": str(call.id), "is_mock": True, "note": "Simulated conversation; no telephony was used."}
