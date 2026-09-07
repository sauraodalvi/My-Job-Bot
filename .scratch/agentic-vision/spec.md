# Agentic Runtime — the runtime layer

Status: ready-for-human
Feature slug: agentic-vision

## Problem Statement

The tool today is a deterministic scripted automator: it walks search results,
fills Easy Apply forms from static answers + optional AI, scans for referral
contacts, and sends templated messages. It has no goals, no memory, no planning,
no audit trail, and no way for a non-technical user to understand or control
"what the agent is doing right now and why". A live demo with an AI model needs
visible reasoning, safe rehearsal, and model-agnostic plumbing — none of which
exist. The user wants to evolve it into an *agentic* system while keeping the
working browser automation.

## Solution

Build the **runtime layer** on top of User State (`user-state` spec) and the
onboarding layer (`setup-flow-gui` spec). A single agent works through missions:
**observe → understand → plan → select tool → execute → observe result → verify →
remember → replan**, with every decision and action logged as an event. The
model never owns the browser, the database, or the state — it owns **decisions**,
expressed as structured **tool calls** executed by the app.

> **User State tells the agent who you are and what you want.**
> **Missions tell it what success looks like.**
> **The agent picks the next action; tools let it act; the event log tells it
> (and the user) what happened.**

The GUI is rebuilt around **agent runs** — a home/mission dashboard, an **Agent
Inbox** ("needs your attention") as the human-in-the-loop, an **Applications**
screen with resume snapshots and agent reasoning, a **Network** screen with
per-person relationship timelines, and technical config demoted to
Settings → Advanced.

## The agent loop

```text
MISSION
   ↓
OBSERVE  →  UNDERSTAND  →  PLAN  →  SELECT TOOL  →  EXECUTE
   ↑                                                    ↓
   └──────────  REPLAN  ←  MEMORY  ←  VERIFY  ←  OBSERVE RESULT
```

Example of the replan that makes the demo feel intelligent:

```text
MISSION: find 10 strong AI PM opportunities
→ OBSERVE: 42 jobs discovered           (JOB_DISCOVERED ×42, scored)
→ UNDERSTAND: 8 are strong matches      (JOB_SCORED: 8 high)
→ PLAN: for each strong match, check connections, identify relevant people,
        decide apply/network strategy
→ Job #1: strong match, 2 connections → search_people
→ IDENTIFIED: Sarah, 1st degree, target team (PERSON_SCORED)
→ DECIDE: message Sarah before applying  (AGENT_DECISION)
→ PREPARE message draft                  (MESSAGE_PREPARED)
→ VERIFY: already contacted 3 days ago   (MESSAGE_SENT exists)
→ REPLAN: do not message Sarah; find another relevant contact (AGENT_REPLAN)
→ ACT: find John
```

## Tools, not browser freedom

The model interacts with the app through **structured tools**. No free-form page
driving. Tools are the seam where old automation is wrapped (Selenium today) and
where dry-run vs real execution is decided.

```text
search_jobs()              get_job()
analyze_job()              search_people()
get_person()               get_relationship()
choose_resume()            prepare_application()
answer_application_question()   prepare_connection_request()
prepare_message()          send_message()
submit_application()       record_event()
```

Model replies in a tool-call contract:

```json
{ "tool": "search_people", "arguments": { "company": "Acme AI", "role": "Product Manager" } }
→
{ "people": [ { "name": "Sarah", "relationship": "1st_degree", "role": "Product Manager" } ] }
```

## Policies: Agent Policy + Action Policy

Two layers of policy live in User State (`user-state` spec) and gate the loop:

- **AgentPolicy** — high-level level: Careful / Balanced / Hands-off. Mapped
  explicitly to safety settings (pause before submit, pause on hard questions,
  run in background). Set during onboarding (Step 5).
- **ActionPolicy** — per-action behavior, defaulting each to automatic or ask:

```text
APPLICATION_SUBMIT  → Ask
CONNECTION_REQUEST  → Ask
LINKEDIN_DM         → Ask
GMAIL               → Ask
JOB_SCAN            → Automatic
```

Actions labeled "Ask" create an **Approval** in the inbox and pause the loop.
The mapping tables (level → safety settings, action → ask/auto) stay explicit
and tested.

## The Agent Inbox

Instead of watching a browser, the user gets a "needs your attention" queue:

```text
⚡ NEEDS YOUR ATTENTION — 3 things

📄 Application ready — Senior Product Manager, Acme AI
   Match 91% · Resume: AI Product Manager v3      [Review] [Submit]

🤝 Connection opportunity — Sarah Chen, PM @ Acme AI
   1st-degree · likely hiring team                 [View] [Message] [Skip]

❓ Application question — "Will you require sponsorship?"
   No confident answer available                    [Answer]
```

The agent works continuously; the human is the **exception handler**. Approving
or overriding resolves the approval record, emits a USER_OVERRIDE event, and the
loop continues.

## GUI around agent runs

- **Home / Missions**: current mission, progress bar, counts (jobs found /
  strong / applied), "currently doing", needs-you count, recent activity feed
  straight from the event log.
- **Applications**: total and per-application view — job, company, resume
  submitted (with version + snapshot), questions answered, salary answer, status,
  and the agent's decision/reasoning.
- **Network** (replaces "Referrals" as the framing): people with relationship
  status and a per-person timeline (found → identified → DM sent → replied →
  referral offered), plus recommended connections with match scores.
- **Settings**: technical config lives under Settings → Advanced, exactly as the
  onboarding spec proposes.
- **Demo narration**: the event log renders as a live "agent activity" stream —
  that is the demo screen.

## Model-agnostic AI provider

No hard-coded NYOK (or any other) model. `AIProvider` is configured with model,
endpoint, api_key, temperature; openai/deepseek/gemini/local (Ollama/LM Studio)
plug in. "NYOK" is treated as any other model name — if it exposes an
OpenAI/Gemini-compatible endpoint it works. The demo harness points at whichever
model the user configures. The model owns decisions, never state, the browser,
or the database.

## User Stories

1. As the user, I want to start a mission ("find 10 strong AI PM opportunities")
   that combines a SavedSearch, a resume, a goal, and automation level, so that
   the agent works toward a concrete goal.
2. As the user, I want the agent to choose the next action itself (apply, find a
   person, follow up, wait) and log its reasoning, so that the run is goal-driven
   rather than a scripted crawl.
3. As the user, I want the agent to observe, plan, act, verify, and replan in a
   visible loop, so that I can watch and trust it.
4. As the user, I want actions gated by ActionPolicy to pause in my Agent Inbox,
   so that nothing sensitive happens without my review.
5. As the user, I want a "needs your attention" inbox (application ready,
   connection opportunity, unanswered question), so that I am the exception
   handler, not the browser watcher.
6. As the user, I want to approve, edit, or skip inbox items, so that I control
   outcomes without technical complexity.
7. As the user, I want the Applications screen to show the resume version and
   snapshot submitted plus the agent's reasoning, so that I always know what the
   employer received and why.
8. As the user, I want a Network screen with per-person relationship timelines,
   so that I can see my outreach history and follow up.
9. As the user, I want the agent to remember who it already contacted and
   replan instead of re-messaging, so that I never get duplicate outreach
   ("message Sarah → already contacted → replan → message John").
10. As a demo presenter, I want a live agent-activity stream rendered from the
    event log, so that the demo shows the loop thinking out loud.
11. As a demo presenter, I want dry-run/rehearsal to exercise the loop with no
    side effects (nothing submitted, sent, or logged as done), so that demos are
    safe.
12. As a developer, I want real actions and dry actions to share an executor
    boundary, so features are rehearsable then promotable by policy instead of a
    rewrite.
13. As a developer, I want the model to communicate via structured tool calls,
    never free browser automation, so that behavior is auditable and safe.
14. As a developer, I want AIProvider configured by model/endpoint/key, so that
    NYOK, Gemini, DeepSeek, or a local model demo without code changes.
15. As the user, I want no multi-agent swarms, LangChain/CrewAI layers, vector
    databases, or cloud backends, so that the product stays simple to run.
16. As the user, I want one agent with six tools to ship the MVP mission, so
    that the demo lands fast.

## Implementation Decisions

- **Executor boundary**: an ActionExecutor with Real and Dry implementations,
  seeded by the existing `--dry-run` machinery (`modules/dry_run.py`). Every
  action logs an event through the store; dry mode logs no irreversible action.
  The executor is the only place that touches real side effects.
- **Tool layer**: a registry mapping tool names to callables over the DataStore
  (`user-state` spec) + automation module. Six-tool MVP: `search_jobs`,
  `analyze_job`, `search_people`, `get_relationship`, `prepare_action`,
  `execute_action` — the last resolving against ActionPolicy (auto vs ask) and
  the executor.
- **Agent loop**: a simple controller (mission → observe → plan → select tool →
  execute → verify → remember → replan). Replan reads the event log ("already
  contacted X") before repeating an action. No external agent frameworks.
- **Policy engine**: AgentPolicy + ActionPolicy loads from User State; exposes
  `policy.check(action)` → automatic / ask / blocked; enforces quota (per-day
  usage), approval, safety, and dry run in one place. Callers of
  `modules/license.py` keep their surface; quota moves behind the engine.
- **Inbox**: an Approvals table + endpoints to list/approve/edit/skip; approving
  executes the prepared action, emitting MESSAGE_APPROVED etc. events; edits
  store the USER_OVERRIDE.
- **GUI**: dashboard (Home / Missions), Applications, Network, Settings →
  Advanced. Rendered from User State via the existing control panel (`app.py` +
  `control_panel.html`); the dashboard replaces the current bare home page.
- **Stack**: keep the existing working stack (Selenium, current config
  overrides, dry-run) wrapped behind the executor; do NOT retrofit the runtime
  around a different stack. Introducing Playwright/FastAPI/Pydantic is optional
  and deferred — do not block the agent loop on it.
- **Events as the nervous system**: every item above writes events; the GUI and
  demo read them. The event vocabulary from the user-state spec is the source of
  naming.

## Testing Decisions

- A good test asserts external behavior through the executor/policy seams:
  given identical inputs and a policy, the same logged outcome; "ask" actions
  never execute without an approval; "already contacted" people are never
  messaged twice; dry runs produce events with no side effects.
- The executor boundary is tested with fake tools asserting event output and
  no-op behavior under dry mode (prior art: `tests/test_dry_run.py`, the
  referral smoke harness).
- Policy tables (AgentPolicy → safety settings; ActionPolicy → ask/auto) are
  unit-tested as pure mappings (prior art: config overrides tests).
- The replan-verify behavior is tested at the store level: `MESSAGE_SENT` events
  for a person → the loop selects a different person.
- The six-tool MVP is exercised end-to-end in dry mode against an in-memory
  store, asserting the mission reaches its goal with legal event histories.

## Out of Scope

- Multi-agent swarm / CrewAI / LangChain orchestration, vector DBs, RAG,
  Kubernetes, cloud backends, full autonomous browser navigation, or "15
  different agents".
- Licensing gates beyond quota enforcement behind the policy engine.
- Replacing the working automation engine; Selenium stays wrapped by the
  executor.
- Non-local deployment; everything stays local, single-user, embedded SQLite.
- Migrating the stack (Playwright/FastAPI/Pydantic) — optional, deferred, and
  not required for the agent loop.

## Further Notes

- The MVP to land first: **one agent, six tools, one mission** ("find strong
  jobs and build the best path toward getting hired"), with the event log as the
  demo screen. Everything else (inbox, applications, network dashboards) builds
  on that spine.
- "NYOK model": confirm with the user which provider/endpoint it exposes before
  wiring the demo; the architecture must not depend on it.
- The demo to optimize everything around: user asks "find AI PM jobs in Europe
  within the last 7 days" → agent searches, analyzes, ranks people, checks
  relationships, prepares a DM, policy asks approval, GUI shows it, user sends,
  event logs MESSAGE_SENT, memory stores "Sarah contacted" — then a second run
  never re-messages Sarah.