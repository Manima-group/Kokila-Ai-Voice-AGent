# Kokila — Intelligence that speaks.

Unified AI SaaS by **Manima AI-Tech Solutions**: one login, one product-selection Overview, two products and shared integrations.

- **Calling Agent** — AI voice agents for inbound calls, consent-based outbound campaigns, CRM, appointments and call analytics.
- **Business Assistant** — voice/text assistant over your connected business data (Business mode) plus a private Personal mode with memory and reminders.
- **Kokila Connect** — shared integration layer (Manima Hub, ERPNext, Google Calendar, n8n implemented; more planned).
- **Manima Super Admin** — tenants, plans, per-client product/feature licensing, kill switches, health and audit.

| Layer | Stack |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic (modular monolith) |
| Workers | Celery + Redis (campaign dispatch, outbox, webhook retry, reminders, reconciliation, retention) |
| Data | PostgreSQL 16, Redis 7 |
| AI | Voice: Retell AI via provider abstraction (+ mock); Assistant LLM: OpenAI or Anthropic (explicit model); browser speech |
| Payments | Razorpay |
| Web | Next.js 16, React 19, TypeScript, Tailwind CSS 4, TanStack Query (orange/white/grey) |
| Infra | Docker, Docker Compose, Caddy (HTTPS), GitHub Actions |

> **Status:** see [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md) and [REQUIREMENTS_TRACEABILITY.csv](REQUIREMENTS_TRACEABILITY.csv). Tests use mock/test-double providers. **No live provider (Retell, LLM, ERPNext, Razorpay, Google) has been verified yet — not production-ready.**

## Quick start (local, mock voice mode)
```bash
cp .env.example .env     # set JWT_SECRET and ENCRYPTION_KEY (commands in the file); optionally LLM_PROVIDER/LLM_MODEL/key
docker compose up --build -d
SUPERADMIN_PASSWORD='choose-a-long-passphrase' docker compose run --rm -e SUPERADMIN_PASSWORD api \
  python -m app.cli create-superadmin --email ops@yourdomain.com
open http://localhost:3000
```
- **Create an account:** http://localhost:3000/signup → you become Company Admin, land on **/overview** with a 14-day trial (Calling Agent inbound + Business Assistant starter).
- **Super Admin:** sign in with the email/password you set above → **/admin**.
- No default credentials exist.

Without Docker:
```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://kokila:kokila@localhost:5432/kokila REDIS_URL=redis://localhost:6379/0
.venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload        # http://localhost:8000/api/docs
.venv/bin/celery -A app.workers.celery_app worker -B -l info
cd ../frontend && npm ci && BACKEND_URL=http://localhost:8000 npm run dev          # http://localhost:3000
```

## Commands
| Task | Command |
|---|---|
| Backend tests (Postgres + Redis, DB `kokila_test`) | `cd backend && pytest -q` |
| Lint / types | `ruff check app tests alembic && ruff format --check app tests && mypy app` |
| Frontend | `cd frontend && npm run lint && npm run typecheck && npm run build` |
| Migrations | `docker compose run --rm migrate` — see [DATABASE_MIGRATION_GUIDE](docs/DATABASE_MIGRATION_GUIDE.md) |
| Backup / restore | `scripts/backup.sh`, `scripts/restore.sh <file>` |

## Documentation
[MASTER_SPECIFICATION](docs/MASTER_SPECIFICATION.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) · [INTEGRATION_GUIDE](docs/INTEGRATION_GUIDE.md) · [DATABASE_MIGRATION_GUIDE](docs/DATABASE_MIGRATION_GUIDE.md) · [DEPLOYMENT_GUIDE](docs/DEPLOYMENT_GUIDE.md) · [SECURITY_GUIDE](docs/SECURITY_GUIDE.md) · [TELECOM_COMPLIANCE_CHECKLIST](docs/TELECOM_COMPLIANCE_CHECKLIST.md) · [TEST_PLAN](docs/TEST_PLAN.md) · [OPERATIONS_RUNBOOK](docs/OPERATIONS_RUNBOOK.md) · [USER_GUIDE](docs/USER_GUIDE.md) · [SUPER_ADMIN_GUIDE](docs/SUPER_ADMIN_GUIDE.md) · [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md) · detailed flows in `docs/architecture/`.

© Manima AI-Tech Solutions · business@manima.co.in
