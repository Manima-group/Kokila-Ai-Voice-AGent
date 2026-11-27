# Implementation status — Kokila V5.0

_Last updated 25 Nov 2026 (branch `feat/kokila-v5-foundation`)._

## Integration checkpoint (27 Nov 2026, branch `feature/integrate-unified-platform`, draft PR #2)

The earlier Kokila Calling Agent codebase (the "original Kokila codebase" blocker below) is on `feature/unified-platform`. It is being ported into this architecture. The plan and the full comparison are in `docs/branch-comparison.md`.

Step 1 is verified:
* Roles, permissions, catalog v2 and migration 0003 are in.
* 44 tests pass locally.
* CI is green for api, web and secrets-scan.

Next is step 2, the Calling Agent core.

## Repository audit (§24.4 step 1)

`Manima-group/Kokila-Ai-Voice-AGent` was **empty** (no commits) when work began. The spec says an existing Kokila
codebase "reportedly uses FastAPI, PostgreSQL 16, Redis, Celery, Next.js, Retell and Razorpay with mock providers".
That code is not in this repository. If it exists elsewhere, its Voice functionality and migrations still need to be
audited and reconciled with this branch (§7, §20.1). **This is an open blocker.**

## What is implemented and tested

| Area | Implemented | Evidence |
|---|---|---|
| Schema | 24 tables, UUID PKs, timestamptz, tenant-aware composite FKs, check constraints, partial unique indexes, pgvector column | `alembic/versions/0001`; upgrade→downgrade→upgrade verified |
| Isolation | PostgreSQL RLS on every tenant table (forced), user-private restrictive policies, NOBYPASSRLS app role, append-only audit/usage/policy tables | `tests/test_isolation.py` (raw-SQL probes) |
| Auth | Argon2id, neutral register/login errors, rotating refresh tokens with family revocation on reuse, logout revokes access, TOTP MFA (AES-GCM-encrypted secret), Redis rate limits | `tests/test_auth.py` |
| Super Admin / entitlements (KOK-17) | Capability registry (20 KOK keys + 12 connectors), normalized dependency edges, immutable plan versions, per-tenant overrides, kill switches, suspension, policy revisions + outbox, audited reasons, MFA-gated platform sessions, admin UI | `tests/test_entitlements.py`, e2e screenshots |
| Assistant sessions (KOK-01 partial, KOK-14-MUTE) | Session state machine, server-authoritative mic/speaker mute (default muted), revision checks, active-device unmute rule, new device starts muted, barge-in generation + played-chars, resume without replay | `tests/test_assistant.py` |
| Turns (KOK-02) | Idempotent turns, history with interruption truncation, memory retrieval, script-based language detection with hysteresis, provider router (retries, circuit breaker, safe-boundary failover), no DB transaction held across provider calls, stale-generation discard, quotas | `tests/test_assistant.py` |
| Tools / approvals | Typed registry, capability-filtered discovery, args validation, idempotency keys, approvals bound to identity + args hash + expiry, policy re-check before side effects, cancel semantics, durable run ledger | `tests/test_assistant.py` |
| Memory (KOK-03) | CRUD with revisions, delete-all, FTS retrieval, approval-gated assistant writes | tests + e2e |
| Identity (KOK-20) | Tenant/user resolution order, tenant lock, Unicode-safe name validation, honest wake-word status | `tests/test_identity.py` |
| Web | Login/register, voice/text assistant (Web Speech), mute/mute-all/stop/push-to-talk, approvals UI, memory, settings + MFA, Super Admin matrix/controls/audit, HttpOnly-cookie BFF with CSRF header, CSP, PWA manifest | `npm run build`; `tests/e2e/smoke.py` |
| Ops | Structured redacted JSON logs with trace IDs, safe error envelope, /healthz, /readyz, Celery outbox dispatcher (SKIP LOCKED), Dockerfiles (non-root, read-only), Compose, CI workflow, OpenAPI snapshot, generated TS contracts | `docker compose config`; `tests/test_worker.py` |

Commands run for this status: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app`, and
`uv run pytest -q` (41 passed). In `apps/web`: `npm run lint`, `npm run typecheck`, and `npm run build` (all
succeeded). `python tests/e2e/smoke.py` passed with no console errors.

## Not yet implemented (mandatory scope remaining)

None of these are claimed. Each still needs to be built and its gate passed:

* **Kokila Voice B2B** (KOK-05/06/07): agents and versions, knowledge, phone numbers, contacts/consent/suppression,
  campaigns, calls, Retell adapter, transfers, call analytics.
* **Realtime media**: LiveKit/WebRTC client, OpenAI Realtime session wiring, VAD and turn detection, full-duplex
  barge-in, TURN. Backend token issuance exists, but the client doesn't use it yet.
* **Research** (KOK-04), **files, images and Vision** (KOK-10), **reminders/scheduler**, **routines** (KOK-14),
  **cross-device event streaming** (SSE/WebSocket over the outbox channel).
* **Connect** (KOK-08/09): SDK packages, embed sessions, Web Component, analytics/semantic metrics, dashboards,
  Excel/CSV, exports.
* **Pro modules**: Automate (KOK-11), proactive alerts (KOK-12), meetings (KOK-13), private deployment with local
  models (KOK-15), marketplace (KOK-16), and all 12 named connectors.
* **Billing** (KOK-18): Razorpay/Stripe, invoices, reconciliation, proration.
* **Ops**: Terraform/AWS (OPS-02), image signing/SBOM, security scanning, load tests, backup/restore drills, and the
  rest of the handover docs (§32.4: file map, user/admin/developer guides, ERD, data dictionary, etc.).
* **Quality gates** (§16): no voice latency, WER, or native-speaker Telugu/Hindi/English evaluations have been run.

## External blockers (need Manima action)

| Blocker | Unblocks |
|---|---|
| OpenAI and/or Anthropic API keys and approved model IDs | Live reasoning verification (KOK-02), Realtime (KOK-01) |
| LiveKit Cloud project or self-hosted deployment + TURN | Realtime media path |
| Retell account, approved SIP/telecom partner, consented test numbers, DPDP/TRAI legal review | KOK-05/06 |
| Brave Search API access | KOK-04 |
| Vendor sandbox accounts for Tally, Zoho, Salesforce, SAP, Dynamics, Gmail, Outlook, WhatsApp, Teams, Slack, n8n | Connectors |
| Manima Hub design tokens/source (hub.manima.co.in) | Visual parity (§26.2). The current theme is a provisional yellow/white/cream/grey palette; **parity is unverified** |
| Original Kokila codebase (if it exists) | Repository reconciliation |
| AWS accounts, domains, Docker registry | OPS-02/03 |
| Native-speaker reviewers and consented audio | §16 gates |
