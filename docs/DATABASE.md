# Database

## Current status

PostgreSQL 16 is configured as the relational database. SQLAlchemy and Alembic
manage the account/session, activity, Telegram, goals, and projects schema in
the revisions under `backend/alembic/versions/`.

## Local database

The root `docker-compose.yml` starts the `db` service with:

- Database: `personal_life_os`
- Local development user: `personal_life_os`
- Local-only password: `local-dev-only`
- Host port: `5432`
- Persistent Docker volume: `postgres_data`
- Container health check: `pg_isready`

The credentials are for local development only. Do not reuse them in shared or
production environments.

Backend connection configuration is supplied by `DATABASE_URL`, for example:

```text
postgresql+psycopg://personal_life_os:local-dev-only@localhost:5432/personal_life_os
```

## ORM and migrations

- Define declarative models using the shared base in `backend/app/db/base.py`.
- Keep database engine, session factory, and request-scoped session dependency
  in `backend/app/db/session.py`.
- Create and review Alembic migrations for schema changes; do not rely on
  automatic table creation at application startup.
- Ensure model modules are imported into the Alembic metadata path before
  generating migrations.
- Keep migrations reversible where practical and review generated SQL before
  applying changes to persistent environments.

## Data ownership and access

- `users` stores normalized unique usernames and Argon2id password hashes.
- `auth_sessions` stores hashes of opaque session and session-bound CSRF
  tokens, plus creation and expiry timestamps.
- `app_setup` is a singleton row used to permit only one initial account.
- Categories, subcategories, and activities carry `user_id`.
- Composite foreign keys require category/subcategory references to belong to
  the same user as the activity.
- `goals` and `projects` are user-owned and may reference only categories
  belonging to their owner. Goal milestones and progress history carry the
  same owner and use composite foreign keys to their parent goal.
- `project_milestones` are user-owned and reference a project using a
  composite project/owner foreign key. Activities may optionally reference a
  project through a composite project/owner foreign key; deleting a project
  detaches its activities rather than deleting them.
- Measurable and recurring goal values are constrained to valid non-negative
  progress not exceeding a positive target. Milestone goals use milestone
  completion instead of numeric values. Recurring progress resets by calendar
  week or month when read or updated; updates are retained in goal progress
  history.
- Project and goal progress history is persisted for audit/display. Goal
  milestone completion changes are recorded as percentage progress entries.
  Project progress is calculated from completed milestones divided by all
  milestones (zero when there are none).
- The application derives ownership from the authenticated session and
  filters reads, updates, and deletes by that user.
- Telegram linking tokens are stored hashed and expire after a short interval;
  Telegram update IDs are unique. Persistent check-in and outbox rows retain
  delivery, response, skip, and failure status for worker retries.
- Telegram message text is retained in update records and pending
  clarification state to support processing/retries. Configure an AI provider
  only after reviewing its data-handling terms; message text and category
  context are sent to the configured provider for extraction.
- Telegram check-in delivery and retry state is persisted in PostgreSQL for a
  separately supervised worker; do not rely on an in-memory scheduler.

When adding more personal records:

- Establish an authenticated principal before accessing protected records.
- Include explicit ownership relationships for user-owned records.
- Scope reads, updates, and deletes to the authenticated user's identity in the
  database query itself.
- Derive the owner from the authenticated request context, not a request-body
  field supplied by the client.
- Add tests that demonstrate cross-user access is denied.
- Define deletion, retention, export, backup, and restoration behavior before
  storing real personal data.

## Schema decisions to record

For each new domain model, document its purpose, ownership, required fields,
nullability, uniqueness, indexes, retention behavior, and migration impact.
Avoid storing more personal or sensitive data than the feature needs.
