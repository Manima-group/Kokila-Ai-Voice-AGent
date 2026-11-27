# Kokila Architecture — unified platform

**Kokila — Intelligence that speaks.** One platform by Manima AI-Tech Solutions: one login, one Overview, two products, shared Kokila Connect, one Super Admin.

```
            Browser (Next.js 16, responsive web, orange/white/grey)
  /login /signup → /overview (product chooser) → /calling-agent/*  |  /assistant/{business,personal}
                     /integrations /billing /settings /help /admin (Manima Super Admin)
                                   │  same-origin /api/v1 rewrite
                                   ▼
         FastAPI modular monolith (one API, one auth, one entitlement policy)
  identity & auth │ tenants & team │ platform (capabilities) │ billing │ audit │ notifications
  Calling Agent: agents, telephony, calls, contacts/leads, campaigns, appointments, analytics
  Business Assistant: conversations, LLM provider adapter, tools, memory, reminders, approvals
  Kokila Connect: connector registry, encrypted connections, adapters (ERPNext, Manima Hub), metric catalog
                                   │
       PostgreSQL 16 (authoritative, one Alembic graph) · Redis (broker, rate limits) · Celery worker + beat
       External: Retell (voice), OpenAI/Anthropic (LLM, explicit model), ERPNext/Manima Hub, Google, Razorpay
```

## Decisions (from the owner's 27 Nov 2026 amendment, overriding v5.0 where they conflict)
| Topic | Decision |
|---|---|
| Theme | Orange, white, grey (reference dashboard image) |
| Products | Calling Agent and Business Assistant; Personal mode lives inside Business Assistant |
| Unpurchased product | Visible, locked, with Upgrade / Request access; API returns 403 |
| Connect | Shared infrastructure, not a product; Manima Hub first-party; ERPNext added |
| Backends / DBs | One backend, one database (the repository already had a single backend/DB — no merge needed) |
| Native apps | Out of scope (web/PWA only) |

## Repository audit (27 Nov 2026)
Single repository, single FastAPI backend, single PostgreSQL database, single Next.js frontend. No duplicate auth, organization or billing logic existed, so no cross-database consolidation was required. Existing records are preserved: migration 0003 grants every existing plan the Calling Agent package it already had (plus outbound if `features.outbound` was set) and the starter Business Assistant package; verified on the dev database (tenant from 17 Nov retained access).

## Entitlements (single policy for every surface)
`effective(key) = known key ∧ ¬platform_disabled(key) ∧ (unexpired tenant override ?? plan grant) ∧ subscription active ∧ all dependencies effective`. Default deny.
- Registry: `backend/app/platform/registry.py` (product keys + KOK-01…KOK-20 + personal mode). KOK-17/18/19 are mandatory infrastructure, not purchasable.
- Enforced in routers (`require_capability`), inbound call routing, campaign dispatch, metric execution (Calling Agent data requires that product) and assistant tools. The UI only mirrors `/me/capabilities`.
- Super Admin changes are revision-checked (409 on stale), dependency-validated (409), optionally cascade disables, and audited.

## Business Assistant
- LLM: `app/assistant/llm.py` — OpenAI or Anthropic via HTTP, configured by `LLM_PROVIDER` + `LLM_MODEL` + key. No default model and no silent fallback; the configured provider/model is shown in the UI and stored on every reply.
- Tool loop (max 4 rounds): business mode → `run_metric`, `create_follow_up_task` (approval-gated); personal mode → `propose_memory` (user approves), `create_reminder`, `web_search` (Brave, only if configured). Tools are filtered by capability; tool output is data, never instructions.
- Quick reports call the governed metric catalog directly, so useful answers exist even without an LLM.
- Isolation: conversations, memory, reminders and actions are scoped to `(tenant_id, user_id)`; personal mode gets no business tools and business mode never reads personal memory.
- Voice: browser Web Speech API (recognition + synthesis) with independent mic/speaker mute, barge-in and an optional foreground wake phrase. The realtime LiveKit/OpenAI Realtime path is **not implemented** (pending provider evaluation — see IMPLEMENTATION_PROGRESS).

## Kokila Connect
- Catalog of 14 connectors; only `implemented` adapters can be connected. `planned` connectors display "Coming soon" and can never appear connected.
- Credentials are Fernet-encrypted; a connection is `connected` only after a live `verify()` call (ERPNext: `frappe.auth.get_logged_user`; Manima Hub: Kokila Connect manifest).
- Governed metrics (`app/connect/metrics.py`) document their formulas, compute deterministically and return provenance (connector, connection, records, fetched_at) and warnings (partial periods, currency).
- SSRF guard: production requires HTTPS and public addresses for connector base URLs.

See also `docs/architecture/` for call flows, database schema and billing.
