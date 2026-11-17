# Database Schema

Generated from SQLAlchemy metadata (`app/db/models.py`). Migrations: `backend/alembic/versions`.

Additional constraints created in migration 0001: `btree_gist` extension; `ex_appointments_no_overlap` EXCLUDE constraint (no overlapping active appointments per calendar); `ck_appointments_time`; partial unique index `uq_subscriptions_current` (one current subscription per tenant); campaign attempt/concurrency CHECKs.

Tenant-owned tables carry a non-null indexed `tenant_id`. `webhook_events`, `outbox_events` and `audit_logs` have a nullable `tenant_id` (resolved after verification / platform-level actions). `plans` and `platform_settings` are platform-wide.


## agent_tools

| Column | Type | Null | Notes |
|---|---|---|---|
| agent_id | UUID | no | FK → agents.id, indexed |
| name | VARCHAR(60) | no |  |
| enabled | BOOLEAN | no |  |
| config | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (agent_id, name)

## agent_versions

| Column | Type | Null | Notes |
|---|---|---|---|
| agent_id | UUID | no | FK → agents.id, indexed |
| version | INTEGER | no |  |
| config | JSONB | no |  |
| created_by | UUID | yes | FK → users.id |
| published_at | DATETIME | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (agent_id, version)

## agents

| Column | Type | Null | Notes |
|---|---|---|---|
| name | VARCHAR(120) | no |  |
| description | TEXT | yes |  |
| template | VARCHAR(60) | no |  |
| status | VARCHAR(20) | no |  |
| provider | VARCHAR(30) | no |  |
| provider_agent_id | VARCHAR(120) | yes | indexed |
| provider_llm_id | VARCHAR(120) | yes |  |
| published_version_id | UUID | yes |  |
| latest_version | INTEGER | no |  |
| sync_status | VARCHAR(20) | no |  |
| sync_error | TEXT | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (tenant_id, name)

## appointments

| Column | Type | Null | Notes |
|---|---|---|---|
| calendar_connection_id | UUID | no | FK → calendar_connections.id, indexed |
| contact_id | UUID | yes | FK → contacts.id |
| lead_id | UUID | yes | FK → leads.id |
| call_id | UUID | yes | FK → calls.id |
| title | VARCHAR(200) | no |  |
| start_at | DATETIME | no | indexed |
| end_at | DATETIME | no |  |
| timezone | VARCHAR(64) | no |  |
| status | VARCHAR(25) | no | indexed |
| idempotency_key | VARCHAR(120) | no |  |
| external_event_id | VARCHAR(200) | yes |  |
| failure_reason | TEXT | yes |  |
| notes | TEXT | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (tenant_id, idempotency_key)

## audit_logs

| Column | Type | Null | Notes |
|---|---|---|---|
| tenant_id | UUID | yes | FK → tenants.id, indexed |
| actor_user_id | UUID | yes | indexed |
| actor_type | VARCHAR(20) | no |  |
| action | VARCHAR(80) | no | indexed |
| resource_type | VARCHAR(60) | yes |  |
| resource_id | VARCHAR(80) | yes |  |
| ip_address | VARCHAR(64) | yes |  |
| details | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## background_job_failures

| Column | Type | Null | Notes |
|---|---|---|---|
| tenant_id | UUID | yes | indexed |
| task_name | VARCHAR(120) | no |  |
| reference | VARCHAR(200) | yes |  |
| error | TEXT | no |  |
| resolved | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## calendar_connections

| Column | Type | Null | Notes |
|---|---|---|---|
| provider | VARCHAR(20) | no |  |
| label | VARCHAR(120) | no |  |
| calendar_id | VARCHAR(300) | no |  |
| encrypted_tokens | TEXT | yes |  |
| token_expires_at | DATETIME | yes |  |
| status | VARCHAR(20) | no |  |
| slot_minutes | INTEGER | no |  |
| business_hours | JSONB | no |  |
| timezone | VARCHAR(64) | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## call_attempts

| Column | Type | Null | Notes |
|---|---|---|---|
| campaign_id | UUID | no | FK → campaigns.id, indexed |
| campaign_contact_id | UUID | no | FK → campaign_contacts.id |
| attempt_no | INTEGER | no |  |
| idempotency_key | VARCHAR(120) | no | unique |
| status | VARCHAR(20) | no | indexed |
| provider_call_id | VARCHAR(120) | yes |  |
| call_id | UUID | yes |  |
| outcome | VARCHAR(40) | yes |  |
| error | TEXT | yes |  |
| dispatched_at | DATETIME | yes |  |
| meta | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (campaign_contact_id, attempt_no)

## call_events

| Column | Type | Null | Notes |
|---|---|---|---|
| call_id | UUID | no | FK → calls.id, indexed |
| event_type | VARCHAR(40) | no |  |
| dedupe_key | VARCHAR(200) | no | unique |
| occurred_at | DATETIME | yes |  |
| applied | BOOLEAN | no |  |
| note | VARCHAR(200) | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## call_recordings

| Column | Type | Null | Notes |
|---|---|---|---|
| call_id | UUID | no | FK → calls.id, indexed |
| storage_url | TEXT | no |  |
| consent_obtained | BOOLEAN | no |  |
| expires_at | DATETIME | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## calls

| Column | Type | Null | Notes |
|---|---|---|---|
| provider | VARCHAR(30) | no |  |
| provider_call_id | VARCHAR(120) | no |  |
| direction | VARCHAR(10) | no |  |
| agent_id | UUID | yes | FK → agents.id, indexed |
| agent_version_id | UUID | yes |  |
| phone_number_id | UUID | yes | FK → phone_numbers.id |
| contact_id | UUID | yes | FK → contacts.id, indexed |
| campaign_id | UUID | yes | FK → campaigns.id, indexed |
| call_attempt_id | UUID | yes |  |
| from_number | VARCHAR(20) | yes |  |
| to_number | VARCHAR(20) | yes |  |
| status | VARCHAR(20) | no | indexed |
| analysis_status | VARCHAR(20) | no |  |
| started_at | DATETIME | yes | indexed |
| ended_at | DATETIME | yes |  |
| duration_seconds | INTEGER | no |  |
| disconnection_reason | VARCHAR(80) | yes |  |
| outcome | VARCHAR(40) | yes | indexed |
| summary | TEXT | yes |  |
| sentiment | VARCHAR(20) | yes |  |
| transcript | TEXT | yes |  |
| transcript_segments | JSONB | yes |  |
| extracted | JSONB | no |  |
| language | VARCHAR(10) | yes |  |
| recording_url | TEXT | yes |  |
| provider_cost_minor | INTEGER | yes |  |
| handoff_requested | BOOLEAN | no |  |
| is_mock | BOOLEAN | no |  |
| last_event_at | DATETIME | yes |  |
| row_version | INTEGER | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (provider, provider_call_id)

## campaign_contacts

| Column | Type | Null | Notes |
|---|---|---|---|
| campaign_id | UUID | no | FK → campaigns.id, indexed |
| contact_id | UUID | no | FK → contacts.id |
| status | VARCHAR(20) | no | indexed |
| ineligible_reason | VARCHAR(80) | yes |  |
| attempts | INTEGER | no |  |
| next_attempt_at | DATETIME | yes | indexed |
| last_outcome | VARCHAR(40) | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (campaign_id, contact_id)

## campaigns

| Column | Type | Null | Notes |
|---|---|---|---|
| name | VARCHAR(200) | no |  |
| purpose | VARCHAR(60) | no |  |
| agent_id | UUID | no | FK → agents.id |
| from_phone_number_id | UUID | no | FK → phone_numbers.id |
| status | VARCHAR(20) | no | indexed |
| window_start | VARCHAR(5) | no |  |
| window_end | VARCHAR(5) | no |  |
| timezone | VARCHAR(64) | no |  |
| days_of_week | JSONB | no |  |
| max_concurrency | INTEGER | no |  |
| max_attempts | INTEGER | no |  |
| retry_delay_minutes | INTEGER | no |  |
| start_at | DATETIME | yes |  |
| end_at | DATETIME | yes |  |
| description | TEXT | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## contact_consents

| Column | Type | Null | Notes |
|---|---|---|---|
| contact_id | UUID | no | FK → contacts.id, indexed |
| purpose | VARCHAR(60) | no |  |
| channel | VARCHAR(20) | no |  |
| status | VARCHAR(20) | no |  |
| source | VARCHAR(60) | no |  |
| evidence | TEXT | yes |  |
| granted_at | DATETIME | no |  |
| expires_at | DATETIME | yes |  |
| revoked_at | DATETIME | yes |  |
| recording_consent | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## contacts

| Column | Type | Null | Notes |
|---|---|---|---|
| phone_e164 | VARCHAR(20) | no |  |
| name | VARCHAR(200) | yes |  |
| email | VARCHAR(320) | yes |  |
| language | VARCHAR(10) | yes |  |
| tags | JSONB | no |  |
| attributes | JSONB | no |  |
| source | VARCHAR(30) | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (tenant_id, phone_e164)

## data_retention_policies

| Column | Type | Null | Notes |
|---|---|---|---|
| resource | VARCHAR(40) | no |  |
| retain_days | INTEGER | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (tenant_id, resource)

## deletion_requests

| Column | Type | Null | Notes |
|---|---|---|---|
| contact_id | UUID | yes |  |
| phone_e164 | VARCHAR(20) | yes |  |
| status | VARCHAR(20) | no |  |
| requested_by | UUID | yes |  |
| reason | TEXT | yes |  |
| completed_at | DATETIME | yes |  |
| summary | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## integration_connections

| Column | Type | Null | Notes |
|---|---|---|---|
| kind | VARCHAR(20) | no |  |
| name | VARCHAR(120) | no |  |
| target_url | TEXT | yes |  |
| encrypted_secret | TEXT | yes |  |
| event_types | JSONB | no |  |
| status | VARCHAR(20) | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## invoices

| Column | Type | Null | Notes |
|---|---|---|---|
| number | VARCHAR(40) | no | unique |
| payment_id | UUID | yes | FK → payment_transactions.id, unique |
| period_start | DATETIME | no |  |
| period_end | DATETIME | no |  |
| subtotal_minor | INTEGER | no |  |
| tax_minor | INTEGER | no |  |
| total_minor | INTEGER | no |  |
| currency | VARCHAR(3) | no |  |
| status | VARCHAR(20) | no |  |
| line_items | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## knowledge_documents

| Column | Type | Null | Notes |
|---|---|---|---|
| source_id | UUID | no | FK → knowledge_sources.id, indexed |
| title | VARCHAR(300) | no |  |
| content | TEXT | no |  |
| checksum | VARCHAR(64) | no |  |
| status | VARCHAR(20) | no |  |
| flagged_injection | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## knowledge_sources

| Column | Type | Null | Notes |
|---|---|---|---|
| agent_id | UUID | yes | FK → agents.id, indexed |
| name | VARCHAR(200) | no |  |
| kind | VARCHAR(20) | no |  |
| provider_kb_id | VARCHAR(120) | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## lead_activities

| Column | Type | Null | Notes |
|---|---|---|---|
| lead_id | UUID | no | FK → leads.id, indexed |
| kind | VARCHAR(20) | no |  |
| body | TEXT | yes |  |
| user_id | UUID | yes | FK → users.id |
| call_id | UUID | yes | FK → calls.id |
| due_at | DATETIME | yes |  |
| completed_at | DATETIME | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## leads

| Column | Type | Null | Notes |
|---|---|---|---|
| contact_id | UUID | no | FK → contacts.id, indexed |
| status | VARCHAR(20) | no | indexed |
| score | INTEGER | no |  |
| source | VARCHAR(30) | no |  |
| assigned_to | UUID | yes | FK → users.id, indexed |
| last_outcome | VARCHAR(40) | yes |  |
| notes | TEXT | yes |  |
| next_follow_up_at | DATETIME | yes |  |
| qualification | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## outbox_events

| Column | Type | Null | Notes |
|---|---|---|---|
| tenant_id | UUID | yes | FK → tenants.id, indexed |
| event_type | VARCHAR(60) | no | indexed |
| payload | JSONB | no |  |
| status | VARCHAR(20) | no | indexed |
| attempts | INTEGER | no |  |
| next_attempt_at | DATETIME | no | indexed |
| last_error | TEXT | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## payment_transactions

| Column | Type | Null | Notes |
|---|---|---|---|
| razorpay_order_id | VARCHAR(60) | no | unique |
| razorpay_payment_id | VARCHAR(60) | yes | unique |
| plan_id | UUID | yes | FK → plans.id |
| amount_minor | INTEGER | no |  |
| currency | VARCHAR(3) | no |  |
| status | VARCHAR(25) | no |  |
| purpose | VARCHAR(30) | no |  |
| captured_at | DATETIME | yes |  |
| meta | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## phone_numbers

| Column | Type | Null | Notes |
|---|---|---|---|
| provider | VARCHAR(30) | no |  |
| provider_account_id | UUID | yes | FK → provider_accounts.id |
| route_key | VARCHAR(80) | no |  |
| e164 | VARCHAR(20) | no | indexed |
| label | VARCHAR(120) | yes |  |
| number_type | VARCHAR(20) | no |  |
| inbound_agent_id | UUID | yes | FK → agents.id |
| outbound_enabled | BOOLEAN | no |  |
| status | VARCHAR(20) | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (route_key, e164)

## plans

| Column | Type | Null | Notes |
|---|---|---|---|
| code | VARCHAR(40) | no | unique |
| name | VARCHAR(100) | no |  |
| price_minor | INTEGER | no |  |
| currency | VARCHAR(3) | no |  |
| interval_months | INTEGER | no |  |
| included_minutes | INTEGER | no |  |
| overage_per_minute_minor | INTEGER | yes |  |
| max_agents | INTEGER | no |  |
| max_concurrent_calls | INTEGER | no |  |
| max_users | INTEGER | no |  |
| features | JSONB | no |  |
| is_active | BOOLEAN | no |  |
| is_public | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## platform_settings

| Column | Type | Null | Notes |
|---|---|---|---|
| key | VARCHAR(100) | no | PK |
| value | JSONB | no |  |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## provider_accounts

| Column | Type | Null | Notes |
|---|---|---|---|
| provider | VARCHAR(30) | no |  |
| label | VARCHAR(120) | no |  |
| encrypted_api_key | TEXT | no |  |
| status | VARCHAR(20) | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## refresh_tokens

| Column | Type | Null | Notes |
|---|---|---|---|
| user_id | UUID | no | FK → users.id, indexed |
| token_hash | VARCHAR(64) | no | unique |
| family_id | UUID | no | indexed |
| expires_at | DATETIME | no |  |
| revoked_at | DATETIME | yes |  |
| replaced_by | UUID | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## subscriptions

| Column | Type | Null | Notes |
|---|---|---|---|
| plan_id | UUID | no | FK → plans.id |
| status | VARCHAR(20) | no | indexed |
| current_period_start | DATETIME | no |  |
| current_period_end | DATETIME | no |  |
| cancel_at_period_end | BOOLEAN | no |  |
| is_current | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

## suppression_entries

| Column | Type | Null | Notes |
|---|---|---|---|
| phone_e164 | VARCHAR(20) | no |  |
| reason | VARCHAR(40) | no |  |
| source | VARCHAR(40) | no |  |
| attributes | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (tenant_id, phone_e164)

## tenant_memberships

| Column | Type | Null | Notes |
|---|---|---|---|
| tenant_id | UUID | no | FK → tenants.id, indexed |
| user_id | UUID | no | FK → users.id, indexed |
| role | VARCHAR(30) | no |  |
| is_active | BOOLEAN | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

Composite unique: (tenant_id, user_id)

## tenants

| Column | Type | Null | Notes |
|---|---|---|---|
| name | VARCHAR(200) | no |  |
| slug | VARCHAR(80) | no | unique |
| status | VARCHAR(20) | no |  |
| timezone | VARCHAR(64) | no |  |
| industry | VARCHAR(80) | yes |  |
| outbound_paused | BOOLEAN | no |  |
| compliance | JSONB | no |  |
| settings | JSONB | no |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## usage_records

| Column | Type | Null | Notes |
|---|---|---|---|
| call_id | UUID | yes | FK → calls.id |
| kind | VARCHAR(30) | no |  |
| quantity | NUMERIC(12, 2) | no |  |
| provider_cost_minor | INTEGER | yes |  |
| is_mock | BOOLEAN | no |  |
| occurred_at | DATETIME | no | indexed |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| tenant_id | UUID | no | FK → tenants.id, indexed |

Composite unique: (call_id, kind)

## users

| Column | Type | Null | Notes |
|---|---|---|---|
| email | VARCHAR(320) | no | unique, indexed |
| password_hash | VARCHAR(255) | no |  |
| full_name | VARCHAR(200) | no |  |
| is_superadmin | BOOLEAN | no |  |
| is_active | BOOLEAN | no |  |
| failed_logins | INTEGER | no |  |
| locked_until | DATETIME | yes |  |
| last_login_at | DATETIME | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

## webhook_events

| Column | Type | Null | Notes |
|---|---|---|---|
| tenant_id | UUID | yes | FK → tenants.id, indexed |
| source | VARCHAR(30) | no |  |
| dedupe_key | VARCHAR(200) | no | unique |
| event_type | VARCHAR(60) | no |  |
| status | VARCHAR(20) | no |  |
| attempts | INTEGER | no |  |
| payload | JSONB | no |  |
| error | TEXT | yes |  |
| processed_at | DATETIME | yes |  |
| id | UUID | no | PK |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
