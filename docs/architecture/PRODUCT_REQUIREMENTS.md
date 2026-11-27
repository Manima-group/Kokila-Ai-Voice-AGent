# Product Requirements (summary)

Authoritative source: *KOKILA — MASTER ENGINEERING PROMPT v1.0* (Claude Project). This file maps requirements to the implementation.

| # | Module | Implemented in | Status |
|---|---|---|---|
| 1 | Super Admin dashboard (tenants, plans, entitlements, kill switch, health, compliance review) | `admin/router.py`, `frontend/(app)/admin` | Done |
| 2 | Registration & authentication (argon2, JWT + rotating refresh cookie, lockout) | `auth/` | Done |
| 3 | Multi-tenant management & isolation | `auth/deps.py`, every router | Done (app-level; RLS deferred) |
| 4 | Agent builder: 6 templates, languages, voice, greeting, instructions, rules, hours, tools, escalation, outcome schema, versions, knowledge | `agents/` | Done |
| 5 | Inbound calling (routing webhook, signed events, state machine, transcripts) | `calls/webhooks.py`, `calls/service.py` | Done (mock-verified; live pending) |
| 6 | Consent-based outbound campaigns (consent, suppression, windows, concurrency, retries, pause/resume/cancel, kill switches) | `campaigns/` | Done (mock-verified) |
| 7 | Multilingual (en, hi, kn via Retell; te not offered by retell-sdk) | `agents/templates.py`, `voice/providers/retell.py` | Adapter done; **live audio tests pending** |
| 8 | CRM: contacts, CSV import, dedupe, leads, assignment, tasks, timeline, consent, suppression | `contacts/`, `leads/` | Done |
| 9 | Appointments: internal + Google Calendar, availability, book/cancel/reschedule, overlap protection, reconciliation | `appointments/` | Done (Google live pending) |
| 10 | Call logs, transcripts, analytics | `calls/router.py`, `analytics/` | Done |
| 11 | Human handoff (tool, transfer_call config, operator tasks, terminate) | `calls/tools.py`, `agents/router.py` | Done |
| 12 | Integrations: signed webhooks, n8n, outbox | `integrations/` | Done |
| 13 | Subscriptions & usage billing (Razorpay, GST invoices, limits) | `billing/` | Done (Razorpay live pending) |
| 14 | Team & role management | `tenants/router.py` | Done |
| 15 | Audit logs, retention, erasure, monitoring | `audit/`, `admin/` | Done (OTel pending) |

## Explicit non-goals for MVP
LiveKit/SIP provider (interface ready), object storage for recordings (provider URLs stored), email delivery of invites (temporary password shown once), load-test-based SLOs.
