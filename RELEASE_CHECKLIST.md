# Release Checklist

Commercial production readiness: **NOT YET** — unchecked items below are blocking.

## Code & CI
- [x] Backend tests pass (43) with migrations up/down/up
- [x] ruff, mypy, ESLint, TypeScript, Next build pass
- [ ] CI green on GitHub (backend, frontend, docker, secrets-scan) — pending push
- [ ] Docker images built and stack smoke-tested (CI `docker` job)
- [ ] Trivy / pip-audit / npm audit findings reviewed

## Security
- [x] Production settings guard (secrets, cookies, no mock provider)
- [x] Webhook signature verification without bypass (Retell, Razorpay)
- [x] Tenant isolation + RBAC tests
- [ ] Independent security review / penetration test
- [ ] Secrets provisioned from a secret manager; `ENCRYPTION_KEY` backed up offline
- [ ] MFA for super admins (not implemented)

## Live integrations
- [ ] Retell inbound + outbound + tools verified on staging
- [ ] Per-language audio tests (en, hi, kn) recorded; Telugu path decided
- [ ] Razorpay test-mode payment → webhook → activation → invoice
- [ ] Google Calendar OAuth, booking, reschedule, cancel, token refresh

## Compliance
- [ ] TELECOM_COMPLIANCE_CHECKLIST operator items complete (DLT, 140/1600 series, NCPR scrubbing process)
- [ ] DPDP Act notices, grievance officer, recording disclosure approved by counsel
- [ ] Terms of service / privacy policy published

## Operations
- [ ] DNS + TLS live via Caddy; `/ready` monitored
- [ ] Hourly backups + successful restore drill
- [ ] Log shipping and alerting on webhook failures / outbox dead letters
- [ ] Load test against defined SLOs
- [ ] Rollback rehearsed (DEPLOYMENT_GUIDE §7)
