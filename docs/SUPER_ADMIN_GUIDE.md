# Manima Super Admin Guide

## Creating the first Super Admin (one-time, CLI)
```bash
SUPERADMIN_PASSWORD='a-long-unique-passphrase' docker compose run --rm -e SUPERADMIN_PASSWORD api \
  python -m app.cli create-superadmin --email ops@manima.co.in
```
The email must be a real, deliverable domain (`.local` addresses are rejected because they could not sign in). Re-running the command resets the password. No default credentials exist. MFA is **not yet implemented** — protect this account and restrict who can run the CLI.

Sign in at `/login`; Super Admins without an organization land on **/admin** (Manima Super Admin).

## Console
- **Health:** database, Redis, active/suspended tenants, calls (24 h), live calls, failed webhooks, outbox dead letters, open job failures.
- **Platform outbound kill switch:** stops all outbound dialing for every tenant (audited, with reason).
- **Tenants:** plan, subscription, users, calls, compliance status; actions: Suspend/Reactivate, Approve/Reject outbound compliance, Assign plan, **Products & features**.
- **Plans & entitlements:** create/edit plans (price in paise excl. GST, minutes, limits, overage).

## Licensing products and features
**Products & features** shows every capability with its effective state and source (plan / override / not licensed / platform disabled / dependency / subscription inactive).
- **Enable / Disable** creates a tenant override; **Use plan** removes it.
- Disabling a product also disables its dependent features (reported as "Also disabled …").
- Enabling a feature whose prerequisite is off is rejected with a dependency conflict.
- Every change needs a reason, is revision-checked (another admin's concurrent edit returns a conflict) and is written to the audit log.

Examples:
| Client | Action |
|---|---|
| Calling Agent only | Disable `Business Assistant` |
| Business Assistant only | Disable `Calling Agent` |
| Both | Leave both products enabled |
| Selected enterprise features | Enable e.g. `Outbound campaigns`, `Custom assistant name`, `Web research` individually |

Plan packages (API): `PUT /api/v1/admin/plans/{code}/capabilities` with the full list of enabled keys. Platform-wide feature kill: `PUT /api/v1/admin/capabilities/{key}/control`.

Enforcement is server-side: a locked product's pages show a locked state and its APIs return `403 capability_disabled` even if a user types the URL or calls the API directly.

## Support boundaries
Super Admin views do not expose tenant transcripts, personal assistant data or credentials. Viewing a tenant's detail is itself audited.
