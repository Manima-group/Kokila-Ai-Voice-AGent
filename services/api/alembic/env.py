"""Alembic env: runs as the schema-owner role under a PostgreSQL advisory lock (§29.2)."""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings
from app.models import Base

MIGRATION_LOCK_KEY = 7_515_000_001  # stable advisory-lock key for Kokila migrations

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("KOKILA_MIGRATION_DATABASE_URL") or get_settings().migration_database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.execute(text("set lock_timeout = '30s'"))
        await conn.execute(text("select pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        await conn.commit()
        try:
            await conn.run_sync(_do_run)
            await conn.commit()
        finally:
            await conn.execute(text("select pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
            await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
