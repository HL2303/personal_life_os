# Roadmap

## Roadmap status

This roadmap records the implemented foundation and V1 modules. Any work beyond
the listed capabilities remains subject to product-owner confirmation.

## Phase 0 - Technical foundation (complete)

- Establish the Next.js and TypeScript frontend.
- Establish the FastAPI and SQLAlchemy backend.
- Configure PostgreSQL for local development and Alembic for schema migrations.
- Add environment examples, health checks, initial tests, and setup
  documentation.

**Exit state:** the web application and API build, the backend health checks
are covered by tests, and local infrastructure configuration is documented.
No live PostgreSQL integration test is included in this foundation.

## Phase 1 - Product definition (in progress)

- Confirm target user, core problem, and first life area or workflow.
- Agree on the first end-to-end user journey and measurable acceptance criteria.
- Decide account, privacy, personal-data handling, and deployment requirements.

**Exit state:** reviewed product requirements and an implementation plan for a
small, testable first product capability.

## Phase 2 - Secure activity vertical slice (implemented)

- Add first-account setup and secure session-based authentication.
- Define user-owned activity models and Alembic migration.
- Implement activity/category/subcategory CRUD, daily timeline, summaries,
  validation, and automated tests.
- Scope reads and writes to the authenticated user and enforce same-owner
  references in the database.

**Exit state:** the workflow and authorization boundaries pass automated tests,
and the migration plus CRUD flow pass automated tests. The latest migration
upgrade/downgrade lifecycle has been checked on SQLite; PostgreSQL integration
verification remains outstanding.

## Phase 3 - Telegram and Analytics (implemented)

- Add optional Telegram account linking, protected webhook processing,
  configurable scheduled check-ins, and queued delivery through a separately
  supervised worker.
- Add user-scoped daily, weekly, monthly, and custom-range analytics using
  persisted activities, with untracked time distinguished from tracked time.

## Phase 4 - Goals and Projects (implemented)

- Add measurable, recurring, and milestone-based goals, manually maintained
  progress history, projects, project milestones, and optional activity-project
  associations.
- Enforce account ownership across records and references.

## Next - Validate and refine (proposed)

- Validate the current workflows with intended users and agree on success
  measures.
- Verify migrations and application workflows against PostgreSQL in an
  integration environment.
- Address deployment, recovery, and operational requirements before public
  production use.

Public deployment, collaboration, billing, and AI recommendations remain
deferred. Optional Telegram activity extraction is implemented but requires
explicit provider configuration.
