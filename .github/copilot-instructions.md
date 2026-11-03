# Copilot instructions

## Project overview

Personal Life OS is a personal organization application. The repository currently
contains a Phase 0 foundation, not a feature-complete product.

## Repository structure

- `frontend/`: Next.js App Router application using TypeScript.
- `backend/`: FastAPI application, SQLAlchemy setup, Alembic migrations, and
  pytest tests.
- `docker-compose.yml`: local PostgreSQL service.
- `docs/`: product, architecture, database, and roadmap documentation.

## Working in this repository

- Read the relevant documentation and inspect existing code before changing
  architecture or adding dependencies.
- Keep changes focused on the requested scope. Do not introduce activity
  tracking or other product features unless explicitly requested.
- Keep API configuration in the settings module and secrets in local
  environment variables. Never commit credentials.
- Use SQLAlchemy models and Alembic migrations for database schema changes.
- Add or update tests for behavior changes. Run the smallest relevant test,
  lint, type-check, or build command and report its result.
- Preserve the current frontend/backend separation and existing API contracts.
- Authentication and user-owned data models are not implemented yet. When they
  are introduced, every read and write of user-owned data must be scoped to the
  authenticated user and covered by tests.
- Update the relevant documentation when changing architecture, schema, API
  behavior, setup, or product scope.

## Local checks

- Backend: from `backend/`, run `pytest` and `ruff check app tests`.
- Frontend: from `frontend/`, run `npm run typecheck` and, when relevant,
  `npm run build`.
- Compose configuration: from the repository root, run `docker compose config`.
