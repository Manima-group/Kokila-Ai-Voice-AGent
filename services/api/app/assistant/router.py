"""Assistant sessions (mute controls, interruption, resume), conversations and turns (§23.1a, §24.3, §27.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.assistant.service import message_out, run_turn
from app.core.config import get_settings
from app.core.deps import Tenant, TenantContext
from app.core.errors import Conflict, KokilaError, NotFound
from app.domain.capabilities import CapabilityKey
from app.domain.constants import ErrorCode, EventType, Permission, SessionState
from app.identity.service import resolve_identity, system_prompt
from app.models import AssistantSession, Conversation, Message, OutboxEvent
from app.providers import media

router = APIRouter(prefix="/v1", tags=["assistant"])

Channel = Literal["web_voice", "web_text", "embed"]


class SessionOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    channel: str
    locale: str
    state: str
    generation: int
    last_sequence: int
    mic_muted: bool
    speaker_muted: bool
    revision: int
    policy_revision: int
    expires_at: datetime
    device_id: str


def _sout(s: AssistantSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        conversation_id=s.conversation_id,
        channel=s.channel,
        locale=s.locale,
        state=s.state,
        generation=s.generation,
        last_sequence=s.last_sequence,
        mic_muted=s.mic_muted,
        speaker_muted=s.speaker_muted,
        revision=s.revision,
        policy_revision=s.policy_revision,
        expires_at=s.expires_at,
        device_id=s.device_id,
    )


class SessionCreateIn(BaseModel):
    channel: Channel = "web_voice"
    locale: Annotated[str, Field(pattern=r"^(auto|te-IN|hi-IN|en-IN|en-US|en-GB)$")] = "auto"
    conversation_id: uuid.UUID | None = None
    device_id: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


async def _new_conversation(ctx: TenantContext, channel: str, language: str = "auto") -> Conversation:
    conv = Conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, channel=channel, language=language)
    ctx.db.add(conv)
    await ctx.db.flush()
    return conv


@router.post("/assistant/sessions", status_code=201, response_model=SessionOut, operation_id="sessions_create")
async def create_session(body: SessionCreateIn, ctx: Tenant) -> SessionOut:
    ctx.require(Permission.ASSISTANT_USE)
    ctx.require_capability(
        CapabilityKey.ASSISTANT_VOICE if body.channel == "web_voice" else CapabilityKey.ASSISTANT_TEXT
    )
    if body.conversation_id:
        conv = await ctx.db.scalar(
            select(Conversation).where(Conversation.id == body.conversation_id, Conversation.user_id == ctx.user_id)
        )
        if conv is None:
            raise NotFound("conversation not found")
    else:
        conv = await _new_conversation(ctx, body.channel, body.locale)
    s = AssistantSession(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conv.id,
        device_id=body.device_id,
        channel=body.channel,
        locale=body.locale,
        state=SessionState.IDLE.value,
        mic_muted=True,
        speaker_muted=True,
        policy_revision=ctx.policy.revision,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
    )
    ctx.db.add(s)
    await ctx.db.flush()
    return _sout(s)


async def _session(ctx: TenantContext, sid: uuid.UUID, lock: bool = True) -> AssistantSession:
    stmt = select(AssistantSession).where(AssistantSession.id == sid, AssistantSession.user_id == ctx.user_id)
    s = await ctx.db.scalar(stmt.with_for_update() if lock else stmt)
    if s is None:
        raise NotFound("session not found")
    if s.state == SessionState.ENDED:
        raise Conflict("session has ended")
    return s


@router.get("/assistant/sessions/{session_id}", response_model=SessionOut, operation_id="sessions_get")
async def get_session(session_id: uuid.UUID, ctx: Tenant) -> SessionOut:
    stmt = select(AssistantSession).where(AssistantSession.id == session_id, AssistantSession.user_id == ctx.user_id)
    s = await ctx.db.scalar(stmt)
    if s is None:
        raise NotFound("session not found")
    return _sout(s)


class ControlsIn(BaseModel):
    mic_muted: bool | None = None
    speaker_muted: bool | None = None
    expected_revision: int
    device_id: Annotated[str, Field(min_length=8, max_length=64)]


@router.post("/assistant/sessions/{session_id}/controls", response_model=SessionOut, operation_id="sessions_controls")
async def set_controls(session_id: uuid.UUID, body: ControlsIn, ctx: Tenant) -> SessionOut:
    """Server-authoritative mute state (KOK-14-MUTE). Only an explicit user request on the active device
    can unmute. Speaker mute discards queued speech by advancing the generation; it never cancels tool work."""
    s = await _session(ctx, session_id)
    if s.revision != body.expected_revision:
        raise Conflict(
            "controls changed on another device",
            code=ErrorCode.REVISION_CONFLICT,
            details={"current_revision": s.revision},
        )
    unmuting = (body.mic_muted is False and s.mic_muted) or (body.speaker_muted is False and s.speaker_muted)
    if unmuting and body.device_id != s.device_id:
        raise KokilaError("unmute must be performed on the active device", code=ErrorCode.FORBIDDEN, status_code=403)
    if body.mic_muted is False:
        ctx.require_capability(CapabilityKey.ASSISTANT_VOICE)
    if body.mic_muted is not None:
        s.mic_muted = body.mic_muted
        if body.mic_muted and s.state == SessionState.LISTENING:
            s.state = SessionState.IDLE.value
    if body.speaker_muted is not None:
        if body.speaker_muted and not s.speaker_muted:
            s.generation += 1  # invalidate queued/streaming speech
            if s.state == SessionState.SPEAKING:
                s.state = SessionState.IDLE.value
        s.speaker_muted = body.speaker_muted
    s.revision += 1
    ctx.db.add(
        OutboxEvent(
            tenant_id=ctx.tenant_id,
            event_type=EventType.SESSION_CONTROLS_CHANGED,
            payload={
                "session_id": str(s.id),
                "mic_muted": s.mic_muted,
                "speaker_muted": s.speaker_muted,
                "revision": s.revision,
            },
        )
    )
    await ctx.db.flush()
    return _sout(s)


class StateIn(BaseModel):
    state: Literal["idle", "listening"]
    expected_generation: int


@router.post("/assistant/sessions/{session_id}/state", response_model=SessionOut, operation_id="sessions_state")
async def set_state(session_id: uuid.UUID, body: StateIn, ctx: Tenant) -> SessionOut:
    s = await _session(ctx, session_id)
    if body.state == "listening" and s.mic_muted:
        raise Conflict("microphone is muted")
    if body.expected_generation != s.generation:
        raise Conflict("stale generation", details={"current_generation": s.generation})
    s.state = body.state
    s.revision += 1
    await ctx.db.flush()
    return _sout(s)


class InterruptIn(BaseModel):
    expected_generation: int
    message_id: uuid.UUID | None = None
    played_chars: Annotated[int | None, Field(ge=0)] = None


@router.post("/assistant/sessions/{session_id}/interrupt", response_model=SessionOut, operation_id="sessions_interrupt")
async def interrupt(session_id: uuid.UUID, body: InterruptIn, ctx: Tenant) -> SessionOut:
    """Barge-in: cancel playback/generation and record what was actually heard. Committed actions stand."""
    s = await _session(ctx, session_id)
    if body.expected_generation != s.generation:
        raise Conflict("stale generation", details={"current_generation": s.generation})
    s.generation += 1
    s.state = SessionState.IDLE.value if s.mic_muted else SessionState.LISTENING.value
    s.revision += 1
    if body.message_id is not None:
        m = await ctx.db.scalar(
            select(Message).where(
                Message.id == body.message_id, Message.conversation_id == s.conversation_id, Message.role == "assistant"
            )
        )
        if m is not None and m.status == "final":
            m.status = "interrupted"
            m.played_chars = min(body.played_chars or 0, len(m.content))
    await ctx.db.flush()
    return _sout(s)


class ResumeIn(BaseModel):
    last_sequence: Annotated[int, Field(ge=0)]
    device_id: Annotated[str, Field(min_length=8, max_length=64)]


@router.post("/assistant/sessions/{session_id}/resume", operation_id="sessions_resume")
async def resume(session_id: uuid.UUID, body: ResumeIn, ctx: Tenant) -> dict:
    """Reconnect: returns messages after last_sequence; never replays mutations; never unmutes.
    A different device takes over muted and must be explicitly activated (§23.3)."""
    s = await _session(ctx, session_id)
    if s.expires_at <= datetime.now(UTC):
        raise Conflict("session expired")
    if body.device_id != s.device_id:
        s.device_id, s.mic_muted = body.device_id, True
        s.generation += 1
    s.state = SessionState.IDLE.value
    s.policy_revision = ctx.policy.revision
    s.last_sequence = max(s.last_sequence, body.last_sequence)
    s.revision += 1
    rows = (
        await ctx.db.scalars(
            select(Message)
            .where(Message.conversation_id == s.conversation_id, Message.sequence > body.last_sequence)
            .order_by(Message.sequence)
            .limit(200)
        )
    ).all()
    await ctx.db.flush()
    return {"session": _sout(s), "messages": [message_out(m) for m in rows], "capabilities": ctx.policy.enabled_keys()}


@router.post("/assistant/sessions/{session_id}/end", response_model=SessionOut, operation_id="sessions_end")
async def end_session(session_id: uuid.UUID, ctx: Tenant) -> SessionOut:
    s = await _session(ctx, session_id)
    s.state, s.mic_muted, s.ended_at = SessionState.ENDED.value, True, datetime.now(UTC)
    s.generation += 1
    s.revision += 1
    await ctx.db.flush()
    return _sout(s)


@router.post("/assistant/sessions/{session_id}/media-token", operation_id="sessions_media_token")
async def media_token(session_id: uuid.UUID, ctx: Tenant) -> dict:
    ctx.require_capability(CapabilityKey.ASSISTANT_VOICE)
    s = await _session(ctx, session_id, lock=False)
    return media.livekit_token(
        session_id=s.id, user_id=ctx.user_id, display_name=ctx.user.display_name, can_publish=not s.mic_muted
    )


@router.post("/assistant/sessions/{session_id}/realtime-token", operation_id="sessions_realtime_token")
async def realtime_token(session_id: uuid.UUID, ctx: Tenant) -> dict:
    ctx.require_capability(CapabilityKey.ASSISTANT_VOICE)
    s = await _session(ctx, session_id, lock=False)
    if s.mic_muted:
        raise Conflict("microphone is muted; unmute explicitly before starting realtime audio")
    identity = await resolve_identity(ctx.db, ctx.policy, ctx.tenant_id, ctx.user_id)
    prompt = system_prompt(identity, user_name=ctx.user.display_name, locale_hint=s.locale, memory=[], tool_names=[])
    locale = s.locale
    await ctx.release()
    out = await media.openai_realtime_client_secret(locale=locale, instructions=prompt)
    await ctx.reattach()
    return out


# --- conversations ------------------------------------------------------------------------------------


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    channel: str
    language: str
    status: str
    created_at: datetime
    updated_at: datetime


def _cout(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        title=c.title,
        channel=c.channel,
        language=c.language,
        status=c.status,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/conversations", operation_id="conversations_list")
async def list_conversations(
    ctx: Tenant, limit: Annotated[int, Query(ge=1, le=100)] = 30, cursor: str | None = None
) -> dict:
    ctx.require_capability(CapabilityKey.ASSISTANT_TEXT)
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == ctx.user_id, Conversation.status == "active")
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    if cursor:
        ts, cid = cursor.split("|", 1)
        c_at = datetime.fromisoformat(ts)
        stmt = stmt.where(
            (Conversation.updated_at < c_at) | ((Conversation.updated_at == c_at) & (Conversation.id < uuid.UUID(cid)))
        )
    rows = (await ctx.db.scalars(stmt.limit(limit + 1))).all()
    nxt = f"{rows[limit - 1].updated_at.isoformat()}|{rows[limit - 1].id}" if len(rows) > limit else None
    return {"items": [_cout(c) for c in rows[:limit]], "next_cursor": nxt}


class ConversationIn(BaseModel):
    channel: Channel = "web_text"
    language: Annotated[str, Field(pattern=r"^(auto|te-IN|hi-IN|en-IN|en-US|en-GB)$")] = "auto"


@router.post("/conversations", status_code=201, response_model=ConversationOut, operation_id="conversations_create")
async def create_conversation(body: ConversationIn, ctx: Tenant) -> ConversationOut:
    ctx.require_capability(CapabilityKey.ASSISTANT_TEXT)
    conv = await _new_conversation(ctx, body.channel, body.language)
    await ctx.db.refresh(conv)
    return _cout(conv)


@router.get("/conversations/{conversation_id}/messages", operation_id="conversations_messages")
async def list_messages(
    conversation_id: uuid.UUID,
    ctx: Tenant,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict:
    ctx.require_capability(CapabilityKey.ASSISTANT_TEXT)
    conv = await ctx.db.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == ctx.user_id)
    )
    if conv is None:
        raise NotFound("conversation not found")
    rows = (
        await ctx.db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.sequence > after_sequence)
            .order_by(Message.sequence)
            .limit(limit + 1)
        )
    ).all()
    nxt = str(rows[limit - 1].sequence) if len(rows) > limit else None
    return {"items": [message_out(m) for m in rows[:limit]], "next_cursor": nxt}


@router.post(
    "/conversations/{conversation_id}/archive", response_model=ConversationOut, operation_id="conversations_archive"
)
async def archive_conversation(conversation_id: uuid.UUID, ctx: Tenant) -> ConversationOut:
    conv = await ctx.db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == ctx.user_id)
        .with_for_update()
    )
    if conv is None:
        raise NotFound("conversation not found")
    conv.status = "archived"
    conv.revision += 1
    await ctx.db.flush()
    await ctx.db.refresh(conv)
    return _cout(conv)


class TurnIn(BaseModel):
    text: Annotated[str, Field(min_length=1)]
    session_id: uuid.UUID | None = None
    generation: int | None = None
    language: Annotated[str | None, Field(pattern=r"^(auto|te-IN|hi-IN|en-IN|en-US|en-GB)$")] = None
    input_mode: Literal["voice", "text"] = "text"


@router.post("/conversations/{conversation_id}/turns", operation_id="conversations_turn")
async def create_turn(
    conversation_id: uuid.UUID,
    body: TurnIn,
    ctx: Tenant,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
) -> dict:
    text = body.text.strip()
    if not text or len(text) > get_settings().max_turn_chars:
        raise KokilaError("turn text is empty or too long", status_code=422)
    res = await run_turn(
        ctx,
        conversation_id=conversation_id,
        text=text,
        client_turn_id=idempotency_key,
        session_id=body.session_id,
        generation=body.generation,
        language=body.language,
    )
    return {
        "turn_id": str(res.turn_id),
        "state": res.state,
        "language": res.language,
        "stale": res.stale,
        "replayed": res.replayed,
        "user_message": message_out(res.user_message),
        "assistant_message": message_out(res.assistant_message),
        "tool_runs": res.tool_runs,
        "speak": None if res.stale or res.assistant_message is None else res.assistant_message.content,
    }
