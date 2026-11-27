# System Architecture

## Components

```
Browser ──HTTPS──> Caddy ──> web (Next.js, :3000) ──/api/v1 rewrite──> api (FastAPI, :8000)
Retell / Razorpay ──HTTPS (signed)──> Caddy ──> api /api/v1/webhooks/*
api ──> PostgreSQL 16 (authoritative)        api ──> Redis (rate limits)
worker (Celery) <── Redis broker ── beat (schedules)
worker ──> PostgreSQL, Voice provider (outbound dial), tenant webhooks/n8n (outbox), Google Calendar
```

- **Modular monolith**: one FastAPI app with domain packages (`auth`, `tenants`, `agents`, `voice`, `telephony`, `calls`, `contacts`, `leads`, `campaigns`, `appointments`, `integrations`, `analytics`, `billing`, `audit`, `admin`). Each owns its models, router and service.
- **Workers** (`app/workers/tasks.py`): `dispatch_campaigns` (30 s), `process_outbox` (15 s), `retry_failed_webhooks` (60 s), `reconcile_appointments` (5 min), `expire_subscriptions` (1 h), `apply_retention`, `purge_raw_events` (daily). Task failures are recorded in `background_job_failures`.
- **Sync SQLAlchemy** in a threadpool (FastAPI sync endpoints). Webhook endpoints read the raw body asynchronously, then process in a threadpool. No external HTTP call is made while holding a long DB transaction: campaign attempts and appointment reservations are committed *before* contacting the provider.

## Tenancy & authorization

- Every tenant-owned row has a non-null indexed `tenant_id`. All queries filter on `TenantContext.tenant_id`; cross-tenant ids return **404** via `get_owned()`.
- `X-Tenant-ID` is validated against the user's active membership (`auth/deps.py`). Suspended tenants are blocked.
- RBAC is server-side (`auth/rbac.py`): `COMPANY_ADMIN`, `MANAGER`, `OPERATOR` (assigned leads only), `VIEWER` (read; masked numbers; no transcripts). `SUPER_ADMIN` is a platform flag; `/admin/*` actions are audited.
- PostgreSQL RLS was evaluated and **not enabled** for the MVP: the app connects as a single role through a pool, and RLS policies keyed on a session GUC add risk of leaks on pooled connections if any code path forgets to set it. Isolation is enforced in the application layer and covered by cross-tenant tests. Revisit RLS (with `SET LOCAL` per transaction) before multi-region scale-out.

## Reliability patterns

| Concern | Mechanism |
|---|---|
| Duplicate provider events | `webhook_events.dedupe_key` UNIQUE + `call_events.dedupe_key` UNIQUE |
| Out-of-order / stale events | Monotonic call state machine (`calls/service.py`); stale events stored with `applied=false` |
| Concurrent events | `SELECT … FOR UPDATE` on the call, savepoints + unique constraints, optimistic `row_version` |
| Duplicate dials | `call_attempts.idempotency_key` UNIQUE, also passed to Retell `idempotency_key` |
| Double booking | Postgres `EXCLUDE USING gist` on `(calendar, tstzrange)` for active appointments |
| External booking succeeded, DB failed | Deterministic Google event id (`kk<appointment uuid>`) + `reconcile_pending()` |
| Payment duplicates | `x-razorpay-event-id` dedupe, unique order/payment ids, activation only from signed webhook |
| Webhook delivery to tenants | Transactional outbox, exponential backoff (max 8 attempts) → `dead` |
| Usage double-count | `usage_records` UNIQUE `(call_id, kind)` |

Exactly-once is **not** claimed; effects are made effectively-once via idempotency, constraints and reconciliation.

## Observability

- JSON logs to stdout with phone/email redaction (`core/logging.py`); no raw payloads are logged.
- `/health` (liveness) and `/ready` (DB + Redis) endpoints; Docker health checks.
- `/api/v1/admin/health`: failed webhooks, outbox backlog/dead letters, open job failures, live calls.
- OpenTelemetry instrumentation is **not yet wired** (see IMPLEMENTATION_PROGRESS known issues).
