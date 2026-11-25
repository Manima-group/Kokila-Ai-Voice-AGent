"""Kokila API application factory."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.assistant.router import router as assistant_router
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.db import DbScope, dispose_engine, unit_of_work
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, new_trace_id, set_trace
from app.core.ratelimit import close_redis, redis_client
from app.identity.router import router as identity_router
from app.memory.router import router as memory_router
from app.platform.router import router as platform_router
from app.providers.reasoning import close_reasoning, get_reasoning_router
from app.tools.router import router as tools_router

EXPECTED_MIGRATION = "0002"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_reasoning()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.service_name, s.build_id)
    app = FastAPI(
        title="Kokila API",
        version="5.0.0",
        lifespan=lifespan,
        docs_url="/docs" if s.env.value in ("development", "test") else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["X-Trace-Id"],
        max_age=600,
    )

    @app.middleware("http")
    async def _trace(request: Request, call_next) -> Response:
        trace = request.headers.get("traceparent", "").split("-")[1:2]
        trace_id = trace[0] if trace and len(trace[0]) == 32 else new_trace_id()
        req_id = request.headers.get("x-request-id", "")[:64] or new_trace_id()
        set_trace(trace_id, req_id)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        route = request.scope.get("route")
        logging.getLogger("kokila.http").info(
            "request",
            extra={
                "method": request.method,
                "route": getattr(route, "path", None),
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "tenant_ref": getattr(request.state, "tenant_id", None),
            },
        )
        return response

    for r in (auth_router, platform_router, assistant_router, memory_router, identity_router, tools_router):
        app.include_router(r)

    @app.get("/healthz", tags=["ops"], operation_id="healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], operation_id="readyz")
    async def readyz(response: Response) -> dict:
        checks: dict[str, str] = {}
        try:
            async with unit_of_work(scope=DbScope.ANONYMOUS) as db:
                await db.execute(text("select 1"))
                ver = await db.scalar(text("select version_num from alembic_version"))
                checks["database"] = "ok"
                checks["schema"] = "ok" if ver == EXPECTED_MIGRATION else "mismatch"
        except Exception:  # noqa: BLE001 - readiness reports, never raises
            checks["database"] = "unavailable"
        try:
            await redis_client().ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "unavailable"
        checks["reasoning"] = "configured" if get_reasoning_router().configured else "not_configured"
        ready = checks.get("database") == "ok" and checks.get("schema") == "ok" and checks.get("redis") == "ok"
        response.status_code = 200 if ready else 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    return app


app = create_app()
