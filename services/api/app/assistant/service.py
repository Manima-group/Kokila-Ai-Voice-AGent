"""Conversation turns: persistence, retrieval, reasoning, tool brokering and truthful outcomes (§4, §14.1)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.assistant.language import detect_script_language, next_language
from app.core.config import get_settings
from app.core.deps import TenantContext
from app.core.errors import Conflict, NotFound
from app.domain.capabilities import CapabilityKey
from app.domain.constants import ErrorCode, Permission, SessionState, SideEffect, ToolRunStatus
from app.identity.service import resolve_identity, system_prompt
from app.memory.service import search_memory
from app.models import ApprovalRequest, AssistantSession, Conversation, Message, ToolRun
from app.platform.entitlements import consume_quota
from app.providers.reasoning import ChatMessage, ToolCallRequest, ToolSpec, get_reasoning_router
from app.tools.registry import TOOLS
from app.tools.service import available_tools, request_run, run_out

MAX_TOOL_ROUNDS = 2


@dataclass(slots=True)
class TurnResult:
    turn_id: uuid.UUID
    user_message: Message
    assistant_message: Message | None
    tool_runs: list[dict[str, Any]] = field(default_factory=list)
    state: str = SessionState.IDLE.value
    language: str = "auto"
    stale: bool = False
    replayed: bool = False


async def _conversation(ctx: TenantContext, conversation_id: uuid.UUID, lock: bool = False) -> Conversation:
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == ctx.user_id)
    conv = await ctx.db.scalar(stmt.with_for_update() if lock else stmt)
    if conv is None:
        raise NotFound("conversation not found")
    return conv


async def append_message(
    ctx: TenantContext,
    conversation_id: uuid.UUID,
    *,
    turn_id: uuid.UUID,
    role: str,
    content: str,
    language: str | None = None,
    client_turn_id: str | None = None,
    status: str = "final",
    provider: str | None = None,
    model: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Message:
    conv = await _conversation(ctx, conversation_id, lock=True)  # serializes sequence allocation
    msg = Message(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conv.id,
        turn_id=turn_id,
        client_turn_id=client_turn_id,
        sequence=conv.next_sequence,
        role=role,
        content=content,
        language=language,
        status=status,
        provider=provider,
        model=model,
        meta=meta or {},
    )
    conv.next_sequence += 1
    if role == "user" and conv.title == "New conversation":
        conv.title = content[:80]
    ctx.db.add(msg)
    await ctx.db.flush()
    return msg


async def _history(ctx: TenantContext, conv_id: uuid.UUID) -> tuple[list[ChatMessage], list[str]]:
    limit = get_settings().max_history_messages
    rows = list(
        reversed(
            (
                await ctx.db.scalars(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.sequence.desc())
                    .limit(limit)
                )
            ).all()
        )
    )
    msgs: list[ChatMessage] = []
    tool_notes: list[str] = []
    for m in rows:
        if m.role == "tool":
            tool_notes.append(f"{m.meta.get('tool_key')}: {m.content[:300]}")
            continue
        if m.role not in ("user", "assistant") or m.status == "failed":
            continue
        text = m.content
        if m.role == "assistant" and m.status == "interrupted":
            # Only what was actually heard becomes conversation state (§4 step 6).
            text = text[: m.played_chars or 0]
            if not text:
                continue
            text += " …(interrupted)"
        if msgs and msgs[-1].role == m.role:
            msgs[-1].content += "\n" + text
        else:
            msgs.append(ChatMessage(role=m.role, content=text))
    while msgs and msgs[0].role != "user":
        msgs.pop(0)
    return msgs, tool_notes[-5:]


async def _session(ctx: TenantContext, session_id: uuid.UUID, lock: bool = True) -> AssistantSession:
    stmt = select(AssistantSession).where(AssistantSession.id == session_id, AssistantSession.user_id == ctx.user_id)
    s = await ctx.db.scalar(stmt.with_for_update() if lock else stmt)
    if s is None:
        raise NotFound("session not found")
    return s


async def _replay(ctx: TenantContext, user_msg: Message) -> TurnResult:
    reply = await ctx.db.scalar(
        select(Message).where(
            Message.conversation_id == user_msg.conversation_id,
            Message.turn_id == user_msg.turn_id,
            Message.role == "assistant",
        )
    )
    runs = (
        await ctx.db.scalars(select(ToolRun).where(ToolRun.idempotency_key.like(f"turn:{user_msg.turn_id}:%")))
    ).all()
    out = []
    for r in runs:
        ap = await ctx.db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == r.id))
        out.append(run_out(r, ap))
    return TurnResult(
        turn_id=user_msg.turn_id,
        user_message=user_msg,
        assistant_message=reply,
        tool_runs=out,
        language=user_msg.language or "auto",
        replayed=True,
    )


async def run_turn(
    ctx: TenantContext,
    *,
    conversation_id: uuid.UUID,
    text: str,
    client_turn_id: str,
    session_id: uuid.UUID | None,
    generation: int | None,
    language: str | None,
) -> TurnResult:
    ctx.require(Permission.ASSISTANT_USE)
    ctx.require_capability(CapabilityKey.ASSISTANT_TEXT)
    conv = await _conversation(ctx, conversation_id, lock=True)
    prior = await ctx.db.scalar(
        select(Message).where(Message.conversation_id == conv.id, Message.client_turn_id == client_turn_id)
    )
    if prior is not None:
        return await _replay(ctx, prior)  # reconnect/retry never re-executes actions

    session: AssistantSession | None = None
    if session_id is not None:
        session = await _session(ctx, session_id)
        if session.state == SessionState.ENDED or session.conversation_id != conv.id:
            raise Conflict("session is not active for this conversation")
        if generation is not None and generation != session.generation:
            raise Conflict(
                "stale generation", code=ErrorCode.STATE_CONFLICT, details={"current_generation": session.generation}
            )
        session.state = SessionState.THINKING.value
        generation = session.generation

    turn_id = uuid.uuid4()
    await consume_quota(
        ctx.db,
        ctx.policy,
        capability=CapabilityKey.ASSISTANT_TEXT,
        user_id=ctx.user_id,
        source_event_id=f"turn:{turn_id}",
    )
    detected = detect_script_language(text)
    recent = (
        await ctx.db.scalars(
            select(Message.language)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.sequence.desc())
            .limit(1)
        )
    ).all()
    conv.language = next_language(conv.language, [*reversed(recent), detected], language)
    user_msg = await append_message(
        ctx,
        conv.id,
        turn_id=turn_id,
        role="user",
        content=text,
        language=detected or conv.language,
        client_turn_id=client_turn_id,
    )

    identity = await resolve_identity(ctx.db, ctx.policy, ctx.tenant_id, ctx.user_id)
    memory: list[str] = []
    if ctx.policy.allows(CapabilityKey.ASSISTANT_MEMORY):
        memory = [m.content for m in await search_memory(ctx, text, 6)]
    tools = available_tools(ctx)
    history, tool_notes = await _history(ctx, conv.id)
    system = system_prompt(
        identity,
        user_name=ctx.user.display_name,
        locale_hint=conv.language,
        memory=memory,
        tool_names=[t.key for t in tools],
    )
    if tool_notes:
        system += "\n<recent_tool_results>\n" + "\n".join(tool_notes) + "\n</recent_tool_results>"
    specs = [ToolSpec(t.key, t.description, t.json_schema()) for t in tools]
    conv_id, user_msg_id = conv.id, user_msg.id

    runs_out: list[dict[str, Any]] = []
    awaiting = False
    side_effect_done = False
    reply_text = ""
    provider = model = None
    messages = history
    for _round in range(MAX_TOOL_ROUNDS + 1):
        await ctx.release()  # no transaction is held across the provider call
        result = await get_reasoning_router().complete(
            system=system, messages=messages, tools=specs, allow_failover=not side_effect_done
        )
        await ctx.reattach()
        provider, model = result.provider, result.model
        reply_text = result.text
        if not result.tool_calls or _round == MAX_TOOL_ROUNDS:
            break
        allowed = {t.key for t in available_tools(ctx)}  # re-evaluated after reattach
        tool_msgs: list[ChatMessage] = []
        for call in result.tool_calls[:3]:
            out = await _broker_call(ctx, call, allowed, conv_id, turn_id)
            runs_out.append(out)
            if out["status"] == ToolRunStatus.AWAITING_APPROVAL:
                awaiting = True
            elif out["status"] == ToolRunStatus.SUCCEEDED and out["side_effect"] != SideEffect.READ:
                side_effect_done = True
            await append_message(
                ctx,
                conv_id,
                turn_id=turn_id,
                role="tool",
                content=json.dumps({"status": out["status"], "result": out["result"]}, ensure_ascii=False)[:2000],
                meta={"tool_key": out["tool_key"], "run_id": out["run_id"], "call_id": call.id},
            )
            tool_msgs.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=json.dumps(
                        {"status": out["status"], "result": out["result"], "error": out["error_code"]},
                        ensure_ascii=False,
                    ),
                )
            )
        if awaiting:
            pending = [
                r["approval"]["summary"]
                for r in runs_out
                if r.get("approval") and r["status"] == ToolRunStatus.AWAITING_APPROVAL
            ]
            reply_text = (
                (reply_text + "\n" if reply_text else "")
                + "I need your approval before I do this: "
                + "; ".join(pending)
            )
            break
        messages = [
            *messages,
            ChatMessage(role="assistant", content=result.text, tool_calls=result.tool_calls),
            *tool_msgs,
        ]

    status, stale = "final", False
    state = SessionState.AWAITING_APPROVAL if awaiting else SessionState.SPEAKING
    if session_id is not None:
        session = await _session(ctx, session_id)
        if session.generation != generation:
            stale, status = True, "interrupted"  # user barged in while we were thinking: discard audio
            state = SessionState(session.state)
        else:
            if state is SessionState.SPEAKING and session.speaker_muted:
                state = SessionState.IDLE
            session.state = state.value
    reply = await append_message(
        ctx,
        conv_id,
        turn_id=turn_id,
        role="assistant",
        content=reply_text or "(no response)",
        language=conv.language,
        status=status,
        provider=provider,
        model=model,
        meta={"reply_to": str(user_msg_id), "dev_mock": provider == "dev_mock"},
    )
    if stale:
        reply.played_chars = 0
    user_msg = await ctx.db.get(Message, user_msg_id)  # type: ignore[assignment]
    return TurnResult(
        turn_id=turn_id,
        user_message=user_msg,
        assistant_message=reply,
        tool_runs=runs_out,
        state=state.value,
        language=conv.language,
        stale=stale,
    )


async def _broker_call(
    ctx: TenantContext, call: ToolCallRequest, allowed: set[str], conv_id: uuid.UUID, turn_id: uuid.UUID
) -> dict[str, Any]:
    key = f"turn:{turn_id}:{call.id}"[:128]
    if call.key not in allowed or call.key not in TOOLS:
        # The model asked for something not discoverable: record nothing executable, report truthfully.
        return {
            "run_id": None,
            "tool_key": call.key,
            "status": ToolRunStatus.FAILED.value,
            "side_effect": SideEffect.READ.value,
            "args": {},
            "args_hash": None,
            "result": {"message": "tool not available"},
            "error_code": "tool_unavailable",
            "approval": None,
            "revision": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }
    run, approval = await request_run(
        ctx, tool_key=call.key, args=call.arguments, idempotency_key=key, conversation_id=conv_id
    )
    return run_out(run, approval)


def message_out(m: Message | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "id": str(m.id),
        "turn_id": str(m.turn_id),
        "sequence": m.sequence,
        "role": m.role,
        "content": m.content,
        "language": m.language,
        "status": m.status,
        "played_chars": m.played_chars,
        "provider": m.provider,
        "model": m.model,
        "dev_mock": bool(m.meta.get("dev_mock")),
        "tool_key": m.meta.get("tool_key"),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
