# Voice Provider Integration

## Interface (`app/voice/base.py`)
`create_agent`, `update_agent`, `initiate_outbound_call`, `configure_inbound_route`, `terminate_call`, `fetch_call`, `fetch_transcript`, `fetch_usage`, `verify_webhook`, `normalize_event`. Each adapter declares `capabilities` and `supported_languages`; unsupported features raise `UnsupportedCapability` (never silently degrade). Provider failures raise `ProviderError(retryable=...)`.

## RetellProvider (`voice/providers/retell.py`)
- Uses the official **retell-sdk** (checked against v6.2.x signatures): `llm.create/update`, `agent.create/update`, `call.create_phone_call(idempotency_key=…)`, `phone_number.update(inbound_webhook_url=…)`, `call.stop`, `call.retrieve`.
- **Webhook verification:** `Retell.verify(body, api_key, signature)` from the SDK (`x-retell-signature: v=<ms>,d=<hmac>` with a 5-minute window). No custom algorithm. Missing/invalid signatures → 401. There is no "skip verification" setting.
- Languages: `en→en-IN`, `hi→hi-IN`, `kn→kn-IN`. **Telugu (`te-IN`) is not in the SDK's language enum**, so publishing a Telugu-primary agent on Retell fails with `UnsupportedCapability` rather than pretending. Options: Retell custom STT, or a future provider adapter.
- Tools are Retell custom functions pointing to `{PUBLIC_BASE_URL}/api/v1/webhooks/retell/tools/{name}`; payloads are signature-verified and executed server-side with tenant scoping and argument validation. A `transfer_call` tool is added when an escalation number is configured.
- Cost: `call_cost.combined_cost` is stored in `calls.provider_cost_minor` as **USD cents** (provider currency). Never assumed zero; `NULL` means unknown.

## MockVoiceProvider (`voice/providers/mock.py`)
Deterministic, offline, refuses to run when `ENVIRONMENT=production`. Emits Retell-shaped payloads signed with `MOCK_WEBHOOK_SECRET` using the SDK's signing helper, so tests exercise the real verification → dedupe → state-machine path. Calls are flagged `is_mock` and excluded from billing and default analytics.

## Tenant-owned credentials
`POST /api/v1/provider-accounts` stores a tenant's Retell key encrypted (Fernet). Numbers on that account use route key `retell:<account_id>` and webhooks at `/webhooks/retell/accounts/{id}` (verified with that tenant's key).

## Live verification status — PENDING
Requires a Retell account and an Indian DID. Run the checklist in `docs/runbooks/TEST_PLAN.md §Live provider` before enabling any language for production.

## Adding LiveKit/SIP later
Implement `VoiceProvider`, register it in `voice/registry.py`, add its name to `VOICE_PROVIDERS` in `calls/webhooks.py`, and map its events to `NormalizedEvent`.
