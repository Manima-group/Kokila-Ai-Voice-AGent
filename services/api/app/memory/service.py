from __future__ import annotations

from sqlalchemy import func, or_, select

from app.core.deps import TenantContext
from app.models import MemoryItem


async def search_memory(ctx: TenantContext, query: str, limit: int = 5) -> list[MemoryItem]:
    """Hybrid-lite retrieval: full-text rank ('simple' config keeps Telugu/Devanagari tokens) then recency.

    Vector retrieval activates once an embedding provider is configured and benchmarked (tracked blocker).
    RLS already restricts rows to this tenant and user; the explicit filter is defence in depth.
    """
    vec = func.to_tsvector("simple", MemoryItem.content)
    q = func.plainto_tsquery("simple", query)
    now = func.now()
    stmt = (
        select(MemoryItem)
        .where(
            MemoryItem.user_id == ctx.user_id,
            or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now),
            vec.op("@@")(q),
        )
        .order_by(func.ts_rank(vec, q).desc(), MemoryItem.updated_at.desc())
        .limit(limit)
    )
    hits = list((await ctx.db.scalars(stmt)).all())
    if len(hits) < limit:
        seen = {m.id for m in hits}
        recent = (
            await ctx.db.scalars(
                select(MemoryItem)
                .where(
                    MemoryItem.user_id == ctx.user_id, or_(MemoryItem.expires_at.is_(None), MemoryItem.expires_at > now)
                )
                .order_by(MemoryItem.updated_at.desc())
                .limit(limit)
            )
        ).all()
        hits += [m for m in recent if m.id not in seen][: limit - len(hits)]
    return hits
