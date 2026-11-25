"""Tool registry discovery, runs, approvals and cancellation (§24.3)."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.assistant.service import append_message
from app.core.deps import Tenant
from app.core.errors import NotFound
from app.domain.constants import ToolRunStatus
from app.models import ApprovalRequest, ToolRun
from app.tools import service

router = APIRouter(prefix="/v1", tags=["tools"])


@router.get("/tools", operation_id="tools_list")
async def list_tools(ctx: Tenant) -> dict:
    """Only tools whose capability and permission are effective are listed."""
    return {
        "items": [
            {
                "key": t.key,
                "version": t.version,
                "description": t.description,
                "capability": t.capability,
                "side_effect": t.side_effect.value,
                "requires_approval": t.requires_approval,
                "input_schema": t.json_schema(),
            }
            for t in service.available_tools(ctx)
        ]
    }


class RunIn(BaseModel):
    tool_key: str
    args: dict[str, Any] = Field(default_factory=dict)
    conversation_id: uuid.UUID | None = None


@router.post("/tools/runs", status_code=202, operation_id="tools_runs_create")
async def create_run(
    body: RunIn, ctx: Tenant, idempotency_key: Annotated[str, Header(min_length=8, max_length=128)]
) -> dict:
    run, approval = await service.request_run(
        ctx,
        tool_key=body.tool_key,
        args=body.args,
        idempotency_key=f"api:{idempotency_key}",
        conversation_id=body.conversation_id,
    )
    return service.run_out(run, approval)


async def _run(ctx, run_id: uuid.UUID) -> ToolRun:
    run = await ctx.db.scalar(select(ToolRun).where(ToolRun.id == run_id, ToolRun.requested_by == ctx.user_id))
    if run is None:
        raise NotFound("tool run not found")
    return run


@router.get("/tools/runs/{run_id}", operation_id="tools_runs_get")
async def get_run(run_id: uuid.UUID, ctx: Tenant) -> dict:
    run = await _run(ctx, run_id)
    ap = await ctx.db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id))
    return service.run_out(run, ap)


@router.post("/tools/runs/{run_id}/cancel", status_code=202, operation_id="tools_runs_cancel")
async def cancel_run(run_id: uuid.UUID, ctx: Tenant) -> dict:
    run = await service.cancel(ctx, run_id)
    out = service.run_out(run)
    out["cancelled"] = run.status == ToolRunStatus.CANCELLED
    out["already_committed"] = run.status == ToolRunStatus.SUCCEEDED
    return out


@router.get("/approvals", operation_id="approvals_list")
async def list_approvals(
    ctx: Tenant, status: Literal["pending", "all"] = "pending", limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> dict:
    stmt = (
        select(ApprovalRequest)
        .where(ApprovalRequest.requested_by == ctx.user_id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    if status == "pending":
        stmt = stmt.where(ApprovalRequest.decision == "pending")
    rows = (await ctx.db.scalars(stmt)).all()
    items = []
    for a in rows:
        run = await ctx.db.get(ToolRun, a.run_id)
        if run is not None:
            items.append(service.run_out(run, a))
    return {"items": items, "next_cursor": None}


class DecisionIn(BaseModel):
    decision: Literal["approve", "deny"]
    args_hash: Annotated[str, Field(min_length=64, max_length=64)]


@router.post("/approvals/{approval_id}/decision", operation_id="approvals_decide")
async def decide(approval_id: uuid.UUID, body: DecisionIn, ctx: Tenant) -> dict:
    run, approval = await service.decide(
        ctx, approval_id=approval_id, approve=body.decision == "approve", expected_args_hash=body.args_hash
    )
    if run.conversation_id is not None:
        # Record the verified outcome in the conversation so later turns reason from facts (§14.1).
        await append_message(
            ctx,
            run.conversation_id,
            turn_id=uuid.uuid4(),
            role="tool",
            content=json.dumps({"status": run.status, "result": run.result}, ensure_ascii=False),
            meta={"tool_key": run.tool_key, "run_id": str(run.id), "after_approval": True},
        )
    return service.run_out(run, approval)
