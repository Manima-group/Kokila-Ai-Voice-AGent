# Changelog

## [0.2.0] — 2026-11-27 — Unified platform
### Added
- Product-selection Overview after login; Calling Agent workspace (`/calling-agent`), Business Assistant (`/assistant`, business + personal modes), Integrations, Help.
- Capability licensing (KOK registry) enforced server-side; Super Admin products & features matrix.
- Kokila Connect: connector catalog, verified encrypted connections, ERPNext and Manima Hub adapters, governed metrics.
- Business Assistant backend: OpenAI/Anthropic adapters, tool loop, approvals, memory, reminders, notifications.
### Changed
- Login/sign-up land on `/overview`; old Calling Agent URLs redirect.
- Login accepts any stored email format; super-admin CLI validates deliverable emails.
### Fixed
- Local-date handling in quick reports and appointment availability (no UTC day shift).

## [0.1.0] — 2026-11-17
### Added
- FastAPI modular-monolith backend: auth (argon2, rotating refresh tokens), multi-tenant RBAC, agent builder with versions and knowledge base, Retell and mock voice providers, signed webhook ingestion with call state machine, agent tools, CRM (contacts, CSV import, consent, suppression, leads, tasks), consent-gated outbound campaigns with TRAI-aware controls and kill switches, appointments (internal + Google) with overlap protection and reconciliation, signed outbound webhooks/n8n via transactional outbox, Razorpay billing with webhook-only activation and GST invoices, analytics, super admin console, audit, retention and erasure.
- Alembic migrations (schema + trial plan seed).
- Celery workers and beat schedule.
- Next.js 16 web app covering all product screens.
- Dockerfiles, Compose (dev + production with Caddy HTTPS), backup/restore scripts, GitHub Actions CI.
- Documentation set under `docs/`.
