# Security Guide

## Controls implemented
| Area | Control |
|---|---|
| Passwords | argon2id (`argon2-cffi`), min 10 chars with letters+digits, 5-failure lockout for 15 min |
| Sessions | 15-min HS256 access JWT; 14-day refresh token in httpOnly `SameSite=Strict` cookie scoped to `/api/v1/auth`, stored hashed, rotated on use; reuse revokes the whole family |
| Production config guard | App refuses to start in `production` with weak `JWT_SECRET`, default `ENCRYPTION_KEY`, mock voice provider, missing Retell key, or insecure cookies |
| Authorization | Server-side RBAC on every endpoint; tenant from validated membership; 404 for foreign ids; operators limited to assigned leads; viewers get masked numbers and no transcripts |
| Webhooks | Retell: SDK `verify` (HMAC + 5-min window). Razorpay: SDK HMAC verification. Missing/invalid → 401. No bypass flag. Raw events retained 30 days (`RAW_EVENT_RETENTION_DAYS`) |
| Outbound webhooks | Per-endpoint secret (shown once, stored encrypted), `sha256` HMAC over `timestamp.body`, HTTPS required in production |
| Secrets at rest | Provider API keys, Google tokens, webhook secrets encrypted with Fernet (`ENCRYPTION_KEY`) |
| Rate limiting | Redis fixed window on auth and webhook routes (fails open with a warning if Redis is down) |
| Transport/headers | HTTPS via Caddy + HSTS; `X-Frame-Options: DENY`, `nosniff`, strict referrer; strict CORS list |
| Logging | JSON logs with phone/email redaction; payloads never logged |
| Audit | `audit_logs` for auth events, config changes, consent, campaigns, billing, erasure and all super-admin actions |
| Prompt injection | Guardrail system prompt (automated-identity disclosure, no invented prices/bookings, opt-out handling, knowledge treated as data); knowledge docs with injection patterns are flagged and excluded; tool args validated and clipped; privileged actions only via server-side tools |
| Privacy | Retention policies (transcripts, recordings, call events) enforced daily; contact erasure redacts call content, deletes PII/leads/consents, and keeps a suppression entry so the person is never re-dialled |

## Unified-platform controls (27 Nov 2026)
| Area | Control |
|---|---|
| Product licensing | Capability registry enforced server-side on every router, inbound routing, dispatch, metrics and assistant tools; default deny; 403 `capability_disabled` |
| Admin changes | Revision-checked, dependency-validated, reasoned and audited; platform-wide capability kill switches |
| Personal data | Assistant conversations, memory, reminders and actions scoped to tenant **and** user; personal mode has no business tools |
| Connectors | Fernet-encrypted credentials never returned by the API; connection counts only after live verification; read-only scopes by default; SSRF guard (HTTPS + public IP in production); 20 000-row cap |
| AI actions | Writes require approval bound to a SHA-256 hash of the exact arguments; tool output treated as data; tools filtered by capability and role |
| LLM | Provider/model explicit and recorded per message; no fallback model |
| Voice | Microphone muted by default; mute stops capture and discards interim text; wake phrase only in a foreground tab |
| Reports | CSV export guards against spreadsheet formula injection |

## Known gaps (tracked)
- PostgreSQL RLS not enabled (see ARCHITECTURE.md); isolation is application-level and covered by tests.
- No MFA / SSO yet; no password-reset email flow (admins re-invite).
- Recording storage relies on provider URLs; no Kokila object storage or signed-URL proxy yet.
- Rate limiter fails open when Redis is unavailable.
- Dependency scanning runs in CI (`pip-audit`, `npm audit`, Trivy, gitleaks) — results must be reviewed on each release.
- India DPDP Act 2023 obligations (notice, consent manager, grievance officer, breach reporting) need legal review before launch.
