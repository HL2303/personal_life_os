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

The current implementation provides a private workspace with one-time account
setup; public registration is disabled after the first account is created.
The implemented workflows are:

- Manage activities, categories, and subcategories; log activities
  retrospectively and review them on a daily timeline.
- Review recorded time through daily, weekly, monthly, and custom-range
  analytics, category summaries, and activity drill-down. Missing periods
  remain explicitly untracked.
- Link an optional Telegram bot for scheduled check-ins and activity capture.
  AI extraction is optional and requires provider configuration; uncertain
  activity details are clarified rather than invented.
- Create measurable, recurring, and milestone-based goals with manually
  recorded progress and history.
- Manage projects, milestones, and project-linked activities. Project progress
  is based on completed milestones divided by all milestones.

All protected records and cross-record references are scoped to the
authenticated account. This describes the current implementation; the target
users, success criteria, and broader product direction still need validation.

## 6. Current non-goals

- Social, shared, or collaborative accounts.
- AI recommendations or automated inference of goal progress from activity.
- Billing and public production deployment.

Basic activity analytics and optional Telegram check-ins are implemented.
These do not imply that advanced analytics, recommendations, collaboration,
or production deployment are approved.

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
