# Integration Guide (Kokila Connect)

Connections are **read-only by default**, stored encrypted, and marked **Connected** only after a live verification succeeds. Planned connectors show "Coming soon" and cannot be connected or faked.

| Connector | Status | Auth | What Kokila reads/does |
|---|---|---|---|
| Manima Hub | Adapter implemented; **Hub-side endpoints pending** | Bearer token | Metrics via the Kokila Connect host protocol |
| ERPNext | Implemented; verified against a local test double only | API key + secret | Sales invoices, receivables, stock (Bin) |
| Google Calendar | Implemented (OAuth) | OAuth 2.0 | Availability and bookings (Calling Agent) |
| n8n | Implemented (signed webhooks) | HMAC secret | Receives Kokila events |
| Zoho CRM, Tally, Salesforce, SAP, Dynamics, Gmail, Outlook, WhatsApp, Teams, Slack | **Planned** | — | Not yet implemented; need vendor sandbox accounts |

## ERPNext
1. In ERPNext create a user with read access to Sales Invoice, Company and Bin (a reporting role). Open the user → **API Access → Generate Keys**.
2. Kokila → **Integrations → ERPNext → Connect**: site URL (`https://erp.example.com`), API key, API secret → **Save and test**.
3. Kokila calls `GET /api/method/frappe.auth.get_logged_user` with `Authorization: token <key>:<secret>`. Success → Connected (shows the ERPNext user). Failure → Needs attention with the reason; the connection is never used.
4. Metrics (Business Assistant quick reports and the `run_metric` tool):
   - `erpnext.sales_total` — net sales = Σ `base_net_total` of submitted Sales Invoices by `posting_date` (returns negative); also gross incl. tax, invoice and return counts, daily chart.
   - `erpnext.sales_compare` — same, vs. the previous period of equal length.
   - `erpnext.overdue_invoices` — submitted, `outstanding_amount > 0`, `due_date < today`.
   - `erpnext.customer_outstanding` — outstanding grouped by customer.
   - `erpnext.low_stock` — Bin rows with `actual_qty <= threshold` (default 10).
   Results larger than 20 000 rows are refused (narrow the period) rather than truncated silently.

## Manima Hub — Kokila Connect host protocol
Manima Hub (or any Manima app) implements two endpoints; Kokila does the rest.
```
GET  {base}/kokila/v1/manifest          → {"host": "manima-hub", "metrics": [{"key": "sales_total", "title": "Sales"}]}
POST {base}/kokila/v1/metrics/{key}     body {"date_from","date_to",...} → MetricResult JSON
Authorization: Bearer <scoped read-only token>
```
MetricResult: `{metric, title, definition, period:{from,to}, kpis:[{label,value,unit}], table:{columns,rows}|null, chart:{type,x,series:[{name,values}]}|null, warnings:[], source:{...}}`.
**Blocker:** these endpoints do not exist in Manima Hub yet; until they do, verification returns "does not expose the Kokila Connect endpoint".

## Outbound webhooks / n8n
Calling Agent → Automations: add an HTTPS endpoint and copy the one-time signing secret. Verify `X-Kokila-Signature = sha256=HMAC_SHA256(secret, "{X-Kokila-Timestamp}." + body)`. Events: `call.*`, `call.handoff_requested`, `appointment.*`, `contact.opted_out`. Failed deliveries retry with backoff (max 8) then dead-letter.

## Adding a connector
1. Add a `ConnectorSpec` in `app/connect/registry.py` (adapter `planned` until real).
2. Implement an adapter with `verify()` and read methods (timeouts, 401/403 → `connector_unauthorized`, no secrets in errors).
3. Add governed metrics with documented formulas in `app/connect/metrics.py`.
4. Add contract tests with `httpx.MockTransport`, then verify against the vendor's sandbox before marking it implemented.
