# Operations Runbook

| Situation | Action |
|---|---|
| Complaints / carrier incident / suspected spam | Super Admin → **Stop all outbound** (platform kill switch) or tenant **Pause all outbound**. Both take effect on the next dispatch tick (≤30 s). |
| Webhooks failing (`/admin/health` → webhooks_failed) | `docker compose logs api | grep webhook`; check `webhook_events.error`. Worker retries 6× automatically. After fixing, reset: `UPDATE webhook_events SET attempts=0 WHERE status='failed';` |
| 401 on all Retell webhooks | `RETELL_API_KEY` rotated/mismatched, or server clock skew > 5 min (check NTP). |
| Outbox dead letters | Inspect `outbox_events WHERE status='dead'`; fix the tenant endpoint; `UPDATE outbox_events SET status='failed', attempts=0, next_attempt_at=now() WHERE id=...`. |
| Appointment stuck `pending_confirmation` | Reconciliation runs every 5 min; check Google token (`calendar_connections.status`), reconnect via Integrations. |
| Payment captured but plan not active | Check Razorpay webhook delivery + `webhook_events WHERE source='razorpay'`; verify `RAZORPAY_WEBHOOK_SECRET`. Super Admin can grant the plan (audited) while investigating. |
| Tenant abuse | Super Admin → Suspend (blocks all API access for that tenant's users; audited). |
| Data erasure request | Contact page → **Erase data** (or `POST /deletion-requests`). Recorded in audit log and `deletion_requests`. |
| Restore | `scripts/restore.sh <dump>` (stops api/worker/beat, restores, migrates, restarts). |
| Key rotation | JWT: change `JWT_SECRET` and restart (all users re-login). ENCRYPTION_KEY: requires re-encrypting stored secrets — not automated; plan a maintenance window. |
