# Outbound Campaign Flow

1. **Create** campaign: purpose, published agent, outbound-enabled caller-ID number, window, days, concurrency (1–100), attempts (1–5), retry delay.
2. **Add contacts** by id or tag — only the tenant's own contacts can be added; numbers are E.164 and unique per tenant (dedupe).
3. **Eligibility** per contact: not suppressed, and a granted, unexpired **voice consent whose purpose equals the campaign purpose**. Re-checked at dial time.
4. **Start** requires: plan feature `outbound`, published agent, outbound-enabled number and — for any non-mock provider — Super-Admin-approved tenant compliance profile and a caller ID designated as `service` (1600-series) or `promotional` (140-series).
5. **Dispatch** (`dispatch_campaign`, every 30 s and via "Dispatch now") stops on: platform kill switch, tenant outbound pause, suspended tenant, campaign not running, outside **09:00–21:00 IST** (hard rule) or the campaign window/days, compliance problems, subscription/minutes/concurrency limits.
6. For each due contact (row-locked, `SKIP LOCKED`): create `call_attempt` with unique `idempotency_key`, **commit**, then call the provider with the same idempotency key and metadata `{kokila_tenant_id, kokila_attempt_id, kokila_campaign_id}`.
7. Provider events update the call; `on_call_finished` sets the attempt outcome and schedules retries only for `no_answer`, `busy`, `failed` while attempts < max. Provider outages schedule a retry. Otherwise the contact is `completed`/`exhausted`.
8. **Opt-out** (`record_opt_out` tool or `do_not_call` outcome) immediately suppresses the number, revokes consents and cancels pending campaign entries across campaigns.
9. Pause / resume / cancel are audited. Campaign completes automatically when no contacts remain open.

Outcomes: `interested, qualified, not_interested, callback_requested, appointment_requested, appointment_confirmed, no_answer, busy, failed, voicemail, human_transfer, do_not_call`.
