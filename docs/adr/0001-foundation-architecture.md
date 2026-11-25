# ADR 0001 — Foundation architecture

Status: accepted (25 Nov 2026)

## Context
The repository was empty. Spec §26.1 fixes the canonical stack, and §2 calls for a modular monolith with a separate media plane.

## Decisions
1. **Modular monolith** (`services/api`) with domain packages (auth, platform, assistant, memory, identity, tools,
   providers). The Celery worker shares the image. A separate media worker comes with the realtime path.
2. **Isolation in the database**: every tenant table has forced RLS keyed on transaction-local settings
   (`kokila.tenant_id`, `kokila.user_id`, `kokila.scope`). The app connects as `kokila_app` (NOBYPASSRLS) and
   migrations run as `kokila_owner` under an advisory lock. Platform scope can manage control-plane rows only. It can
   never read conversations, messages, memory or sessions.
3. **One entitlement policy** (`app/platform/entitlements.py`) is evaluated live on every request and re-evaluated
   before side effects. Overrides, plans and kill switches are the only writable sources. Dependencies are normalized
   edges, and conflicts fail atomically.
4. **No transaction across provider calls**: `TenantContext.release()` / `reattach()` commit before a reasoning call
   and re-validate membership and policy afterwards.
5. **Provider adapters** behind `ReasoningRouter`, with model IDs from configuration. `dev_mock` is rejected outside
   development/test, and its replies are labelled.
6. **Web BFF**: tokens live only in HttpOnly SameSite=Strict cookies. The browser calls `/api/k/*` with an
   `X-Kokila-Client` header (CSRF defence).
7. **Browser speech first, realtime second**: the Web Speech API gives a credential-free working voice path. LiveKit +
   OpenAI Realtime is the target path once credentials exist. Mute state is server-authoritative in both.

## Deviations
* Python 3.13 is installed in the build container. The project pins 3.12 via uv (`requires-python >=3.12,<3.13`).
* shadcn/ui isn't used yet. Components are minimal Tailwind v4 utilities pending Manima Hub tokens.
