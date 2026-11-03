# Roadmap

## Roadmap status

This roadmap separates completed repository foundation work from product phases
that still need product-owner confirmation. Future phases are sequencing
proposals, not approved feature commitments.

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
and the migration plus CRUD flow have been verified against an isolated
PostgreSQL scratch database.

## Phase 3 - Validate and refine (proposed)

- Validate the workflow with intended users.
- Improve usability and reliability based on observed evidence.
- Add only the next highest-value capability supported by product feedback.

**Exit state:** the product direction and next investment are based on agreed
success measures and user feedback.

## Deferred until explicitly approved

Telegram, AI features, collaboration, analytics, billing, and production
deployment remain deferred. Their priority and requirements remain open.
