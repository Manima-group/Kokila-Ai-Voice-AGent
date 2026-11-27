import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.llm import configured_provider
from app.assistant.models import AssistantAction, AssistantConversation, AssistantMessage, MemoryItem, Notification, Reminder
from app.assistant.service import converse, execute_action, prefs
from app.audit.service import audit_ctx
from app.auth.deps import TenantContext, require_capability, tenant_context
from app.core.config import get_settings
from app.core.errors import AppError, Forbidden, NotFound, ServiceUnavailable
from app.db.session import get_db
from app.platform.entitlements import evaluate
from app.platform.entitlements import require as require_cap
from app.platform.registry import PRODUCT_BUSINESS_ASSISTANT

router = APIRouter(prefix="/assistant", tags=["assistant"], dependencies=[Depends(require_capability(PRODUCT_BUSINESS_ASSISTANT, "assistant.text"))])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
LANGS = ("auto", "en-IN", "hi-IN", "te-IN")


class ConversationIn(BaseModel):
    mode: str = Field(pattern="^(business|personal)$")


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, pattern="^(auto|en-IN|hi-IN|te-IN)$")


class PrefsIn(BaseModel):
    assistant_name: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[\w .'\-ऀ-ॿఀ-౿]+$")
    language: str | None = Field(default=None, pattern="^(auto|en-IN|hi-IN|te-IN)$")
    voice_name: str | None = Field(default=None, max_length=120)
    wake_phrase: str | None = Field(default=None, max_length=60)
    response_length: str | None = Field(default=None, pattern="^(short|medium|detailed)$")


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class DecisionIn(BaseModel):
    approve: bool
    args_hash: str


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime


def _conv(db: Session, cid: uuid.UUID, ctx: TenantContext) -> AssistantConversation:
    c = db.get(AssistantConversation, cid)
    if c is None or c.tenant_id != ctx.tenant_id or c.user_id != ctx.user.id:
        raise NotFound("Conversation not found")
    return c


def _check_mode(db: Session, ctx: TenantContext, mode: str) -> None:
    if mode == "personal":
        require_cap(db, ctx.tenant_id, "assistant.personal")
    elif not ctx.can("analytics:read"):
        raise Forbidden("Business mode requires analytics access")


def _msg(m: AssistantMessage) -> dict:
    return {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "artifacts": m.artifacts,
        "provider": m.provider,
        "model": m.model,
        "language": m.language,
        "created_at": m.created_at.isoformat(),
    }


@router.get("/config")
def config(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    p = configured_provider()
    caps = {k: s.effective for k, s in evaluate(db, ctx.tenant_id).items()}
    pr = prefs(db, ctx.tenant_id, ctx.user.id)
    db.commit()
    return {
        "llm": {"configured": p is not None, "provider": p.name if p else None, "model": p.model if p else None},
        "voice": {
            "engine": "browser_speech",
            "note": "Uses the browser's speech recognition and synthesis; language quality depends on the browser.",
            "realtime": "not_configured",
        },
        "research": bool(get_settings().brave_api_key) and caps.get("assistant.research", False),
        "modes": {"business": True, "personal": caps.get("assistant.personal", False)},
        "memory": caps.get("assistant.memory", False),
        "preferences": {
            "assistant_name": pr.assistant_name,
            "language": pr.language,
            "voice_name": pr.voice_name,
            "wake_phrase": pr.wake_phrase,
            "response_length": pr.response_length,
        },
        "custom_name_allowed": caps.get("assistant.identity", False),
    }


@router.patch("/preferences")
def update_prefs(body: PrefsIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    pr = prefs(db, ctx.tenant_id, ctx.user.id)
    data = body.model_dump(exclude_unset=True)
    if "assistant_name" in data or "wake_phrase" in data:
        require_cap(db, ctx.tenant_id, "assistant.identity")
    for k, v in data.items():
        setattr(pr, k, v)
    db.commit()
    return {"status": "updated"}


@router.get("/conversations")
def conversations(
    mode: str = Query(pattern="^(business|personal)$"), ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)
) -> list[dict]:
    _check_mode(db, ctx, mode)
    rows = db.scalars(
        select(AssistantConversation)
        .where(
            AssistantConversation.tenant_id == ctx.tenant_id,
            AssistantConversation.user_id == ctx.user.id,
            AssistantConversation.mode == mode,
            AssistantConversation.status == "active",
        )
        .order_by(AssistantConversation.updated_at.desc())
        .limit(100)
    ).all()
    return [{"id": str(c.id), "title": c.title, "mode": c.mode, "updated_at": c.updated_at.isoformat()} for c in rows]


@router.post("/conversations", status_code=201)
def new_conversation(body: ConversationIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    _check_mode(db, ctx, body.mode)
    c = AssistantConversation(tenant_id=ctx.tenant_id, user_id=ctx.user.id, mode=body.mode, title="New conversation", status="active")
    db.add(c)
    db.commit()
    return {"id": str(c.id), "title": c.title, "mode": c.mode, "updated_at": c.updated_at.isoformat()}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: uuid.UUID, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> None:
    db.delete(_conv(db, cid, ctx))
    db.commit()


@router.get("/conversations/{cid}/messages")
def messages(cid: uuid.UUID, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    c = _conv(db, cid, ctx)
    return [_msg(m) for m in db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == c.id).order_by(AssistantMessage.created_at))]


@router.post("/conversations/{cid}/messages")
def send(cid: uuid.UUID, body: MessageIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    c = _conv(db, cid, ctx)
    _check_mode(db, ctx, c.mode)
    provider = configured_provider()
    if provider is None:
        raise ServiceUnavailable(
            "The assistant's AI model is not configured (LLM_PROVIDER, LLM_MODEL and API key). Quick reports still work.", code="llm_not_configured"
        )
    reply = converse(db, provider, c, body.content, body.language)
    db.commit()
    return _msg(reply)


# ---- Memory (personal, user-controlled) ---------------------------------------------------------------------------
def _mem_guard(db: Session, ctx: TenantContext) -> None:
    require_cap(db, ctx.tenant_id, "assistant.personal")
    require_cap(db, ctx.tenant_id, "assistant.memory")


@router.get("/memory")
def memory(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    _mem_guard(db, ctx)
    rows = db.scalars(select(MemoryItem).where(MemoryItem.tenant_id == ctx.tenant_id, MemoryItem.user_id == ctx.user.id).order_by(MemoryItem.created_at.desc()))
    return [{"id": str(m.id), "content": m.content, "status": m.status, "created_at": m.created_at.isoformat()} for m in rows]


@router.post("/memory", status_code=201)
def add_memory(body: MemoryIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    _mem_guard(db, ctx)
    m = MemoryItem(tenant_id=ctx.tenant_id, user_id=ctx.user.id, scope="personal", content=body.content, status="active")
    db.add(m)
    db.commit()
    return {"id": str(m.id), "status": m.status}


def _own_memory(db: Session, mid: uuid.UUID, ctx: TenantContext) -> MemoryItem:
    m = db.get(MemoryItem, mid)
    if m is None or m.tenant_id != ctx.tenant_id or m.user_id != ctx.user.id:
        raise NotFound("Memory item not found")
    return m


@router.post("/memory/{mid}/approve")
def approve_memory(mid: uuid.UUID, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    _mem_guard(db, ctx)
    m = _own_memory(db, mid, ctx)
    m.status = "active"
    db.commit()
    return {"id": str(m.id), "status": m.status}


@router.delete("/memory/{mid}", status_code=204)
def delete_memory(mid: uuid.UUID, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> None:
    _mem_guard(db, ctx)
    db.delete(_own_memory(db, mid, ctx))
    db.commit()


# ---- Approvals ----------------------------------------------------------------------------------------------------
@router.get("/actions")
def actions(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(AssistantAction)
        .where(AssistantAction.tenant_id == ctx.tenant_id, AssistantAction.user_id == ctx.user.id)
        .order_by(AssistantAction.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": str(a.id),
            "tool": a.tool_key,
            "summary": a.summary,
            "args": a.args,
            "args_hash": a.args_hash,
            "status": a.status,
            "result": a.result,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/actions/{aid}/decision")
def decide(aid: uuid.UUID, body: DecisionIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    a = db.scalar(select(AssistantAction).where(AssistantAction.id == aid).with_for_update())
    if a is None or a.tenant_id != ctx.tenant_id or a.user_id != ctx.user.id:
        raise NotFound("Action not found")
    if a.status != "pending":
        raise AppError(f"Action already {a.status}", code="invalid_state", status_code=409)
    expected = hashlib.sha256(json.dumps({"tool": a.tool_key, "args": a.args}, sort_keys=True).encode()).hexdigest()
    if body.args_hash != a.args_hash or a.args_hash != expected:
        raise AppError("Action details changed; review again", code="args_mismatch", status_code=409)
    a.decided_at = datetime.now(UTC)
    if not body.approve:
        a.status = "rejected"
    else:
        if a.tool_key == "create_follow_up_task" and not ctx.can("leads:write"):
            raise Forbidden("You are not allowed to create follow-up tasks")
        try:
            a.result, a.status = execute_action(db, a), "executed"
        except AppError as exc:
            a.result, a.status = {"error": exc.message}, "failed"
    audit_ctx(db, ctx, f"assistant.action_{a.status}", "assistant_action", a.id, tool=a.tool_key)
    db.commit()
    return {"id": str(a.id), "status": a.status, "result": a.result}


# ---- Reminders ----------------------------------------------------------------------------------------------------
@router.get("/reminders")
def reminders(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Reminder).where(Reminder.tenant_id == ctx.tenant_id, Reminder.user_id == ctx.user.id).order_by(Reminder.due_at.desc()).limit(100))
    return [{"id": str(r.id), "text": r.text, "due_at": r.due_at.isoformat(), "status": r.status} for r in rows]


@router.post("/reminders", status_code=201)
def add_reminder(body: ReminderIn, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    require_cap(db, ctx.tenant_id, "assistant.personal")
    if body.due_at.tzinfo is None or body.due_at <= datetime.now(UTC):
        raise AppError("due_at must be a future time with timezone", code="invalid_time", status_code=422)
    r = Reminder(tenant_id=ctx.tenant_id, user_id=ctx.user.id, text=body.text, due_at=body.due_at, status="scheduled")
    db.add(r)
    db.commit()
    return {"id": str(r.id), "status": r.status}


@router.post("/reminders/{rid}/cancel")
def cancel_reminder(rid: uuid.UUID, ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    r = db.get(Reminder, rid)
    if r is None or r.tenant_id != ctx.tenant_id or r.user_id != ctx.user.id:
        raise NotFound("Reminder not found")
    if r.status == "scheduled":
        r.status = "cancelled"
    db.commit()
    return {"id": str(r.id), "status": r.status}


# ---- Notifications (platform-wide, any member) --------------------------------------------------------------------
@notifications_router.get("")
def list_notifications(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(Notification)
        .where(Notification.tenant_id == ctx.tenant_id, (Notification.user_id == ctx.user.id) | (Notification.user_id.is_(None)))
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()
    return {
        "unread": sum(1 for n in rows if n.read_at is None),
        "items": [
            {
                "id": str(n.id),
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "read": n.read_at is not None,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


@notifications_router.post("/read-all")
def read_all(ctx: TenantContext = Depends(tenant_context), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    for n in db.scalars(
        select(Notification).where(Notification.tenant_id == ctx.tenant_id, Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
    ):
        n.read_at = now
    db.commit()
    return {"status": "ok"}
