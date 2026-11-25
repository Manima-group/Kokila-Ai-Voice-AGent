# Kokila operations runbook (authoritative, §33 REL-FINAL-04)

## Health
* `GET /healthz` checks liveness only.
* `GET /readyz` returns 503 when the database, schema (`alembic_version` ≠ expected) or Redis are unavailable.
  `checks.reasoning=not_configured` means turns will return 503 `provider_unavailable`.

## Logs
JSON lines on stdout with `trace_id`, `request_id`, `route`, `status`, `duration_ms` and `tenant_ref`. Every error
response includes `error.trace_id`, so search logs for that value. Secrets, tokens and passwords are redacted by key
name. Message content is never logged.

## Common incidents
| Symptom | Check | Action |
|---|---|---|
| All turns 503 `provider_unavailable` | `/readyz` reasoning check; logs `reasoning_transient_failure` | Verify the key/model; configure `KOKILA_REASONING_FALLBACK_PROVIDER` |
| Users get 403 `capability_disabled` unexpectedly | `/v1/platform/capabilities` (kill switch?) and the tenant's entitlements | Fix the package; every change is audited |
| 429 on login | Redis keys `kokila:<env>:rl:*` | Wait for the window, or investigate abuse |
| Outbox backlog | `select status,count(*) from outbox_events group by 1` | Check the worker is running (`celery ... -B`); there should be exactly one beat |
| Refresh token "reuse detected" | Audit and logs for the user | The family was revoked by design; the user signs in again |

## Migrations
Run as a single job: `alembic upgrade head && python -m app.cli bootstrap`. Migrations take advisory lock
`7515000001`. Never edit applied migrations; add forward migrations only.

## Emergency disable
Super Admin → Controls → disable the capability (reason required). The change takes effect on the next request for all
tenants.
