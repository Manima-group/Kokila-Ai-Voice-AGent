# Release Checklist

Commercial production readiness: **NOT READY** — unchecked items are blocking.

## Unified platform acceptance (owner amendment §16)
- [x] 1 Register and sign in
- [x] 2 Login lands on the unified Overview
- [x] 3 Both product cards display (desktop + mobile)
- [x] 4 Product access reflects entitlements (UI + API)
- [x] 5 Calling Agent keeps all existing functionality (43 prior tests still pass)
- [ ] 6 Business Assistant text and voice with live credentials — **LLM/voice credentials pending** (mock-verified only)
- [x] 7 Switch products without re-authentication
- [ ] 8 Connected business data queried with permissions — **test double only; live ERPNext/Manima Hub pending**
- [x] 9 Cross-tenant isolation tests
- [x] 10 Locked products blocked via direct URL and API
- [x] 11 Super Admin assigns/revokes capabilities
- [x] 12 Existing database records preserved (dev upgrade verified)
- [x] 13 Desktop and mobile layouts (Playwright screenshots)
- [x] 14 Docker services build and start (GitHub Actions run 45969809558)
- [x] 15 Backend and frontend automated tests pass
- [x] 16 Production frontend build succeeds
- [x] 17 Mock providers isolated (refused in production)
- [ ] 18 All mandatory v5.0 modules implemented or recorded as blocked — recorded in traceability; 12 not started

## Security
- [x] Server-side RBAC + capability enforcement, webhook signatures, encrypted secrets, approval-gated AI writes
- [ ] PostgreSQL RLS · [ ] MFA for admins · [ ] password reset · [ ] independent penetration test · [ ] secret manager in production

## Live integrations
- [ ] LLM provider + model chosen and verified · [ ] Retell inbound/outbound · [ ] per-language audio tests (te/hi/en) · [ ] ERPNext · [ ] Manima Hub endpoints · [ ] Razorpay test mode · [ ] Google Calendar OAuth · [ ] remaining connectors

## Operations
- [x] Push to GitHub and green CI (`feature/unified-platform`) · [ ] staging deploy · [ ] backups + restore drill · [ ] monitoring/alerts · [ ] load test vs v5.0 §16 targets · [ ] legal/telecom sign-off
