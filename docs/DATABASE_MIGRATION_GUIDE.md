# Database Migration Guide

One PostgreSQL database, one Alembic graph (`backend/alembic/versions`):

| Revision | Content | Data effect |
|---|---|---|
| 0001 | Core schema (identity, Calling Agent, CRM, billing, audit) + exclusion/partial-unique constraints | — |
| 0002 | Seeds the free **trial** plan | insert-only |
| 0003 | `plan_capabilities`, `tenant_capability_overrides`, `platform_capability_controls`, `tenants.policy_revision` | Grants every existing plan its current Calling Agent access (+outbound if `features.outbound`) and the starter Business Assistant package — no existing tenant loses access |
| 0004 | Connect (`connector_connections`) and Assistant (`assistant_conversations`, `assistant_messages`, `memory_items`, `assistant_actions`, `reminders`, `notifications`, `assistant_preferences`) | new tables only |

## Procedure (staging first, then production)
1. **Backup**: `scripts/backup.sh /var/backups/kokila` and confirm the `.sha256` file; copy off-host.
2. **Dry review**: `docker compose run --rm api alembic upgrade head --sql > /tmp/upgrade.sql` and review.
3. **Stop writers** for the window (`docker compose stop worker beat`); the API can stay up — revisions 0003/0004 are additive.
4. **Migrate**: `docker compose run --rm migrate` (single job; never from every replica).
5. **Verify**:
   ```sql
   SELECT p.code, count(*) FROM plan_capabilities pc JOIN plans p ON p.id = pc.plan_id GROUP BY 1;
   SELECT count(*) FROM tenants;  -- unchanged
   ```
   then sign in as an existing tenant and open Calling Agent; `GET /api/v1/me/capabilities` must show `product.calling_agent: true`.
6. **Restart** worker/beat.

## Rollback
`alembic downgrade 0002` removes capability and Connect/Assistant tables (their data is lost) and restores pre-unification behaviour **only if the matching older application version is deployed**. Prefer restoring the step-1 backup with `scripts/restore.sh` when data written after the upgrade does not matter. Every test run executes upgrade → downgrade → upgrade, and `alembic check` reports no drift.

## Verified locally (27 Nov 2026)
Upgrade from the 17 Nov database preserved existing tenants and their access; downgrade/upgrade cycles of 0003 and 0004 succeeded; 52 backend tests passed on the migrated schema.
