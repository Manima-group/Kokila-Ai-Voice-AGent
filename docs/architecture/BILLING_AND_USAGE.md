# Billing and Usage

- **Plans** (`plans`) are configured by the Super Admin (`PUT /admin/plans`): price (paise, excl. GST), interval, included minutes, optional overage rate (NULL = hard cap), max agents / concurrent calls / users, feature flags (`outbound`, `calendar`, `integrations`). Only the free **trial** (14 days, 30 min, 1 agent, 1 concurrent call, inbound only) is seeded; paid pricing is not invented in code. `python -m app.cli seed-dev` adds clearly labelled `[DEV]` plans for local use only.
- **Entitlements** (`billing/service.py`): checked before agent creation, user invites, campaign start, every outbound dial and inbound routing.
- **Usage**: one `usage_records` row per completed call (`UNIQUE(call_id, kind)`), billable minutes rounded up per call. Mock calls are recorded with `is_mock=true` and excluded from limits and billing.
- **Checkout**: `POST /billing/checkout` creates a Razorpay order server-side (amount = price + GST). The browser's success callback hits `POST /billing/verify`, which verifies `razorpay_signature` with the SDK but only marks the payment `client_verified`.
- **Activation** happens only from a signed `payment.captured` / `order.paid` webhook (`X-Razorpay-Signature`, HMAC-SHA256 with the webhook secret via the SDK), deduplicated by `x-razorpay-event-id`, with amount check. It creates the new current subscription and a GST invoice.
- **Lifecycle**: `trialing → active → past_due/expired` (hourly job), `cancel_at_period_end`, admin plan grants (audited).
- **Provider cost reconciliation**: Retell `combined_cost` stored per call (USD cents) and surfaced in analytics. Converting to INR and margin reporting require an FX source — **not implemented**.
- **Pending**: live Razorpay test-mode run, recurring auto-debit (Razorpay Subscriptions API), overage invoicing at period end, GSTIN on invoices.
