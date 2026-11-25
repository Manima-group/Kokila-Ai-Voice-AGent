"""User-editable personal memory with review and deletion (§5, KOK-03)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.audit import audit
from app.core.deps import TenantContext, capability
from app.core.errors import NotFound, RevisionConflict
from app.domain.capabilities import CapabilityKey
from app.domain.constants import AuditAction, Permission
from app.models import MemoryItem

router = APIRouter(prefix="/v1/memory", tags=["memory"])
MemCtx = Annotated[TenantContext, Depends(capability(CapabilityKey.ASSISTANT_MEMORY))]


class MemoryOut(BaseModel):
    id: uuid.UUID
    kind: str
    content: str
    confidence: float
    expires_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _out(m: MemoryItem) -> MemoryOut:
    return MemoryOut(
        id=m.id,
        kind=m.kind,
        content=m.content,
        confidence=m.confidence,
        expires_at=m.expires_at,
        revision=m.revision,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", operation_id="memory_list")
async def list_memory(ctx: MemCtx, limit: Annotated[int, Query(ge=1, le=100)] = 50, cursor: str | None = None) -> dict:
    ctx.require(Permission.MEMORY_MANAGE)
    stmt = (
        select(MemoryItem)
        .where(MemoryItem.user_id == ctx.user_id)
        .order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc())
    )
    if cursor:
        ts, cid = cursor.split("|", 1)
        c_at = datetime.fromisoformat(ts)
        stmt = stmt.where(
            (MemoryItem.updated_at < c_at) | ((MemoryItem.updated_at == c_at) & (MemoryItem.id < uuid.UUID(cid)))
        )
    rows = (await ctx.db.scalars(stmt.limit(limit + 1))).all()
    nxt = f"{rows[limit - 1].updated_at.isoformat()}|{rows[limit - 1].id}" if len(rows) > limit else None
    return {"items": [_out(m) for m in rows[:limit]], "next_cursor": nxt}


class MemoryIn(BaseModel):
    content: Annotated[str, Field(min_length=1, max_length=1000)]
    kind: Literal["semantic", "procedural", "episodic"] = "semantic"
    expires_at: datetime | None = None


@router.post("", status_code=201, response_model=MemoryOut, operation_id="memory_create")
async def create_memory(body: MemoryIn, ctx: MemCtx) -> MemoryOut:
    ctx.require(Permission.MEMORY_MANAGE)
    m = MemoryItem(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kind=body.kind,
        scope="personal",
        content=body.content.strip(),
        expires_at=body.expires_at,
    )
    ctx.db.add(m)
    await ctx.db.flush()
    await ctx.db.refresh(m)
    return _out(m)


class MemoryPatch(BaseModel):
    content: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    expires_at: datetime | None = None
    expected_revision: int


async def _get(ctx: TenantContext, mid: uuid.UUID, lock: bool = False) -> MemoryItem:
    stmt = select(MemoryItem).where(MemoryItem.id == mid, MemoryItem.user_id == ctx.user_id)
    m = await ctx.db.scalar(stmt.with_for_update() if lock else stmt)
    if m is None:
        raise NotFound("memory item not found")
    return m


@router.patch("/{memory_id}", response_model=MemoryOut, operation_id="memory_update")
async def update_memory(memory_id: uuid.UUID, body: MemoryPatch, ctx: MemCtx) -> MemoryOut:
    ctx.require(Permission.MEMORY_MANAGE)
    m = await _get(ctx, memory_id, lock=True)
    if m.revision != body.expected_revision:
        raise RevisionConflict("memory changed", details={"current_revision": m.revision})
    if body.content is not None:
        m.content = body.content.strip()
        m.embedding = None  # stale embedding must be recomputed, never served
    if "expires_at" in body.model_fields_set:
        m.expires_at = body.expires_at
    m.revision += 1
    await ctx.db.flush()
    await ctx.db.refresh(m)
    return _out(m)


@router.delete("/{memory_id}", status_code=204, operation_id="memory_delete")
async def delete_memory(memory_id: uuid.UUID, ctx: MemCtx) -> None:
    ctx.require(Permission.MEMORY_MANAGE)
    m = await _get(ctx, memory_id)
    await ctx.db.delete(m)  # hard delete; embedding lives in the same row so the index is updated with it
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.MEMORY_DELETED,
        target_ref=f"memory:{memory_id}",
    )


@router.delete("", status_code=204, operation_id="memory_delete_all")
async def delete_all_memory(ctx: MemCtx) -> None:
    ctx.require(Permission.MEMORY_MANAGE)
    await ctx.db.execute(delete(MemoryItem).where(MemoryItem.user_id == ctx.user_id))
    audit(
        ctx.db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=AuditAction.MEMORY_DELETED,
        target_ref="memory:all",
    )
