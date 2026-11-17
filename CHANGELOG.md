# Changelog

## [0.1.0] — 2026-11-17
### Added
- FastAPI modular-monolith backend: auth (argon2, rotating refresh tokens), multi-tenant RBAC, agent builder with versions and knowledge base, Retell and mock voice providers, signed webhook ingestion with call state machine, agent tools, CRM (contacts, CSV import, consent, suppression, leads, tasks), consent-gated outbound campaigns with TRAI-aware controls and kill switches, appointments (internal + Google) with overlap protection and reconciliation, signed outbound webhooks/n8n via transactional outbox, Razorpay billing with webhook-only activation and GST invoices, analytics, super admin console, audit, retention and erasure.
- Alembic migrations (schema + trial plan seed).
- Celery workers and beat schedule.
- Next.js 16 web app covering all product screens.
- Dockerfiles, Compose (dev + production with Caddy HTTPS), backup/restore scripts, GitHub Actions CI.
- Documentation set under `docs/`.
