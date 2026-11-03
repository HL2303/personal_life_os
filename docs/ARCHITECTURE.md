# Architecture

## Current system

The repository is a small web application with a separately deployable
frontend and API. PostgreSQL is the relational datastore. The current V1
provides first-account setup, private sessions, activity tracking and
analytics, optional Telegram check-ins, and goals and projects.

```mermaid
flowchart LR
    Browser[User browser] -->|HTTPS in production| Web[Next.js frontend]
    Web -->|Same-origin checked, CSRF protected requests| API[FastAPI backend]
    API -->|User-scoped queries| DB[(PostgreSQL)]
    Migrations[Alembic migrations] -->|Schema changes| DB
    Worker[Supervised Telegram worker] -->|Persistent delivery queue| DB
    Worker -->|Bot API| Telegram[Telegram]
    API -. optional configured extraction .-> AI[OpenAI-compatible provider]
```

## Components

### Frontend

- Next.js App Router with TypeScript in `frontend/`.
- Owns the browser experience and calls the backend API with credentialed
  requests.
- The activity dashboard and authentication gate live in `frontend/app/page.tsx`;
  shared API calls and CSRF handling live in `frontend/lib/api.ts`.
- CORS on the API is configured for the single `FRONTEND_ORIGIN` setting.

### Backend

- FastAPI application entry point: `backend/app/main.py`.
- Authentication routes: `backend/app/api/auth.py`.
- Activity and category routes: `backend/app/api/activities.py`.
- Analytics aggregation routes: `backend/app/api/analytics.py`.
- Goal routes: `backend/app/api/goals.py`.
- Project and milestone routes: `backend/app/api/projects.py`.
- Telegram settings and webhook routes: `backend/app/api/telegram_settings.py`
  and `backend/app/api/telegram_webhook.py`.
- Health routes: `backend/app/api/health.py`.
- Settings: `backend/app/core/config.py`.
- SQLAlchemy base and session setup: `backend/app/db/`.
- Authentication dependencies resolve an opaque cookie session to a user.
- Activity, category, subcategory, analytics, goal, project, and progress
  operations filter by that user; composite foreign keys also prevent
  cross-owner references, including activity-to-project associations.
- Goal progress is user-entered or milestone-derived; it is not inferred from
  activity records. Project progress is completed milestones divided by all
  milestones, with no milestones yielding zero progress.

### Database and migrations

- PostgreSQL is provided for local development by the root
  `docker-compose.yml`.
- SQLAlchemy is the backend database toolkit and ORM.
- Alembic reads the SQLAlchemy metadata from `backend/app/db/base.py`.
- Alembic revisions create users, sessions, the setup singleton, categories,
  subcategories, activities, Telegram integration records, goals, projects,
  milestones, progress history, and activity-project associations.

## Runtime and health checks

- `GET /health` is a liveness check and does not require the database.
- `GET /health/ready` checks database connectivity and returns HTTP 503 when
  PostgreSQL is unavailable.
- `/docs` exposes FastAPI's interactive API documentation in development.

## Configuration and trust boundaries

- Local backend settings are read from `backend/.env`; frontend settings are
  read from `frontend/.env.local`.
- Example files document development configuration only. Production secrets
  must be supplied by the deployment environment or secret manager.
- The browser is an untrusted client. The API must validate inputs and enforce
  authorization for every protected operation.
- The first account is created through a one-time setup endpoint; public
  registration is disabled after setup.
- Passwords use Argon2id. Opaque random session tokens are stored as SHA-256
  hashes. Browser sessions use HttpOnly, SameSite=Strict cookies; unsafe
  requests require the configured exact origin and a session-bound CSRF token.
- Production mode requires Secure session cookies and disables interactive API
  documentation. Deployment must use HTTPS and add infrastructure-level
  request rate limiting.
- User-owned records are filtered and mutated only within the authenticated
  user's scope. Never rely on a client-supplied user identifier as
  authorization.
- Do not add a paid external service without explicit product configuration and
  documented operational requirements.

## Local development

See the repository `README.md` for PostgreSQL, backend, and frontend startup
instructions. The frontend and backend can be run separately; Compose currently
starts the database only. Telegram delivery runs in a separately supervised
worker (`python -m app.telegram.worker`); it is not scheduled in web-server
memory. Telegram and AI integrations require environment configuration.

## Architectural evolution

Keep the initial system modular and simple. Introduce additional services,
queues, caches, or deployment infrastructure only when an approved feature or
measured operational need requires them. Record material changes to data
ownership, API boundaries, or deployment topology here.
