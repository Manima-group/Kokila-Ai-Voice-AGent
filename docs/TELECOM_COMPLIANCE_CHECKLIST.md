# Telecom Compliance Checklist (India)

> Not legal advice. Confirm every item with telecom counsel and the access provider before any commercial outbound calling.

## Regulatory context (verified Nov 2026 against public sources)
- TRAI notified the **TCCCPR (Second Amendment) Regulations, 2025** on 12 Feb 2025 (Press Release 11/2025).
- Promotional calls must use the **140 series**; transactional and service calls must use the **1600 series**; ordinary 10-digit numbers must not be used for telemarketing.
- Consent given for completing an ongoing transaction is valid for **7 days** only.
- Calls to prospective customers are treated as promotional.

## Platform controls in Kokila
- [x] Outbound requires a granted, purpose-matched, unexpired voice consent with evidence (`contact_consents`).
- [x] Consent expiry supported (`expires_at`) — set 7 days for transaction-linked consent.
- [x] Opt-out honoured immediately (tool + `do_not_call` outcome + manual), consents revoked, pending campaign entries cancelled; opt-outs cannot be lifted without fresh consent recorded later.
- [x] Suppression list per tenant (manual DND entries supported).
- [x] Hard calling window 09:00–21:00 IST enforced in code (conservative default) plus campaign window/days.
- [x] Caller ID must be flagged `service` (1600) or `promotional` (140) and outbound-enabled for live providers.
- [x] Tenant compliance profile (legal name, DLT entity id, telemarketer registration, attestations) must be **approved by a Super Admin** before live outbound.
- [x] Tenant-level outbound pause and platform-wide kill switch (audited).
- [x] Agents disclose they are automated at the start of each call; no impersonation.
- [x] Retries bounded (max 5 attempts, minimum 15-minute delay).

## Operator / tenant obligations (outside the code)
- [ ] Tenant (Principal Entity) registered on an access provider's DLT platform; telemarketer registration where applicable.
- [ ] Caller-ID numbers provisioned in the correct series with the voice/SIP provider and mapped to the tenant.
- [ ] NCPR/DND scrubbing process agreed with the access provider (Kokila has no direct NCPR integration; import scrubbed numbers as `dnd` suppression).
- [ ] Recording disclosure and DPDP Act notice scripts approved by counsel.
- [ ] Retell (or SIP) carrier terms permit Indian termination for the intended traffic type.
- [ ] Complaint-handling and grievance-officer contact published.
