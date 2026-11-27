# Deployment Guide (single-server MVP)

GitHub is the source repository only — pushing code does not deploy it. Deploy to an authorized server you control.

## 1. Server
Ubuntu 24.04, 4 vCPU / 8 GB RAM minimum, Docker Engine + Compose plugin, ports 80/443 open, DNS A records for `APP_DOMAIN` (e.g. `app.kokila.in`) and `API_DOMAIN` (e.g. `api.kokila.in`).

## 2. Secrets
```bash
git clone https://github.com/Manima-group/Kokila-Ai-Voice-AGent.git kokila && cd kokila
cp .env.example .env && chmod 600 .env
```
Set: `LLM_PROVIDER` + `LLM_MODEL` + the matching API key (Business Assistant chat), `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL=https://$API_DOMAIN`, `FRONTEND_URL=https://$APP_DOMAIN`, `CORS_ORIGINS=["https://$APP_DOMAIN"]`, strong `POSTGRES_PASSWORD`, `JWT_SECRET` (≥32 chars), `ENCRYPTION_KEY` (Fernet), `VOICE_PROVIDER=retell`, `RETELL_API_KEY`, Razorpay keys + webhook secret, Google OAuth client (redirect `https://$API_DOMAIN/api/v1/integrations/google/callback`), SMTP. Prefer a secret manager (e.g. AWS SSM / Doppler) that renders `.env` at deploy time. **Back up `ENCRYPTION_KEY` separately** — losing it makes stored provider credentials unreadable.

## 3. Start
```bash
export APP_DOMAIN=app.kokila.in API_DOMAIN=api.kokila.in
docker compose -f docker-compose.yml -f infrastructure/compose/docker-compose.prod.yml up -d --build
docker compose run --rm -e SUPERADMIN_PASSWORD api python -m app.cli create-superadmin --email ops@manima.co.in
curl -fsS https://$API_DOMAIN/ready
```
Caddy obtains TLS certificates automatically. Migrations run in the one-shot `migrate` service before `api`, `worker`, `beat` start.

## 4. Provider configuration
- Retell: set agent-level webhook to `https://$API_DOMAIN/api/v1/webhooks/retell` (Kokila sets it on publish) and number inbound webhook (Kokila sets it when a number is added/assigned).
- Razorpay dashboard → Webhooks → `https://$API_DOMAIN/api/v1/webhooks/razorpay`, events `payment.captured`, `order.paid`, `payment.failed`.

## 5. Backups
`scripts/backup.sh /var/backups/kokila` via cron (e.g. hourly) + copy off-host encrypted. Test restores monthly with `scripts/restore.sh` on a staging host. Redis holds no authoritative data (AOF enabled for queue durability).

## 6. Monitoring & logs
- Uptime checks on `https://$API_DOMAIN/ready` and `https://$APP_DOMAIN/`.
- `docker compose logs -f api worker beat` (JSON). Ship to Loki/CloudWatch with the Docker log driver of your choice.
- Super Admin → health panel: failed webhooks, outbox dead letters, job failures.

## 7. Upgrade & rollback
1. `scripts/backup.sh` → 2. `git fetch && git checkout <tag>` → 3. `docker compose ... up -d --build` (migrations run first).
Rollback: `git checkout <previous tag>`; if the release included a migration, `docker compose run --rm api alembic downgrade <prev_rev>` **only if** the downgrade is non-destructive, otherwise restore the pre-upgrade backup. Engage the outbound kill switch during incident response.

## 8. Scaling later
API and web are stateless (scale horizontally behind a load balancer); run one `beat` instance only; scale `worker` replicas; move Postgres to a managed service with PITR.
