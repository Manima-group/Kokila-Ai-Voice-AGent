"""Tool broker: validation, idempotency, approvals bound to exact args, cancellation, execution (§15, §24.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.core.audit import audit
from app.core.config import get_settings
from app.core.deps import TenantContext
from app.core.errors import Conflict, Forbidden, KokilaError, NotFound
from app.core.security import args_hash
from app.domain.constants import (
    TOOL_TERMINAL,
    TOOL_TRANSITIONS,
    ApprovalDecision,
    AuditAction,
    ErrorCode,
    EventType,
    ToolRunStatus,
)
from app.models import ApprovalRequest, MemoryItem, OutboxEvent, ToolRun
from app.tools.registry import TOOLS, ToolDef, tool_summary


def available_tools(ctx: TenantContext) -> list[ToolDef]:
    return [t for t in TOOLS.values() if ctx.policy.allows(t.capability) and t.permission in ctx.permissions]


def _transition(run: ToolRun, to: ToolRunStatus) -> None:
    cur = ToolRunStatus(run.status)
    if to not in TOOL_TRANSITIONS[cur]:
        raise Conflict(f"tool run cannot move from {cur} to {to}")
    run.status = to.value
    run.revision += 1


def _event(ctx: TenantContext, run: ToolRun) -> None:
    ctx.db.add(
        OutboxEvent(
            tenant_id=ctx.tenant_id,
            event_type=EventType.TOOL_RUN_CHANGED,
            payload={"run_id": str(run.id), "status": run.status, "revision": run.revision},
        )
    )


async def request_run(
    ctx: TenantContext, *, tool_key: str, args: dict[str, Any], idempotency_key: str, conversation_id: uuid.UUID | None
) -> tuple[ToolRun, ApprovalRequest | None]:
    tool = TOOLS.get(tool_key)
    # Disabled/unknown tools are reported identically: not discoverable, not executable.
    if tool is None or not ctx.policy.allows(tool.capability):
        raise KokilaError(
            f"tool {tool_key} is not available in this workspace", code=ErrorCode.CAPABILITY_DISABLED, status_code=403
        )
    ctx.require(tool.permission)
    digest = args_hash(args)
    existing = await ctx.db.scalar(
        select(ToolRun).where(ToolRun.tenant_id == ctx.tenant_id, ToolRun.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.args_hash != digest or existing.tool_key != tool_key or existing.requested_by != ctx.user_id:
            raise Conflict("idempotency key reused with different arguments", code=ErrorCode.IDEMPOTENCY_CONFLICT)
        approval = await ctx.db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == existing.id))
        return existing, approval

    run = ToolRun(
        tenant_id=ctx.tenant_id,
        requested_by=ctx.user_id,
        conversation_id=conversation_id,
        tool_key=tool.key,
        tool_version=tool.version,
        capability_key=tool.capability,
        side_effect=tool.side_effect.value,
        args=args,
        args_hash=digest,
        status=ToolRunStatus.REQUESTED.value,
        idempotency_key=idempotency_key,
        policy_revision=ctx.policy.revision,
    )
    ctx.db.add(run)
    await ctx.db.flush()
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.TOOL_RUN_REQUESTED,
        target_ref=f"tool_run:{run.id}",
        detail={"tool": tool.key, "args_hash": digest},
    )
    _transition(run, ToolRunStatus.VALIDATING)
    try:
        tool.args_model.model_validate(args)
    except ValidationError as exc:
        _transition(run, ToolRunStatus.FAILED)
        run.error_code = "invalid_arguments"
        run.result = {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}
        run.finished_at = datetime.now(UTC)
        _event(ctx, run)
        return run, None

    approval = None
    if tool.requires_approval:
        _transition(run, ToolRunStatus.AWAITING_APPROVAL)
        approval = ApprovalRequest(
            tenant_id=ctx.tenant_id,
            run_id=run.id,
            requested_by=ctx.user_id,
            args_hash=digest,
            summary=tool_summary(tool, args),
            expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().approval_ttl_s),
        )
        ctx.db.add(approval)
    else:
        _transition(run, ToolRunStatus.QUEUED)
        await _execute(ctx, run, tool)
    _event(ctx, run)
    await ctx.db.flush()
    return run, approval


async def decide(
    ctx: TenantContext, *, approval_id: uuid.UUID, approve: bool, expected_args_hash: str
) -> tuple[ToolRun, ApprovalRequest]:
    approval = await ctx.db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update())
    if approval is None:
        raise NotFound("approval not found")
    run = await ctx.db.scalar(select(ToolRun).where(ToolRun.id == approval.run_id).with_for_update())
    assert run is not None
    # Personal assistant actions are approved by the person who asked; a spoken/model "yes" is not approval.
    if approval.requested_by != ctx.user_id:
        raise Forbidden("only the requesting user can decide this approval")
    if approval.decision != ApprovalDecision.PENDING:
        raise Conflict("approval already decided", details={"decision": approval.decision})
    if approval.args_hash != expected_args_hash or run.args_hash != expected_args_hash:
        raise Conflict("approval does not match the requested action", code=ErrorCode.STATE_CONFLICT)
    now = datetime.now(UTC)
    if approval.expires_at <= now:
        approval.decision, approval.decided_at = ApprovalDecision.EXPIRED.value, now
        _transition(run, ToolRunStatus.CANCELLED)
        run.error_code, run.finished_at = "approval_expired", now
        _event(ctx, run)
        return run, approval
    approval.approver_id, approval.decided_at = ctx.user_id, now
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.APPROVAL_DECIDED,
        target_ref=f"tool_run:{run.id}",
        detail={"approved": approve, "args_hash": expected_args_hash},
    )
    if not approve:
        approval.decision = ApprovalDecision.DENIED.value
        _transition(run, ToolRunStatus.CANCELLED)
        run.error_code, run.finished_at = "approval_denied", now
        _event(ctx, run)
        return run, approval
    approval.decision = ApprovalDecision.APPROVED.value
    _transition(run, ToolRunStatus.QUEUED)
    # Re-evaluate entitlements immediately before the side effect (§25).
    await ctx.refresh_policy()
    tool = TOOLS[run.tool_key]
    if not ctx.policy.allows(tool.capability):
        _transition(run, ToolRunStatus.CANCELLED)
        run.error_code, run.finished_at = "capability_revoked", now
    else:
        await _execute(ctx, run, tool)
    _event(ctx, run)
    await ctx.db.flush()
    return run, approval


async def cancel(ctx: TenantContext, run_id: uuid.UUID) -> ToolRun:
    run = await ctx.db.scalar(select(ToolRun).where(ToolRun.id == run_id).with_for_update())
    if run is None or run.requested_by != ctx.user_id:
        raise NotFound("tool run not found")
    status = ToolRunStatus(run.status)
    if status in TOOL_TERMINAL or status in (ToolRunStatus.RUNNING, ToolRunStatus.UNKNOWN_OUTCOME):
        return run  # caller reports the actual state: already committed or still reconciling
    _transition(run, ToolRunStatus.CANCELLED)
    run.error_code, run.finished_at = "cancelled_by_user", datetime.now(UTC)
    approval = await ctx.db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id))
    if approval is not None and approval.decision == ApprovalDecision.PENDING:
        approval.decision, approval.decided_at = ApprovalDecision.DENIED.value, datetime.now(UTC)
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.TOOL_RUN_CANCELLED,
        target_ref=f"tool_run:{run.id}",
    )
    _event(ctx, run)
    return run


async def _execute(ctx: TenantContext, run: ToolRun, tool: ToolDef) -> None:
    _transition(run, ToolRunStatus.RUNNING)
    run.started_at = datetime.now(UTC)
    args = tool.args_model.model_validate(run.args)
    try:
        async with ctx.db.begin_nested():
            result = await _HANDLERS[tool.key](ctx, args, run)
    except KokilaError as exc:
        _transition(run, ToolRunStatus.FAILED)
        run.error_code, run.result = exc.code, {"message": exc.message}
    else:
        _transition(run, ToolRunStatus.SUCCEEDED)
        run.result = result
    run.finished_at = datetime.now(UTC)


async def _time_now(ctx: TenantContext, _args: Any, _run: ToolRun) -> dict[str, Any]:
    try:
        tz = ZoneInfo(ctx.user.timezone)
    except Exception:  # noqa: BLE001 - invalid stored tz falls back to IST
        tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    return {"iso": now.isoformat(), "timezone": str(tz), "weekday": now.strftime("%A")}


async def _memory_search(ctx: TenantContext, args: Any, _run: ToolRun) -> dict[str, Any]:
    from app.memory.service import search_memory

    items = await search_memory(ctx, args.query, args.limit)
    return {"items": [{"id": str(m.id), "content": m.content, "kind": m.kind} for m in items]}


async def _memory_save(ctx: TenantContext, args: Any, run: ToolRun) -> dict[str, Any]:
    item = MemoryItem(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kind=args.kind,
        scope="personal",
        content=args.content,
        confidence=1.0,
    )
    ctx.db.add(item)
    await ctx.db.flush()
    return {"memory_id": str(item.id), "content": item.content}


async def _memory_delete_matching(ctx: TenantContext, args: Any, _run: ToolRun) -> dict[str, Any]:
    q = func.plainto_tsquery("simple", args.query)
    res = await ctx.db.execute(
        delete(MemoryItem)
        .where(MemoryItem.user_id == ctx.user_id, func.to_tsvector("simple", MemoryItem.content).op("@@")(q))
        .returning(MemoryItem.id)
    )
    ids = [str(r[0]) for r in res.all()]
    if ids:
        audit(
            ctx.db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user_id,
            action=AuditAction.MEMORY_DELETED,
            target_ref=f"memory:{len(ids)}_items",
        )
    return {"deleted": len(ids)}


_HANDLERS = {
    "time.now": _time_now,
    "memory.search": _memory_search,
    "memory.save": _memory_save,
    "memory.delete_matching": _memory_delete_matching,
}
assert set(_HANDLERS) == set(TOOLS), "every registered tool needs exactly one handler"


def run_out(run: ToolRun, approval: ApprovalRequest | None = None) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "tool_key": run.tool_key,
        "status": run.status,
        "side_effect": run.side_effect,
        "args": run.args,
        "args_hash": run.args_hash,
        "result": run.result,
        "error_code": run.error_code,
        "revision": run.revision,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "approval": None
        if approval is None
        else {
            "id": str(approval.id),
            "summary": approval.summary,
            "decision": approval.decision,
            "expires_at": approval.expires_at.isoformat(),
            "args_hash": approval.args_hash,
        },
    }
