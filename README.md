# Kokila — Intelligence that speaks

**[Open Kokila Overview](http://localhost:3002/overview)** · [Sign in](http://localhost:3002/login) · [Create an account](http://localhost:3002/signup)

Kokila is a voice AI platform by **Manima AI-Tech Solutions**. Sign in once, open **Overview**, and choose **Calling Agent** or **Business Assistant**. Both products use the same backend, database, organization permissions, and integration layer.

Open these links on the computer running Kokila. `localhost` refers to that computer.

| Local service | Address |
| --- | --- |
| Kokila Overview | [http://localhost:3002/overview](http://localhost:3002/overview) |
| API documentation | [http://localhost:8002/api/docs](http://localhost:8002/api/docs) |
| API health | [http://localhost:8002/health](http://localhost:8002/health) |
| API readiness | [http://localhost:8002/ready](http://localhost:8002/ready) |
| PostgreSQL | Host port `5435`, container port `5432` |

These ports match the `kokila-unified-platform` local setup documented below.

## 1. Open an existing Kokila installation

If Kokila is already running, open [Overview](http://localhost:3002/overview). If the page doesn’t load, start Docker and run this from your `kokila-unified-platform` folder:

```bash
docker compose -p kokila-unified-platform up -d
docker compose -p kokila-unified-platform ps -a
```

Wait for `web` and `api` to start, then refresh the browser. Sign in with your existing account. Use [Sign up](http://localhost:3002/signup) if this is your first account in this installation.

## 2. Install Kokila for the first time

### Step 1 — Get the code

Install Git and Docker with Docker Compose v2. Start Docker before running the Compose commands.

```bash
git clone --branch main https://github.com/Manima-group/Kokila-Ai-Voice-AGent.git kokila-unified-platform
cd kokila-unified-platform
test -f .env || cp .env.example .env
```

### Step 2 — Configure `.env`

Open `.env` in your editor. Set a strong `POSTGRES_PASSWORD` and generate values for `JWT_SECRET` and `ENCRYPTION_KEY` using the commands documented in `.env.example`. For the PostgreSQL password, a random hexadecimal value works with the connection URL in Compose. Keep `.env` out of Git.

Add or update the following settings. If a key already exists in `.env`, edit its existing line.

```dotenv
WEB_PORT=3002
API_PORT=8002
POSTGRES_PORT=5435

FRONTEND_URL=http://localhost:3002
CORS_ORIGINS=["http://localhost:3002"]
PUBLIC_BASE_URL=http://localhost:8002
GOOGLE_REDIRECT_URI=http://localhost:8002/api/v1/integrations/google/callback
COOKIE_SECURE=false

VOICE_PROVIDER=mock
LLM_PROVIDER=none
```

This configuration starts Kokila for local testing. It lets you run mock call simulations before connecting a live telephony or AI provider.

### Step 3 — Build and start the stack

```bash
docker compose -p kokila-unified-platform config --quiet
docker compose -p kokila-unified-platform up --build -d
docker compose -p kokila-unified-platform ps -a
```

The first build downloads dependencies and builds the backend and frontend images. When the services start, verify the API:

```bash
curl -fsS http://localhost:8002/ready
```

Open [Sign up](http://localhost:3002/signup), enter your organization and account details, and create the account. Kokila takes you to [Overview](http://localhost:3002/overview).

### What the Docker status means

| Service | Job | Expected status |
| --- | --- | --- |
| `postgres` | Stores organizations, accounts, agents, calls, conversations, and other application records | `Up` and `healthy` |
| `redis` | Supports background job queues and rate limits | `Up` and `healthy` |
| `migrate` | Applies database migrations with `alembic upgrade head` | `Exited (0)` |
| `api` | Runs the FastAPI backend | `Up` and `healthy` |
| `worker` | Runs queued jobs such as webhooks, reminders, and campaign tasks | `Up` and `healthy` |
| `beat` | Schedules periodic jobs for the worker | `Up` |
| `web` | Serves the Next.js application on `localhost:3002` | `Up` and `healthy` |

## 3. Understand how Kokila works

1. **Sign in and choose a product.** The frontend opens Overview and shows the products available to your organization. Kokila checks your plan and permissions before granting access.
2. **Make a request.** When you create an agent, open a report, or send an assistant message, the Next.js frontend forwards the request to FastAPI.
3. **Process the request.** The API checks the user, organization, and feature access. It runs the relevant Calling Agent, Business Assistant, billing, or integration logic.
4. **Store data or run background work.** PostgreSQL stores application records. Redis queues background work. Celery Beat schedules periodic tasks, and the Celery worker executes them.
5. **Call a provider where needed.** Kokila uses Retell for configured live phone calls, OpenAI or Anthropic for configured assistant chat, and Kokila Connect for connected business systems.

Inside Docker, the frontend reaches the API at `http://api:8000`. From your computer, the same API is available at `http://localhost:8002`.

## 4. Try Calling Agent

Use this flow to test the product without placing a real phone call:

1. Open [Overview](http://localhost:3002/overview) and select **Calling Agent**.
2. Open **AI Agent Builder** and select **New agent**.
3. Choose a template. Add a name, greeting, language, and instructions.
4. Save and publish the agent.
5. Open **Voice testing** and select **Run simulation**.

For a live inbound call, configure Retell, connect or provision a phone number, assign the published agent to that number, and verify the webhook flow. After a call, use **Call History** to review available details such as the transcript or recording.

Calling Agent also includes contacts, leads, appointments, analytics, and outbound campaigns. Outbound campaigns require recorded consent for the campaign purpose. See the [User Guide](docs/USER_GUIDE.md) and [Telecom Compliance Checklist](docs/TELECOM_COMPLIANCE_CHECKLIST.md).

## 5. Try Business Assistant

Open [Overview](http://localhost:3002/overview) and select **Business Assistant**.

| Mode | Example | What it needs |
| --- | --- | --- |
| **Business** | “What were today’s sales?” or “Which invoices are overdue?” | A connected business data source. Free-form chat also needs an AI model. |
| **Personal** | “Remind me tomorrow to call the supplier.” | A signed-in user and a configured AI model for chat. Personal memories are saved when you approve them. |

To connect business data, open **Integrations**, choose a supported connector, enter its settings, and select **Save and test**. Once the connection passes, try a **Quick report** in Business mode. Quick reports can query supported data without an AI model. Actions that change data can require approval before execution.

### Enable AI chat

In `.env`, choose one provider, enter the exact model ID available to your account, and set its key:

| Provider | Required settings |
| --- | --- |
| OpenAI | `LLM_PROVIDER=openai`, `LLM_MODEL`, `OPENAI_API_KEY` |
| Anthropic | `LLM_PROVIDER=anthropic`, `LLM_MODEL`, `ANTHROPIC_API_KEY` |

Apply the API environment change:

```bash
docker compose -p kokila-unified-platform up -d api
```

Open Business Assistant again and send a short message. To use voice input, grant microphone permission in a supported browser such as Chrome or Edge. The assistant’s browser voice controls are separate from the telephony provider used by Calling Agent.

## 6. Create a Manima Super Admin

Ordinary signup creates a **Company Admin** for an organization. To manage organizations and licenses across the platform, create a **Super Admin** after the API is running:

```bash
read -rsp 'Super Admin password: ' SUPERADMIN_PASSWORD
printf '\n'
export SUPERADMIN_PASSWORD
docker compose -p kokila-unified-platform exec -e SUPERADMIN_PASSWORD api \
  python -m app.cli create-superadmin --email ops@yourdomain.com
unset SUPERADMIN_PASSWORD
```

Replace `ops@yourdomain.com` with your admin email and choose a password of at least 12 characters. Sign in at [Kokila Login](http://localhost:3002/login), then open [Super Admin](http://localhost:3002/admin). See the [Super Admin Guide](docs/SUPER_ADMIN_GUIDE.md).

## 7. Find your way around the code

The tree below shows the main files and directories on `main`.

```text
kokila-unified-platform/
├── .env.example                       # Template for local settings and provider keys
├── .github/workflows/ci.yml           # Backend, frontend, Docker, and secrets checks
├── .gitleaksignore                     # Reviewed, exact false-positive fingerprints
├── docker-compose.yml                 # Services, ports, dependencies, and volumes
├── backend/
│   ├── Dockerfile                     # Shared image for API, migrations, worker, and Beat
│   ├── pyproject.toml                 # Python dependencies and tool configuration
│   ├── alembic/versions/              # Database schema and data migrations
│   ├── tests/                         # Backend tests
│   └── app/
│       ├── main.py                    # FastAPI entry point and health routes
│       ├── cli.py                     # Administrative commands
│       ├── api/                       # API routing
│       ├── auth/                      # Sign-in and authentication
│       ├── tenants/                   # Organizations and tenancy
│       ├── platform/                  # Product capabilities and feature access
│       ├── admin/                     # Platform administration
│       ├── agents/                    # Calling Agent definitions
│       ├── voice/                     # Voice provider integration
│       ├── telephony/                 # Phone and call handling
│       ├── calls/                     # Call records and call workflows
│       ├── campaigns/                 # Outbound campaigns
│       ├── contacts/                  # Contacts and consent records
│       ├── leads/                     # Lead management
│       ├── appointments/              # Appointments
│       ├── analytics/                 # Reporting and analytics
│       ├── assistant/                 # Conversations, tools, and assistant logic
│       ├── connect/                   # Kokila Connect and governed metrics
│       ├── integrations/              # External integration workflows
│       ├── billing/                   # Plans, usage, and payments
│       ├── audit/                     # Audit events
│       ├── core/config.py             # Application settings
│       ├── db/                        # Database setup
│       └── workers/
│           ├── celery_app.py          # Celery configuration
│           └── tasks.py              # Background jobs
├── frontend/
│   ├── Dockerfile                     # Builds and serves the web application
│   ├── next.config.ts                 # Next.js configuration and API forwarding
│   ├── package.json                   # Dependencies and frontend commands
│   └── src/
│       ├── app/
│       │   ├── (auth)/                # Login and signup pages
│       │   └── (app)/
│       │       ├── overview/          # Product chooser
│       │       ├── calling-agent/     # Calling Agent pages
│       │       ├── assistant/         # Business and Personal Assistant pages
│       │       ├── integrations/      # Connector settings
│       │       ├── billing/           # Plans, usage, and billing
│       │       └── admin/             # Super Admin pages
│       ├── components/                # Shared UI components
│       ├── hooks/useVoice.ts          # Browser voice controls
│       └── lib/                       # API and authentication helpers
├── infrastructure/
│   ├── compose/docker-compose.prod.yml
│   └── docker/Caddyfile
├── scripts/
│   ├── backup.sh
│   ├── restore.sh
│   └── dev.sh
└── docs/
    ├── ARCHITECTURE.md
    ├── USER_GUIDE.md
    ├── API_DOCUMENTATION.md
    └── architecture/                  # Detailed flows and database schema
```

**Where to start when changing a feature**

| Task | Start here |
| --- | --- |
| Change the two product cards | `frontend/src/app/(app)/overview/` |
| Change the Calling Agent experience | `frontend/src/app/(app)/calling-agent/` and `backend/app/agents/` |
| Change Assistant behavior | `frontend/src/app/(app)/assistant/` and `backend/app/assistant/` |
| Change provider settings | `.env.example`, `backend/app/core/config.py`, and the relevant provider module |
| Change product or plan access | `backend/app/platform/` and `backend/app/admin/` |
| Add a database change | `backend/alembic/versions/` |
| Debug recurring jobs | `backend/app/workers/celery_app.py` and `backend/app/workers/tasks.py` |

## 8. Troubleshoot the local app

| Symptom | What to check |
| --- | --- |
| Overview doesn’t open | Run `docker compose -p kokila-unified-platform ps -a`. Verify that `web` is running and maps host port `3002` to container port `3000`. |
| Sign-in or signup fails | Check [API readiness](http://localhost:8002/ready), then inspect the `api` and `web` logs. |
| A product card is locked | Check the organization’s trial, subscription, and product permissions. |
| Assistant chat says it needs configuration | Check `LLM_PROVIDER`, `LLM_MODEL`, and the matching API key in `.env`, then recreate the API service with `docker compose -p kokila-unified-platform up -d api`. |
| Call testing fails | Start with **Run simulation** and verify `VOICE_PROVIDER=mock` in `.env`. |
| Docker reports a port is already allocated | Check for an existing container on that port. If you change the configured ports, update the corresponding URLs in `.env`. |

```bash
docker compose -p kokila-unified-platform logs --tail=80 api web
docker compose -p kokila-unified-platform logs --tail=50 worker beat
```

To pause the stack and resume it later:

```bash
docker compose -p kokila-unified-platform stop
docker compose -p kokila-unified-platform up -d
```

## 9. Verification and project status

[CI run #13](https://github.com/Manima-group/Kokila-Ai-Voice-AGent/actions/runs/46030592083) passed all four checks: **backend, frontend, Docker, and secret scanning**.

The local stack supports mock call simulations. Automated testing uses mocks or test doubles for external services. Live Retell calls, AI provider responses, connector traffic, and payment flows still require verification with real provider accounts.

- [Architecture](docs/ARCHITECTURE.md)
- [User Guide](docs/USER_GUIDE.md)
- [API Documentation](docs/API_DOCUMENTATION.md)
- [Database Migration Guide](docs/DATABASE_MIGRATION_GUIDE.md)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
- [Operations Runbook](docs/OPERATIONS_RUNBOOK.md)
- [Release Checklist](RELEASE_CHECKLIST.md)

© Manima AI-Tech Solutions · business@manima.co.in
