# Personal Life OS

Personal Life OS is being built in phases. The current V1 slice includes a
private single-user workspace and end-to-end activity tracking.

## Stack

- Frontend: Next.js and TypeScript (`frontend/`)
- API: FastAPI and SQLAlchemy (`backend/`)
- Database: PostgreSQL, managed locally with Docker Compose
- Schema migrations: Alembic

## Local development

Requirements: Node.js 20+, Python 3.11+, and Docker Compose.

1. Start PostgreSQL from the repository root:

   ```sh
   docker compose up -d db
   ```

2. Configure and run the API:

   ```sh
   cd backend
   python -m venv .venv
   # Activate .venv for your shell, then:
   pip install -e ".[dev]"
   copy .env.example .env
   alembic upgrade head
   uvicorn app.main:app --reload
   ```

   On macOS or Linux, replace `copy .env.example .env` with
   `cp .env.example .env`.

3. Configure and run the frontend in another terminal:

   ```sh
   cd frontend
   npm install
   copy .env.example .env.local
   npm run dev
   ```

   On macOS or Linux, use `cp .env.example .env.local`.

The frontend is available at <http://localhost:3000>. The API health endpoints
are `/health` (liveness) and `/health/ready` (database readiness); interactive
API documentation is available at `/docs`.

Alembic migrations create the initial account/session and user-owned activity
schema. Apply migrations with `alembic upgrade head` from `backend/` after
configuring the database URL. Open <http://localhost:3000> and create the first
account; once created, public account setup is disabled.

## Telegram check-ins

The Telegram integration is optional. Configure `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_BOT_USERNAME`, and a random `TELEGRAM_WEBHOOK_SECRET` in the backend
environment. To register a webhook after you have a public HTTPS endpoint,
set `TELEGRAM_WEBHOOK_URL` to its origin and run
`python -m app.telegram.configure_webhook` from `backend/`. This registers only
the `/api/telegram/webhook` endpoint; do not expose it before configuring its
secret.

Run `python -m app.telegram.worker` as a separately supervised backend process
to deliver scheduled check-ins and queued replies. Scheduling and delivery
state is persisted in PostgreSQL, not in the web server process. Link the bot
from **Telegram** in the app, then configure the interval, timezone, active
hours, and quiet hours there. Bot commands include `/start`, `/link`, `/pause`,
`/resume`, `/today`, `/skip`, and `/help`.

Natural-language extraction is opt-in. Set `AI_PROVIDER=openai_compatible`,
`AI_API_KEY`, and `AI_MODEL` (and optionally `AI_BASE_URL`) to enable it. When
an AI provider is not configured, Telegram activity text is not logged; the
app asks the user to enter it in the dashboard instead. When configured,
Telegram message text, the user's categories, and local date/time context are
sent to that provider for extraction. Low-confidence or incomplete results
require clarification and are not saved.

## Validation

From `backend/`, run `pytest` and `ruff check app tests`. From `frontend/`, run
`npm run typecheck` or `npm run build`.

## Project documentation

- [Product requirements (working draft)](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Database](docs/DATABASE.md)
- [Roadmap](docs/ROADMAP.md)

## Security and scope

Configuration is loaded from untracked local environment files. The committed
example files contain development-only settings and must not be used as
production credentials. Passwords are Argon2id-hashed, session tokens are
stored as hashes, browser sessions use HttpOnly/SameSite cookies, and
state-changing requests require same-origin and CSRF validation. Activity,
category, and subcategory queries are scoped to the authenticated account.

Before any production use, configure a private PostgreSQL database and secret
credentials, set `APP_ENV=production` and `SESSION_COOKIE_SECURE=true`, serve
the frontend and API over HTTPS, and configure deployment-level request
rate-limiting, backups, and recovery. Production mode disables interactive API
documentation. This repository has not been deployed.
