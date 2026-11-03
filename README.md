# Personal Life OS

Personal Life OS is being built in phases. This repository currently contains
the Phase 0 application and database foundation; product features will be added
in later phases.

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

Alembic is configured to use the SQLAlchemy metadata in `backend/app/db`.
There are no domain tables or migrations yet; create the first migration when
the initial domain model is defined.

## Validation

From `backend/`, run `pytest` and `ruff check app tests`. From `frontend/`, run
`npm run typecheck` or `npm run build`.

## Security and scope

Configuration is loaded from untracked local environment files. The committed
example files contain development-only settings and must not be used as
production credentials. Authentication and user-owned data models are
intentionally not included in this infrastructure-only phase; future data
access must be scoped to the authenticated user.
