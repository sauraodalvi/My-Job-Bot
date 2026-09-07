# User State & Domain Model — the middle layer

Status: ready-for-agent
Feature slug: user-state

## Problem Statement

Onboarding collects "who I am and what I want" (resume, salary, locations,
recency, automation level); the runtime acts on that information (missions,
applications, networking, messaging). Today nothing connects the two: settings
live in loose JSON files, history in CSVs, referral results in their own JSON,
and usage counters in more JSON. There is no single model for a resume (file
vs extracted profile), a saved search, a person you've interacted with, or why an
agent did what it did. The agent has nowhere to read "who I am", "what I want",
or "what happened before".

## Solution

Introduce the **User State** middle layer: a single SQLite store plus a thin
read/write boundary that both the onboarding layer and the runtime layer speak
to. It holds the structured domain: Profile, Resumes (with versions), Saved
Searches, Preferences (Agent Policy + Action Policy), Missions, Jobs,
Applications, Companies, People, Relationships, Messages, the Event log,
Approvals, and Usage.

> **Onboarding teaches the agent who you are.**
> **Saved searches tell it what you want.**
> **Missions tell it what success looks like.**
> **The agent decides what to do next; SQLite + the event log are the source of truth.**

The store is local and single-user (no cloud backend). Existing JSON/CSV data is
kept readable/writable for backward compatibility, with lazy migration into the
store on first run of a new version — the user is never asked to migrate.

## Core domain concepts

- **Profile**: the person running the tool (identity fields, current city,
  experience, work authorization, links, portfolio).
- **Resume / ResumeVersion**: a resume is a logical document; a ResumeVersion is
  a specific file + its `uploaded_at`, `version`, `is_default`, and a
  `parsed_profile` (experience, skills, education — extracted separately from
  the file). The file and the extracted profile are distinct records, so a
  re-upload never silently changes past applications' meaning.
- **SavedSearch**: titles, locations, salary range (min/max/currency), recency,
  plus any filters. One physical source of truth for salary and recency; the
  search filter, application answers, and agent reasoning all read from it.
- **AgentPolicy**: the high-level level (Careful / Balanced / Hands-off),
  mapped explicitly to safety settings.
- **ActionPolicy**: per-action behavior (automatic vs ask-first) for
  APPLY / CONNECT / DM / GMAIL / SCAN.
- **Mission**: the goals the agent works toward — a chosen SavedSearch + a goal
  (e.g. "10 strong applications"), optional resume/resume version, and progress.
- **Job / Application**: a discovered job, and an application that references
  the job, the SavedSearch it came from, the exact ResumeVersion submitted
  (including a snapshot of the file), the resulting status, and the agent's
  decision/reasoning.
- **Company / Person / Relationship / Message**: contacts discovered during
  missions, their relationship state machine (discovered → contacted →
  connected / replied / declined / no-reply), and messages sent/received.
- **AgentRun / AgentEvent**: one agent loop session and the ordered event log.
- **Approval**: a pending or resolved human-in-the-loop ask (from the inbox).
- **Usage**: plan counters (daily applied / scanned / messaged), mirroring
  today's license usage counters.

## User Stories

1. As the user, I want all my data (profile, resumes, searches, missions, jobs,
   applications, people, messages, events, usage) in one queryable store, so
   that every part of the product sees the same truth.
2. As the user, I want my resume's file and its extracted profile kept separate,
   so that re-uploading a resume never rewrites what past applications recorded.
3. As the user, I want a resume to have versions, so that I can compare what was
   on disk at application time vs what I uploaded later.
4. As the user, I want my salary range and recency to live on a SavedSearch
   once, so that search, answer-fill, and agent reasoning all agree.
5. As the user, I want each application to record the exact resume version
   submitted (id + filename + snapshot), so that I can always see what the
   employer received.
6. As the user, I want an event log of every meaningful agent action and
   decision, so that the UI can show "what the agent is doing right now and why".
7. As the user, I want relationship state per person (contacted, replied,
   connected, declined), so that I never get duplicate outreach and follow-ups
   are possible.
8. As a developer, I want one read/write boundary for state, so that the UI,
   the agent, and tests consume the same layer rather than each touching files.
9. As a developer, I want JSON/CSV backward compatibility with lazy migration,
   so that existing users upgrade without a data-migration step.
10. As a developer, I want every meaningful state change to be auditable via
    the event log, so that behavior is debuggable and replayable.
11. As the user, I want no cloud backend and local-only storage, so that my
    credentials and data never leave my machine.
12. As the user, I want SQLite to be the persistence engine, so that the whole
    product runs on one embedded file with no server to operate.

## Implementation Decisions

- **Persistence**: SQLite, opened read-write at project root, one check-round
  migration mechanism (schema_version PRAGMA + ordered migrations). No ORM
  beyond a thin data-access module; Pydantic models define row shapes. Prior art
  that becomes the seam: `config/_overrides.py` (JSON fallback + defaults) and
  `modules/license.py` (usage counters) are re-pointed at the store while
  keeping their public functions.
- **Entity graph**: one file per table; `users` (single row), `profiles`,
  `resumes`, `resume_versions`, `saved_searches`, `saved_search_filters`,
  `missions`, `jobs`, `applications`, `companies`, `people`, `relationships`,
  `messages`, `agent_runs`, `agent_events`, `approvals`, `usage`.
- **Salary single source of truth**: a SavedSearch row stores `salary_min`,
  `salary_max`, `salary_currency`. Nothing else in the codebase holds a salary:
  search filters, application answers (`expected salary?` → a point in the
  range), and agent reasoning all read this row.
- **Resume snapshot**: an `applications` row stores `resume_id`,
  `resume_version_id`, `resume_filename`, and `resume_snapshot` (blob/path
  copy). From this, the UI can render "Application #123 — Resume: AI Product
  Manager v3 (PDF)" forever, even after the user edits the current file.
- **Event log**: append-only, ordered, with columns for id, timestamp,
  `run_id`, `mission_id`, `actor` (rule/ai/user), `action`, `subject`
  (referenced entity), `outcome`, `reasoning`, and `context` (JSON). The agent,
  executors, and UI write to it; the UI reads it for activity feeds and the demo
  narration. Actions tracked include JOB_DISCOVERED, JOB_SCORED, JOB_SKIPPED,
  APPLICATION_STARTED, RESUME_SELECTED, QUESTION_DETECTED, APPLICATION_PAUSED,
  APPLICATION_SUBMITTED, PERSON_DISCOVERED, PERSON_SCORED, CONNECTION_DETECTED,
  MESSAGE_PREPARED, MESSAGE_APPROVED, MESSAGE_SENT, AGENT_DECISION,
  AGENT_REPLAN, USER_OVERRIDE.
- **Read/write boundary**: a DataStore class with explicit read (query) and
  write (insert/update) methods; catalogues maps the entity → table. The GUI
  reads through it, the agent's tools read/write through it, executors log via
  it. Nothing else opens files directly.
- **Migration**: on first run of a version that defines a higher
  schema_version, run migrations in order; existing user_config.json/CSV data is
  read and copied in lazily (only if the relevant table is empty), then the app
  keeps working. No destructive deletes of old files; they stay as legacy.
- **License/usage**: usage counters remain per-day; the storage moves to a
  `usage` table but `modules/license.py` keeps its existing surface so callers
  (app.py API, bot) don't change.

## Testing Decisions

- A good test asserts external behavior through the read/write boundary: an
  entity saved is readable with the same shape; an application's resume snapshot
  stays correct after the resume file is later replaced; a person's relationship
  transitions are legal (never message twice); migrations upgrade an empty DB
  and a legacy-JSON-with-CSV state without data loss.
- Interactions with the store are tested against an in-memory SQLite instance
  (fixture). No tests hit the real project DB file.
- Prior art: `tests/test_license.py` (usage counter stubbing), `tests/
  test_config_overrides.py` (defaults-over-json loading) — both get re-pointed
  at the store while their assertions stay meaningful.
- Migration tests create a fake legacy JSON/CSV fixture and assert the lazy
  import result.

## Out of Scope

- The onboarding flow itself (`setup-flow-gui` spec).
- The agent runtime, tools, policies, and GUI screens (`agentic-vision` spec).
- Any cloud sync, multi-user, or multi-device behavior.
- Vector database / embeddings / RAG — the store is relational only.

## Further Notes

- This layer is intentionally "dumb": no orchestration, no AI calls. It is the
  shared vocabulary both other layers write against.
- The event log is the nervous system of the runtime (see `agentic-vision`); it
  is specified here because it belongs in the store, but consumed there.