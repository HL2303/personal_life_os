# Personal Life OS - Product Requirements (working draft)

**Status:** Working baseline; confirm and refine product requirements with the
product owner before using this draft to make irreversible product decisions.

## 1. Product intent

Personal Life OS aims to help a person organize and make progress on the
important areas of their life in one private, dependable workspace. It should
reduce the effort of remembering, planning, and reviewing personal commitments
without turning the product into a source of pressure or noise.

The precise life areas, target user, and first feature set remain to be
confirmed. This draft intentionally does not prescribe a particular tracking
methodology or external service.

## 2. Problem and opportunity

Personal information and intentions can become fragmented across tools and
informal notes. A unified system may make it easier to capture information,
understand what needs attention, and reflect on progress. The product should
earn trust through clarity, predictable behavior, and protection of personal
data.

## 3. Product principles

- **User control:** users should be able to understand and manage their own
  information.
- **Privacy by design:** collect only information needed for agreed product
  capabilities and restrict access to its owner.
- **Low friction:** routine capture and review should be straightforward.
- **Clarity:** present useful information without unnecessary complexity.
- **Incremental delivery:** introduce product areas in validated phases rather
  than building a broad feature set without user feedback.

## 4. Users and primary jobs

The initial intended user is an individual organizing their own personal life.
Specific personas and jobs-to-be-done have not yet been validated.

Candidate jobs for product discovery:

- Capture something the user wants to remember or act on.
- Find and understand previously saved personal information.
- Decide what deserves attention next.
- Review intentions and progress over time.

These are discovery prompts, not commitments that all belong in the first
release.

## 5. Current V1 workflow

The current implementation provides a private, single-user activity log:

1. The first user creates an account through one-time setup; public registration
   is disabled afterward.
2. The user can sign in and manage activities, categories, and subcategories.
3. Activities can be logged retrospectively and reviewed on a daily timeline
   with date navigation and duration/category summaries.
4. Protected data is scoped to the authenticated user.

This records the implemented V1 slice; broader product direction and success
criteria remain to be validated.

## 6. Current non-goals

- Telegram, AI recommendations, and other external integrations.
- Social, shared, or collaborative accounts.
- Production deployment, billing, or analytics.

These may be considered later, but none is implied by the Phase 0 foundation.

## 7. Privacy and security expectations

- Do not commit credentials or personal data.
- Use environment-based configuration for local and deployed environments.
- Define retention, export/deletion, backup, and recovery requirements before
  production use.
- Scope every operation on user-owned data to the authenticated user.
- Avoid collecting sensitive information unless an approved feature requires
  it and its handling is documented.

## 8. Success measures

Success metrics have not been selected. Before launch, define a small set of
user-centered measures, such as successful completion of the core user task,
repeat usage where appropriate, and user-reported clarity and trust. Avoid
collecting behavioral analytics until purpose, consent, and retention are
agreed.

## 9. Open product decisions

- Which users and life areas should the first release serve?
- What is the single core workflow for the first usable product?
- What information is stored, and what should users be able to export or delete?
- What account recovery and session-management workflows are appropriate?
- Which success measures can be collected with minimal personal data?
