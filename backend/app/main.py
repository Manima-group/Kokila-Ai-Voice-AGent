from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.admin.router import router as admin_router
from app.agents.router import router as agents_router
from app.analytics.router import router as analytics_router
from app.appointments.router import router as appointments_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.billing.router import webhook_router as billing_webhook_router
from app.calls.router import router as calls_router
from app.calls.webhooks import router as voice_webhook_router
from app.campaigns.router import router as campaigns_router
from app.contacts.router import router as contacts_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.ratelimit import get_redis
from app.db.session import engine
from app.integrations.router import router as integrations_router
from app.leads.router import router as leads_router
from app.telephony.router import router as telephony_router
from app.tenants.router import router as tenants_router

settings = get_settings()
configure_logging()
app = FastAPI(
    title="Kokila API",
    version="1.0.0",
    description="Kokila — multi-tenant AI voice agent SaaS by Manima AI-Tech Solutions",
    docs_url="/api/docs",
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
)
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if settings.environment == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


api = APIRouter(prefix="/api/v1")
for r in (
    auth_router,
    tenants_router,
    agents_router,
    telephony_router,
    contacts_router,
    leads_router,
    campaigns_router,
    calls_router,
    appointments_router,
    integrations_router,
    analytics_router,
    billing_router,
    audit_router,
    admin_router,
    billing_webhook_router,
    voice_webhook_router,
):
    api.include_router(r)
app.include_router(api)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "service": "kokila-api"}


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    checks = {"database": "ok", "redis": "ok"}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    try:
        get_redis().ping()
    except Exception:  # noqa: BLE001
        checks["redis"] = "unavailable"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", **checks, "voice_provider": settings.voice_provider})
