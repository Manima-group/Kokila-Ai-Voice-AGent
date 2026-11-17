# Kokila — AI Voice Agent SaaS

Multi-tenant SaaS by **Manima AI-Tech Solutions** that lets Indian businesses build multilingual AI voice agents, answer inbound calls, run consent-based outbound campaigns, manage leads and appointments, and bill on usage.

| Layer | Stack |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic (modular monolith) |
| Workers | Celery + Redis (campaign dispatch, outbox delivery, webhook retry, reconciliation, retention) |
| Data | PostgreSQL 16 (authoritative), Redis (broker, rate limits) |
| Voice | Provider abstraction → `RetellProvider` (official `retell-sdk`) and `MockVoiceProvider` |
| Payments | Razorpay (server-side orders, signature verification, webhook-only activation) |
| Web | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, TanStack Query, React Hook Form + Zod |
| Infra | Docker, Docker Compose, Caddy (HTTPS), GitHub Actions |

> **Status:** see [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). All automated tests run against mock providers; **live Retell, Razorpay and Google Calendar verification is still pending**, so this is not yet cleared for commercial production.

## Quick start (local, mock mode — no paid credentials needed)

```bash
cp .env.example .env              # then set JWT_SECRET and ENCRYPTION_KEY (commands are in the file)
docker compose up -d --build      # postgres, redis, migrate, api, worker, beat, web
docker compose run --rm api python -m app.cli seed-dev                      # optional [DEV] plans
SUPERADMIN_PASSWORD='choose-a-long-one' docker compose run --rm -e SUPERADMIN_PASSWORD api \
  python -m app.cli create-superadmin --email you@example.com
open http://localhost:3000        # sign up → create agent → publish → Voice testing → Run simulation
```

`VOICE_PROVIDER=mock` never places real calls. Simulated calls go through the same signed-webhook pipeline and are labelled **mock** everywhere; mock minutes are never billed.

### Without Docker

```bash
# backend
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://kokila:kokila@localhost:5432/kokila REDIS_URL=redis://localhost:6379/0
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload                       # http://localhost:8000/api/docs
.venv/bin/celery -A app.workers.celery_app worker -B -l info   # worker + beat (dev only)
# frontend
cd frontend && npm ci && BACKEND_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

## Commands

| Task | Command |
|---|---|
| Backend tests (needs Postgres + Redis; DB `kokila_test`) | `cd backend && pytest -q` |
| Lint / types | `ruff check app tests alembic && ruff format --check app tests && mypy app` |
| Frontend lint / types / build | `cd frontend && npm run lint && npm run typecheck && npm run build` |
| Apply migrations | `docker compose run --rm migrate` |
| Logs | `docker compose logs -f api worker beat` |
| Backup / restore | `scripts/backup.sh`, `scripts/restore.sh <file>` |
| Reset local DB (destructive) | `scripts/dev.sh reset-db` |

## Repository layout

```
backend/   app/{auth,tenants,agents,voice/providers,telephony,calls,contacts,leads,campaigns,
                appointments,integrations,analytics,billing,audit,admin,workers,core,db,schemas}
           alembic/  tests/
frontend/  src/{app,components,hooks,lib,types}
infrastructure/{docker,compose}   scripts/   docs/   .github/workflows/
```

## Documentation

- Product & architecture: [docs/architecture/PRODUCT_REQUIREMENTS.md](docs/architecture/PRODUCT_REQUIREMENTS.md), [SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md), [DATABASE_SCHEMA.md](docs/architecture/DATABASE_SCHEMA.md)
- Voice: [VOICE_PROVIDER_INTEGRATION.md](docs/architecture/VOICE_PROVIDER_INTEGRATION.md), [INBOUND_CALL_FLOW.md](docs/architecture/INBOUND_CALL_FLOW.md), [OUTBOUND_CAMPAIGN_FLOW.md](docs/architecture/OUTBOUND_CAMPAIGN_FLOW.md)
- API: [docs/api/API_DOCUMENTATION.md](docs/api/API_DOCUMENTATION.md) (+ `openapi.json`)
- Security & compliance: [SECURITY_AND_PRIVACY.md](docs/security/SECURITY_AND_PRIVACY.md), [TELECOM_COMPLIANCE_CHECKLIST.md](docs/security/TELECOM_COMPLIANCE_CHECKLIST.md)
- Billing: [BILLING_AND_USAGE.md](docs/architecture/BILLING_AND_USAGE.md)
- Operations: [DEPLOYMENT_GUIDE.md](docs/deployment/DEPLOYMENT_GUIDE.md), [OPERATIONS_RUNBOOK.md](docs/runbooks/OPERATIONS_RUNBOOK.md), [TEST_PLAN.md](docs/runbooks/TEST_PLAN.md)

© Manima AI-Tech Solutions · business@manima.co.in
