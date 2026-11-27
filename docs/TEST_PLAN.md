# Test Plan

## Automated (CI, deterministic, mock providers) — `backend/tests`
Runs against real PostgreSQL 16 + Redis. Each run validates migrations `upgrade → downgrade → upgrade`.

| Area | Tests |
|---|---|
| Auth | register/login, duplicate & weak password, invalid credentials + lockout, expired & forged JWT, refresh rotation + reuse detection, suspended tenant |
| Tenancy/RBAC | cross-tenant contacts/campaigns/calls/billing denial, header spoofing, viewer/operator denials, operator assigned-lead scope, cross-tenant campaign contacts and lead assignment |
| Agents | invalid config, template validation, plan agent limit, versioning + publish, provider failure → 502 + `sync_status=failed`, injection-flagged knowledge |
| Webhooks | missing/invalid/tampered signature, malformed payload, inbound routing response, unknown number ignored, duplicate, out-of-order, 6-way concurrent duplicate delivery, tool calls (lead capture, availability without calendar, opt-out, bad booking input) |
| Campaigns | missing/expired/revoked/wrong-purpose consent, suppressed contact never dialled, outside legal hours, campaign days, concurrency limit, paused, kill switch, provider outage → retry, no-answer → retry, unique attempt keys, opt-out during call, plan without outbound, compliance gating for live provider |
| Appointments | booking + idempotency, overlap 409, timezone (UTC input → IST), naive datetime + outside hours, 6-way concurrent booking → single winner, cancel/reschedule, Google external success/local failure reconciliation, external failure → failed |
| Billing | GST checkout, invalid/valid client signature, no activation from browser, webhook bad signature 401, activation + invoice, duplicate webhook, subscription expiry → 402, minutes exhausted |
| CRM/Admin | CSV import (dupes, invalid rows, consent without evidence), search/tags, suppression removal rules, erasure, tasks, signed outbox delivery + failure backoff, super admin plans/compliance/kill switch/suspend/audit, analytics from stored data |

| Unified platform (27 Nov) | product entitlements on API (calling-only, assistant-only, both), Super Admin revision/dependency conflicts, cascade, platform capability kill switch, plan packages, ERPNext verify/failed creds/metrics math/returns/outstanding/low stock/compare, connector tenant isolation, revoke, planned connectors cannot be connected, assistant without LLM (503), business answers only from tool data (no data → error reported), approval hash binding + single execution, personal isolation from colleagues, memory approval, reminders → notifications, custom-name entitlement + input validation |

Frontend: ESLint, `tsc --noEmit`, `next build` in CI. End-to-end browser checks (Playwright, run manually 27 Nov): signup → /overview; open each product; old URL redirect; Super Admin locks Calling Agent → locked card + locked direct URL; ERPNext connect via UI against a local test double → quick report renders KPIs/chart; mobile overview. Not yet in CI.

## Live provider verification — PENDING (requires credentials)
Run on staging with test accounts and record results in IMPLEMENTATION_PROGRESS.md:
1. Retell: publish agent (en-IN) → inbound call to DID → events arrive, signature verified, transcript stored.
2. Tool calls from a live call (capture_lead, check_availability, book_appointment, request_human_transfer, record_opt_out).
3. Outbound test call to an internal phone (`POST /calls/test`), then a 2-contact campaign with consent.
4. Per language (en, hi, kn; te via alternative STT): recognition accuracy, response language, pronunciation of names/numbers, barge-in/interruption, silence handling, language switching mid-call. **Do not mark a language production-ready until this passes.**
5. Razorpay test mode: checkout → capture → webhook → active plan → invoice; failed payment.
6. Google Calendar: OAuth connect, availability, booking, reschedule, cancel, token refresh.
7. Load: 50 concurrent webhook deliveries/s for 10 min; campaign with 1 000 contacts at concurrency 20 (define SLOs first).
