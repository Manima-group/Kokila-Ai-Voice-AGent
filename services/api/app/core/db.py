"""Database engine and transaction-local RLS context (§24.2, §27.2).

The application connects as a NOBYPASSRLS role. Every unit of work runs in one
transaction whose identity is set with ``set_config(..., is_local => true)``, so
context is discarded at commit/rollback and can never leak across pooled
connections.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


class DbScope(StrEnum):
    ANONYMOUS = "anonymous"
    TENANT = "tenant"
    PLATFORM = "platform"
    SYSTEM = "system"


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True, pool_timeout=5
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def set_context(
    session: AsyncSession, *, scope: DbScope, user_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None
) -> None:
    await session.execute(
        text(
            "select set_config('kokila.scope', :s, true), set_config('kokila.user_id', :u, true), "
            "set_config('kokila.tenant_id', :t, true)"
        ),
        {"s": scope.value, "u": str(user_id) if user_id else "", "t": str(tenant_id) if tenant_id else ""},
    )


@asynccontextmanager
async def unit_of_work(
    *, scope: DbScope, user_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """One transaction per unit of work; commit on success, rollback on any exception."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        try:
            await set_context(session, scope=scope, user_id=user_id, tenant_id=tenant_id)
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
