# Inbound Call Flow

1. Caller dials a tenant number registered in **Phone numbers** (configured on Retell with `inbound_webhook_url`).
2. Retell sends signed `call_inbound` → `POST /api/v1/webhooks/retell`. Kokila resolves `route_key + to_number → phone_numbers → tenant + inbound agent`, checks tenant status, published agent and entitlements (`check_call_allowed`: active subscription, minutes, concurrency) and returns `override_agent_id` + metadata. Unknown/blocked numbers get an empty response (configure the provider number without a default agent so such calls are not answered).
3. The agent greets and discloses it is an automated assistant (mandatory guardrail in every prompt).
4. During the call, tool calls (`capture_lead`, `check_availability`, `book_appointment`, `request_human_transfer`, `record_opt_out`) hit `/webhooks/retell/tools/{name}`; each is verified, scoped to the call's tenant, checked against the agent version's `allowed_tools` and executed transactionally. Bookings return `confirmed` only after the authoritative write.
5. `call_started`, `call_ended`, `call_analyzed` are verified, persisted to `webhook_events` (dedupe), then applied by the state machine:
   `created → queued → provider_accepted → ringing → in_progress → {completed | failed | cancelled}`; analysis: `pending → processing → completed`.
6. On end/analysis: contact upserted (per-tenant), lead created/updated by deterministic outcome rules, follow-up tasks for callbacks/handoffs, `do_not_call` → suppression, usage metered once, outbox events emitted (`call.ended`, `call.analyzed`, `call.handoff_requested`).
7. Failures during processing mark the event `failed`; the worker retries up to 6 times. Events that cannot be attributed to a tenant are `ignored` (never guessed).

Handled cases: duplicates, out-of-order events (stale `call_started` after `call_ended` is recorded but not applied), concurrent deliveries, disconnects (`dial_busy`, `dial_no_answer`, `voicemail_reached`, `call_transfer`, `error_*`), unavailable calendar (agent told to offer a callback), missing extracted fields.
