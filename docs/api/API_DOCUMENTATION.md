# API Documentation

Base path `/api/v1`. Interactive docs: `GET /api/docs` (Swagger UI); machine-readable spec: `docs/api/openapi.json`.

## Conventions

- **Auth:** `Authorization: Bearer <access_token>` (15 min). Refresh via `POST /auth/refresh` using the httpOnly `kokila_refresh` cookie (rotated on every use; reuse revokes the token family).
- **Tenant:** `X-Tenant-ID: <uuid>` — validated server-side against the caller's active membership. Required when a user belongs to more than one organization.
- **Errors:** `{"error": {"code": "...", "message": "..."}}` with HTTP 400/401/402/403/404/409/422/429/502/503. Other tenants' resources return 404.
- **Pagination:** `?limit=&offset=` (max 200) → `{items, total, limit, offset}`.
- **Webhooks (inbound):** `/webhooks/retell` (+ `/accounts/{id}` for tenant-owned Retell keys), `/webhooks/retell/tools/{tool}`, `/webhooks/razorpay`. All require valid provider signatures.
- **Webhooks (outbound):** Kokila signs deliveries: `X-Kokila-Signature: sha256=HMAC_SHA256(secret, "{X-Kokila-Timestamp}." + body)`.

## Examples

```bash
# Register (creates organization + COMPANY_ADMIN + 14-day trial)
curl -X POST $API/api/v1/auth/register -H 'content-type: application/json' \
  -d '{"company_name":"Acme Realty","full_name":"Asha","email":"asha@acme.in","password":"Str0ngPassw0rd"}'

# Create an agent from a template
curl -X POST $API/api/v1/agents -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Sales Desk","template":"real_estate"}'

# Publish version 1 (syncs to the voice provider)
curl -X POST $API/api/v1/agents/$AGENT/versions/1/publish -H "Authorization: Bearer $TOKEN"

# Record consent, then start a campaign
curl -X POST $API/api/v1/contacts/$CONTACT/consents -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"purpose":"sales","source":"web_form","evidence":"Form #4411, 2026-11-01"}'
curl -X POST $API/api/v1/campaigns/$CAMPAIGN/start -H "Authorization: Bearer $TOKEN"
```

## Endpoints


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
