# Branch comparison: `main` vs `feature/unified-platform`

_Written 27 Nov 2026, before any migration was run. Read-only analysis. Nothing on `main` has been changed._

| | `main` (bc0e69b, V5 foundation, PR #1) | `feature/unified-platform` (4a31bc1) |
|---|---|---|
| Git history | Its own root commit | Its own root commit. **No common ancestor**, so a normal PR/merge is impossible |
| Layout | `apps/web`, `services/api`, `infrastructure/` | `frontend/`, `backend/` |
| Python | Async SQLAlchemy 2 + asyncpg, uv + `uv.lock` | Sync SQLAlchemy 2 + psycopg3, pip requirements |
| Tenancy | **PostgreSQL RLS** (forced) using the NOBYPASSRLS `kokila_app` role, transaction-local GUCs (`kokila.scope/tenant_id/user_id`) and composite tenant FKs | Application-level `tenant_id` filters only |
| Auth | Argon2id, rotating refresh families, **TOTP MFA** (required for platform roles), Redis rate limits | Argon2, rotating refresh cookie, no MFA |
| Tenant roles | `owner/admin/staff/member` + `Permission` enum (9 perms) | `COMPANY_ADMIN/MANAGER/OPERATOR/VIEWER` + ~30 string perms |
| Platform roles | `super_admin/support/finance/operations` | `is_super_admin` flag |
| Entitlements | `capability_catalog` + `capability_dependencies` tables, immutable versioned plans, overrides, kill switches, policy revisions + outbox | Python registry, `plan_capabilities`, overrides, platform controls, revision checks |
| Capability keys | `assistant.*`, `voice.agents/inbound/outbound`, `connect.*`, `automate.*`, `platform.*`, 12 `connector.*` (no ERPNext) | `product.calling_agent`, `product.business_assistant`, `assistant.personal`, KOK-01..20 |
| Assistant | Session state machine, server-side mute, barge-in, provider router with circuit breaker, tool broker + approvals, pgvector memory | Conversations, approvals bound to sha256(args), reminders, notifications, LLM adapters |
| Web | Next 16 / React 19 / Tailwind 4, **HttpOnly-cookie BFF** (`/api/k/[...path]`), CSP, PWA; 1.9k LOC; **provisional yellow theme** | Same versions, client-side token; 3.9k LOC; **orange/white/grey**, product chooser, locked cards |
| Tests | 41 pass locally (verified today: `uv run pytest -q`, real PG16 + pgvector + Redis) | 52 pass; CI run 45969809558 green |
| Migrations | 0001 initial (24 tables), 0002 RLS + grants | 0001–0004 (48 tables) |

## Feature overlap

| Area | main | feature | Integration decision |
|---|---|---|---|
| Auth, sessions, MFA | ✅ stronger | ✅ | **Keep main.** Drop the feature branch's auth |
| Orgs, memberships, RBAC | ✅ | ✅ | **Keep main.** Add `manager` and `viewer` roles plus Calling-Agent permissions (below) |
| Entitlements / Super Admin | ✅ catalog in DB | ✅ registry in code | **Keep main's engine.** Add product keys to the catalog |
| Business Assistant, Personal Mode, memory, tools, approvals | ✅ deeper | ✅ | **Keep main.** Port only the missing pieces: reminders, notifications, quick reports |
| Calling Agent: agents/versions, knowledge, phone numbers, Retell, calls, webhooks, handoff | ❌ | ✅ | **Port** |
| CRM: contacts, leads, consent, suppression | ❌ | ✅ | **Port** |
| Campaigns (consent-gated, DND windows, attempts) | ❌ | ✅ | **Port** |
| Appointments (btree_gist exclusion), calendar | ❌ | ✅ | **Port** |
| Billing: Razorpay, usage, invoices | ❌ (plans only) | ✅ | **Port** onto main's `plans`/`subscriptions`/`usage_events` |
| Kokila Connect: ERPNext and Manima Hub adapters, governed metrics | ❌ (catalog keys only) | ✅ | **Port**. Add `connector.erpnext` |
| Analytics, audit export | partial (`audit_events`) | ✅ | Port analytics; reuse main's audit tables |
| UI: product chooser, locked cards, orange theme, Calling Agent pages | ❌ | ✅ | **Port into `apps/web`** through the BFF; re-theme main's pages orange |
| Docs: traceability, guides | partial | ✅ | Merge; main's `docs/requirements-traceability.csv` stays canonical |

## Schema conflicts

* **Duplicated concepts.** These feature tables map onto existing main tables and are **not** created again:
  * `tenants` → `organizations`
  * `tenant_memberships` → `memberships`
  * `audit_logs` → `audit_events`
  * `usage_records` → `usage_events`
  * `webhook_events` → `webhook_receipts`
  * `assistant_conversations/messages` → `conversations/messages`
  * `assistant_actions` → `tool_runs`/`approval_requests`
  * `assistant_preferences` → `assistant_identity_preferences`
  * `plans`, `subscriptions`, `refresh_tokens`, `memory_items`, `outbox_events`, `platform_capability_controls`, `tenant_capability_overrides`, `plan_capabilities` exist on both sides; keep main's version
* **New tables.** These are added through forward migrations, each tenant-scoped with a composite FK and an RLS policy:
  * provider_accounts, phone_numbers, agents, agent_versions, agent_tools
  * knowledge_sources, knowledge_documents
  * calls, call_events, call_recordings
  * contacts, contact_consents, suppression_entries, leads, lead_activities
  * campaigns, campaign_contacts, call_attempts
  * calendar_connections, appointments
  * payment_transactions, invoices
  * connector_connections, integration_connections
  * reminders, notifications
  * data_retention_policies, deletion_requests, background_job_failures
* **Organization type.** Calling Agent requires `organizations.type = 'business'`. Personal orgs only get Business Assistant / Personal Mode.

## Role mapping

| feature role | main role |
|---|---|
| COMPANY_ADMIN | `owner` (creator) / `admin` |
| MANAGER | **new `manager`** |
| OPERATOR | `staff` |
| VIEWER | **new `viewer`** (read-only) |

New `Permission` values:
* `calls.read`, `calls.transcript`, `calls.handoff`
* `contacts.write`, `contacts.import`, `contacts.delete`, `consent.write`
* `leads.write`, `leads.assign`
* `campaigns.write`, `campaigns.control`
* `appointments.write`, `analytics.read`
* `billing.manage`, `integrations.manage`

`agents.manage` already exists.

## Entitlement key mapping

Published keys are immutable, so nothing is renamed. The catalog version goes from 1 to 2.

* **Product availability is derived, not stored as a separate key.** This avoids rewriting immutable plan versions.
  * **Calling Agent** is available when `voice.agents` is effective and the org type is `business`.
  * **Business Assistant** is available when `assistant.text` is effective.
  * **Personal Mode** is the `personal` org type.
  * Locked cards come from this same derivation.

| feature key | main key |
|---|---|
| product.calling_agent | derived from `voice.agents` |
| product.business_assistant | derived from `assistant.text` |
| assistant.personal | `organizations.type = 'personal'` |
| KOK-05/06/07 | existing `voice.inbound` / `voice.outbound` (campaigns) / `voice.agents` |
| CRM, leads, consent | **new `voice.crm`** → depends on `voice.agents` |
| Appointments | **new `voice.appointments`** → depends on `voice.crm` |
| ERPNext / Manima Hub | **new `connector.erpnext`**, existing `connector.manima` |

Existing installs need new plan versions to grant `voice.crm` or `voice.appointments`, because seeded plans are never mutated. Fresh installs get them in `voice-starter` and `voice-business`.

## Migration hazard found

Migration `0002` builds its RLS policies from the live `TENANT_TABLES` constant in `app/models/base.py`. If that constant is extended, `0002` would silently change meaning on a fresh database.

New tenant tables must not be appended to it. Instead, each new migration carries its own frozen table list and applies the same policy helper.

## Data and migration strategy

1. **No production data exists on either branch.** Neither branch has been deployed: there is no hosted database, only local and CI databases built from migrations. "Preserving records" therefore means:
   * main's migration chain (0001, 0002) is never edited;
   * every change is a new forward migration (0003+) with a working `downgrade()`.
2. Before each migration on any shared environment, take a backup: `pg_dump -Fc` into `backups/<rev>.dump`. Rollback is `alembic downgrade <prev>`, or a restore from the dump.
3. Each migration is verified by:
   * upgrade, downgrade, upgrade on a clean database;
   * main's 41 existing tests still passing;
   * the new isolation probes (`test_isolation.py` style) for each new table.
4. `feature/unified-platform` stays on GitHub unchanged until the integration PR is merged. It is retired only then, by closing it rather than deleting it.

## Integration order (branch `feature/integrate-unified-platform`, off `main`)

| Step | Work | Gate |
|---|---|---|
| 1 | Catalog keys, `manager`/`viewer` roles, permissions (migration 0003) | Existing tests and entitlement tests |
| 2 | Calling Agent core: provider abstraction (mock + Retell), agents/versions, phone numbers, calls, signed webhooks, idempotent call events, handoff (0004) | Ported tests + RLS probes |
| 3 | CRM, consent and suppression, then campaigns (0005) | Consent/DND tests |
| 4 | Appointments with exclusion constraint (0006) | Double-booking tests |
| 5 | Billing: Razorpay orders, verified webhooks, usage, invoices (0007) | Signature and idempotency tests |
| 6 | Connect: ERPNext and Manima Hub, governed metrics (0008) | Adapter tests |
| 7 | Web: orange theme, product chooser, locked cards, Calling Agent pages, Super Admin products | Build + E2E |
| 8 | Docs, CI, then the PR into `main` | Green CI, review |

## Open external blockers (unchanged)

* LLM, Retell, Razorpay, ERPNext and Google Calendar credentials
* Manima Hub `/kokila/v1` endpoints
* LiveKit/TURN
* DPDP/TRAI legal review
