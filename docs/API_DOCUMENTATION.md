# API Documentation

Base path `/api/v1`. Swagger UI: `GET /api/docs`. Machine-readable spec: `docs/openapi.json` (regenerate after route changes).

## Conventions

- **Auth:** `Authorization: Bearer <access_token>` (15 min); refresh with `POST /auth/refresh` using the httpOnly `kokila_refresh` cookie (rotated; reuse revokes the family).
- **Tenant:** `X-Tenant-ID` validated against the caller's membership. Personal-assistant data is additionally scoped to the user.
- **Entitlements:** product/feature routes return `403 capability_disabled` when the organization is not licensed, `402 subscription_inactive` when the subscription lapsed. `GET /me/capabilities` lists effective capabilities.
- **Errors:** `{"error": {"code", "message"}}`; foreign resources return 404.
- **Pagination:** `limit`/`offset` (max 200) → `{items,total,limit,offset}`.
- **Webhooks in:** `/webhooks/retell[/accounts/{id}]`, `/webhooks/retell/tools/{tool}`, `/webhooks/razorpay` (signature required). **Out:** `X-Kokila-Signature: sha256=HMAC(secret, ts + '.' + body)`.

## Key flows

```bash
# Product access for the signed-in organization
curl $API/api/v1/me/capabilities -H "Authorization: Bearer $T" -H "X-Tenant-ID: $TENANT"

# Connect ERPNext (verified live before it counts as connected)
curl -X POST $API/api/v1/connect/connections -H "Authorization: Bearer $T" -H 'content-type: application/json' \
  -d '{"connector_key":"erpnext","name":"Main ERP","base_url":"https://erp.example.com","credentials":{"api_key":"…","api_secret":"…"}}'

# Run a governed metric (no LLM needed)
curl -X POST $API/api/v1/connect/metrics/run -H "Authorization: Bearer $T" -H 'content-type: application/json' \
  -d '{"metric_key":"erpnext.sales_total","params":{"date_from":"2026-11-01","date_to":"2026-11-27"}}'

# Super Admin: give a client the Business Assistant only
curl -X PATCH $API/api/v1/admin/tenants/$TENANT/capabilities -H "Authorization: Bearer $ROOT" -H 'content-type: application/json' \
  -d '{"changes":[{"key":"product.calling_agent","enabled":false}],"expected_revision":1,"reason":"Assistant-only contract"}'
```

## Endpoints (144 operations)


### admin

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/admin/audit-logs` | Platform Audit |
| GET | `/api/v1/admin/health` | Platform Health |
| GET | `/api/v1/admin/kill-switch` | Get Kill Switch |
| PUT | `/api/v1/admin/kill-switch` | Set Kill Switch |
| GET | `/api/v1/admin/plans` | List Plans |
| PUT | `/api/v1/admin/plans` | Upsert Plan |
| GET | `/api/v1/admin/tenants` | Tenants |
| GET | `/api/v1/admin/tenants/{tenant_id}` | Tenant Detail |
| POST | `/api/v1/admin/tenants/{tenant_id}/compliance-decision` | Compliance Decision |
| POST | `/api/v1/admin/tenants/{tenant_id}/plan` | Assign Plan |
| POST | `/api/v1/admin/tenants/{tenant_id}/status` | Set Status |

### agents

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/agents` | List Agents |
| POST | `/api/v1/agents` | Create Agent |
| DELETE | `/api/v1/agents/knowledge/documents/{doc_id}` | Delete Doc |
| GET | `/api/v1/agents/knowledge/sources` | List Sources |
| POST | `/api/v1/agents/knowledge/sources` | Create Source |
| GET | `/api/v1/agents/knowledge/sources/{source_id}/documents` | List Docs |
| POST | `/api/v1/agents/knowledge/sources/{source_id}/documents` | Add Doc |
| GET | `/api/v1/agents/templates` | Templates |
| GET | `/api/v1/agents/{agent_id}` | Get Agent |
| POST | `/api/v1/agents/{agent_id}/archive` | Archive |
| GET | `/api/v1/agents/{agent_id}/versions` | Versions |
| POST | `/api/v1/agents/{agent_id}/versions` | New Version |
| POST | `/api/v1/agents/{agent_id}/versions/{version}/publish` | Publish |

### analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/analytics/agents` | Agent Performance |
| GET | `/api/v1/analytics/campaigns` | Campaign Performance |
| GET | `/api/v1/analytics/overview` | Overview |

### appointments

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/appointments` | List Appointments |
| POST | `/api/v1/appointments` | Create Appointment |
| GET | `/api/v1/appointments/availability` | Availability |
| POST | `/api/v1/appointments/{appointment_id}/cancel` | Cancel Appointment |
| POST | `/api/v1/appointments/{appointment_id}/reschedule` | Reschedule Appointment |
| GET | `/api/v1/calendar-connections` | List Connections |
| POST | `/api/v1/calendar-connections` | Create Internal |

### assistant

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/assistant/actions` | Actions |
| POST | `/api/v1/assistant/actions/{aid}/decision` | Decide |
| GET | `/api/v1/assistant/config` | Config |
| GET | `/api/v1/assistant/conversations` | Conversations |
| POST | `/api/v1/assistant/conversations` | New Conversation |
| DELETE | `/api/v1/assistant/conversations/{cid}` | Delete Conversation |
| GET | `/api/v1/assistant/conversations/{cid}/messages` | Messages |
| POST | `/api/v1/assistant/conversations/{cid}/messages` | Send |
| GET | `/api/v1/assistant/memory` | Memory |
| POST | `/api/v1/assistant/memory` | Add Memory |
| DELETE | `/api/v1/assistant/memory/{mid}` | Delete Memory |
| POST | `/api/v1/assistant/memory/{mid}/approve` | Approve Memory |
| PATCH | `/api/v1/assistant/preferences` | Update Prefs |
| GET | `/api/v1/assistant/reminders` | Reminders |
| POST | `/api/v1/assistant/reminders` | Add Reminder |
| POST | `/api/v1/assistant/reminders/{rid}/cancel` | Cancel Reminder |

### audit

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/audit-logs` | Audit Logs |
| POST | `/api/v1/deletion-requests` | Request Deletion |
| GET | `/api/v1/retention-policies` | List Policies |
| PUT | `/api/v1/retention-policies` | Set Policy |

### auth

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/logout` | Logout |
| GET | `/api/v1/auth/me` | Me |
| POST | `/api/v1/auth/refresh` | Refresh |
| POST | `/api/v1/auth/register` | Register |

### billing

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/billing/cancel` | Cancel Subscription |
| POST | `/api/v1/billing/checkout` | Checkout |
| GET | `/api/v1/billing/invoices` | Invoices |
| GET | `/api/v1/billing/payments` | Payments |
| GET | `/api/v1/billing/plans` | Plans |
| GET | `/api/v1/billing/subscription` | Subscription |
| GET | `/api/v1/billing/usage` | Usage |
| POST | `/api/v1/billing/verify` | Verify |

### calls

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/calls` | List Calls |
| POST | `/api/v1/calls/simulate` | Simulate |
| POST | `/api/v1/calls/test` | Test Call |
| GET | `/api/v1/calls/{call_id}` | Get Call |
| POST | `/api/v1/calls/{call_id}/handoff` | Mark Handoff |
| POST | `/api/v1/calls/{call_id}/terminate` | Terminate |

### campaigns

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/campaigns` | List Campaigns |
| POST | `/api/v1/campaigns` | Create Campaign |
| GET | `/api/v1/campaigns/{campaign_id}` | Get Campaign |
| GET | `/api/v1/campaigns/{campaign_id}/attempts` | Attempts |
| POST | `/api/v1/campaigns/{campaign_id}/cancel` | Cancel |
| GET | `/api/v1/campaigns/{campaign_id}/contacts` | Campaign Contacts |
| POST | `/api/v1/campaigns/{campaign_id}/contacts` | Add Contacts |
| POST | `/api/v1/campaigns/{campaign_id}/dispatch-now` | Dispatch Now |
| POST | `/api/v1/campaigns/{campaign_id}/pause` | Pause |
| POST | `/api/v1/campaigns/{campaign_id}/resume` | Resume |
| POST | `/api/v1/campaigns/{campaign_id}/start` | Start |

### connect

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/connect/connections` | List Connections |
| POST | `/api/v1/connect/connections` | Create Connection |
| POST | `/api/v1/connect/connections/{connection_id}/revoke` | Revoke |
| POST | `/api/v1/connect/connections/{connection_id}/verify` | Verify |
| GET | `/api/v1/connect/connectors` | Connectors |
| GET | `/api/v1/connect/metrics` | Metrics |
| POST | `/api/v1/connect/metrics/run` | Run |

### contacts

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/contacts` | List Contacts |
| POST | `/api/v1/contacts` | Create Contact |
| POST | `/api/v1/contacts/import` | Import Contacts |
| GET | `/api/v1/contacts/{contact_id}` | Get Contact |
| PATCH | `/api/v1/contacts/{contact_id}` | Update Contact |
| POST | `/api/v1/contacts/{contact_id}/consents` | Add Consent |
| POST | `/api/v1/contacts/{contact_id}/consents/{consent_id}/revoke` | Revoke Consent |
| GET | `/api/v1/suppression` | List Suppression |
| POST | `/api/v1/suppression` | Add Suppression |
| DELETE | `/api/v1/suppression/{entry_id}` | Remove Suppression |

### integrations

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/integrations` | List Connections |
| POST | `/api/v1/integrations` | Create Connection |
| GET | `/api/v1/integrations/deliveries` | Deliveries |
| GET | `/api/v1/integrations/event-types` | Event Types |
| GET | `/api/v1/integrations/google/authorize` | Google Authorize |
| GET | `/api/v1/integrations/google/callback` | Google Callback |
| POST | `/api/v1/integrations/{connection_id}/disable` | Disable |

### leads

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/leads` | List Leads |
| POST | `/api/v1/leads` | Create Lead |
| GET | `/api/v1/leads/tasks/open` | Open Tasks |
| GET | `/api/v1/leads/{lead_id}` | Get Lead |
| PATCH | `/api/v1/leads/{lead_id}` | Update Lead |
| POST | `/api/v1/leads/{lead_id}/activities` | Add Activity |
| POST | `/api/v1/leads/{lead_id}/activities/{activity_id}/complete` | Complete Task |
| POST | `/api/v1/leads/{lead_id}/assign` | Assign |

### notifications

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/notifications` | List Notifications |
| POST | `/api/v1/notifications/read-all` | Read All |

### ops

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Health |
| GET | `/ready` | Ready |

### organization

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/tenants/current` | Current |
| PATCH | `/api/v1/tenants/current` | Update Current |
| PUT | `/api/v1/tenants/current/compliance` | Set Compliance |
| POST | `/api/v1/tenants/current/outbound-pause` | Pause Outbound |
| GET | `/api/v1/users` | Members |
| POST | `/api/v1/users` | Invite |
| POST | `/api/v1/users/{user_id}/deactivate` | Deactivate |
| PATCH | `/api/v1/users/{user_id}/role` | Change Role |

### platform

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/admin/capabilities` | Catalog |
| PUT | `/api/v1/admin/capabilities/{key}/control` | Set Control |
| GET | `/api/v1/admin/plans/{code}/capabilities` | Plan Caps |
| PUT | `/api/v1/admin/plans/{code}/capabilities` | Set Plan Caps |
| GET | `/api/v1/admin/tenants/{tenant_id}/capabilities` | Tenant Caps |
| PATCH | `/api/v1/admin/tenants/{tenant_id}/capabilities` | Update Tenant Caps |
| GET | `/api/v1/me/capabilities` | My Capabilities |

### telephony

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/phone-numbers` | List Numbers |
| POST | `/api/v1/phone-numbers` | Add Number |
| PATCH | `/api/v1/phone-numbers/{number_id}` | Update Number |
| GET | `/api/v1/provider-accounts` | List Accounts |
| POST | `/api/v1/provider-accounts` | Add Account |

### webhooks

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/webhooks/razorpay` | Razorpay Webhook |
| POST | `/api/v1/webhooks/{provider}` | Provider Webhook |
| POST | `/api/v1/webhooks/{provider}/accounts/{account_id}` | Provider Account Webhook |
| POST | `/api/v1/webhooks/{provider}/tools/{tool}` | Tool Call |
