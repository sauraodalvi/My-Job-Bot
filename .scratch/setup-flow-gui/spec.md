# Let's Get You Ready — Onboarding Layer

Status: ready-for-agent
Feature slug: setup-flow-gui

## Problem Statement

The target user is not technical and does not want to think. They pay for
convenience. Today the tool demands a wall of up-front input: login, AI key,
titles, locations, salary, recency, resume, profile links, license key, schedule
— plus dozens of advanced options. That is a product for a hobbyist, not for the
person paying to have the job application handled.

The current onboarding also assumes the user can answer structured questions
thoughtfully. They cannot, and they shouldn't have to. **The only thing that
matters is their resume and one sentence about what they want.**

## Solution

Replace the dense, question-heavy setup with a three-step flow that asks the
minimum human input and **derives everything else**:

```text
Step 1  Upload your resume
Step 2  Tell me what you want
Step 3  Should I ask before sending?
```

The flow is introduced as **"Let's get you ready"** (never "Setup").

- **Step 1 — Your resume**: the only truly required input. Upload a PDF/Word
  file; the tool parses it and shows what it *understood*: "Detected: 3+ years
  experience, AI, Product Management ✓". This trust moment is the whole point —
  see below.
- **Step 2 — What you want**: one plain-English box. The user writes something
  like *"AI Product Manager roles in Europe, remote or hybrid, €80–130k, posted
  this week."* AI parses this into a **Saved Search** (titles, locations, salary
  range, recency). If the sentence is unclear, the tool asks **one targeted
  follow-up question in plain words** — never an empty form.
- **Step 3 — Should I ask before sending?**: a single yes/no in the user's
  language, defaulting to **yes, always ask**. Everything else (agent level,
  safety booleans, action policy) is set to a safe recommended configuration
  under the hood.

The flow turns the user's 5-step thinking into a 3-step experience delivered in
about one minute. Non-essential settings never appear unless the user actively
opens "Advanced". Every choice remains editable later; the parsed Saved Search
and Resume Profile are first-class things the user can see and manage.

## Design principles (the "dumb human, pays for convenience" contract)

- **One real input.** The resume. Everything else is derived, defaulted, or
  auto-detected.
- **Zero decisions that can be made wrong.** Salary, recency, locations, titles,
  agent policy, safety settings are never exposed as raw choices in the flow.
  They get defaults the user can ignore or change in Advanced later.
- **Trust via understanding, not configurability.** The moment that convinces a
  non-technical user is seeing the tool *understood* them — the detected
  profile on the resume step and a plain-sentence summary of what it parsed in
  Step 2. That beats any settings screen.
- **Convenience is the product.** Paid plan = everything pre-filled,
  auto-detected, one-click mission, "just works". Free plan = same flow, you
  review everything before anything is sent.
- **Safe by default.** Nothing is sent, submitted, or external until the user
  approves — default yes, always ask.
- **Recommended values, not questions.** The agent level defaults to Balanced,
  mapped to safe safety settings behind the scenes.

## User Stories

1. As a new user, I want a welcome screen that says in one sentence what this
   tool does, so that I understand before I start.
2. As a new user, I want the flow to be called "Let's get you ready", so that it
   doesn't feel like technical setup.
3. As a new user, I want to finish in three short steps in about a minute, so
   that I'm not overwhelmed.
4. As a new user, I want to start by uploading my resume, so that the most
   important input comes first.
5. As a new user, I want the resume step to accept PDF and Word via a browse
   dialog, so that I don't type a path.
6. As a new user, I want to see what was detected from my resume (years of
   experience, key skills) with a "Looks right" confirmation, so that I trust
   the tool understood who I am.
7. As a new user, I want to type my wish in one plain-English box, so that I
   don't separate titles from locations from salary myself.
8. As a new user, I want the tool to turn my sentence into the search for me,
   so that I never fill a form.
9. As a new user, if my sentence is unclear, I want one targeted question in
   plain words rather than an empty form, so that I'm guided, not lectured.
10. As a new user, I want my parsed wish shown back as a short plain sentence
    ("I'll look for AI Product Manager roles in Europe, remote or hybrid,
    €80–130k, posted this week."), so that I can confirm at a glance.
11. As a new user, I want one yes/no — "should I ask you before sending
    anything?" — defaulting to yes, so that I control what goes out without
    understanding a policy engine.
12. As a new user, I want everything else already decided safely for me, so
    that I don't make a choice I don't understand.
13. As a new user, I want back/next navigation and validation on required
    fields, so that I can correct myself and never finish broken.
14. As a new user, I want a final "everything you told me" summary in plain
    words, so that I can review before finishing.
15. As a returning user, I want to reopen the flow pre-filled, so that I can
    change one thing without retyping the rest.
16. As a returning user, I want to edit my wish later (e.g. add a location)
    without redoing the whole flow.
17. As a user, I want things I don't understand hidden behind "Advanced", so
    that the everyday screen stays simple.
18. As a user, I want the same flow on the desktop wizard and the web panel, so
    that both entry points behave identically.
19. As a user who skipped optional inputs (AI key, profile links), I want the
    flow to proceed without them.
20. As a user on the free plan, I want the end screen to state plainly that
    everything will be asked before sending, so that I have no surprises.
21. As a user who already finished onboarding, I want the home screen to show
    "you're all set" instead of asking me again.
22. As a user editing later, I want to see plain-language labels and help for
    each setting, so that nothing is relabeled inconsistently.
23. As a developer, I want the step definitions to live in one shared
    declaration consumed by both UIs, so that I don't maintain two flows.
24. As a developer, I want the recommended-action-policy defaults to be one
    explicit, tested configuration, so that they're auditable and changeable.
25. As a developer, I want resume detection and wish-parsing to be testable as
    pure input→output transforms, so that AI quality is verifiable.
26. As a non-native speaker, I want short, plain sentences everywhere with no
    jargon or terminal commands.

## Implementation Decisions

- The flow is a declarative module (a `setup_flow` definition): three steps,
  which User State entity each step creates/edits, validation rules, and the
  default policy configuration. No renderer-specific code lives in the step
  definitions.
- Both UIs consume the definition: the existing Tkinter desktop wizard and the
  existing browser control panel. One definition, two thin renderers.
- Step 1 creates a **Resume Profile**: stages the uploaded file, runs the
  existing resume extractor, and shows the detected profile for confirmation.
  File and parsed profile are stored separately (see `user-state`).
- Step 2 parses the user's sentence with configured AI into a **Saved Search**
  (titles, locations, salary range with currency, recency). The parse result is
  shown back as one plain sentence for confirmation. Unclear input triggers a
  single guided follow-up question (narrowing one missing/puzzled field), never
  an empty form. If AI is off or parsing fails, fall back to a guided plain
  question set (one question at a time), never a raw form.
- Salary range and recency live only on the Saved Search as the single source
  of truth; the legacy filter settings are derived from it (search filter,
  "expected salary?" answers, agent reasoning all read the same value).
- Step 3 sets an **Action Policy**: a safe recommended default — scan
  automatic; submit / connect / DM / gmail all ask-first — surfaced to the user
  as a single yes/no ("ask before sending?"). The underlying **Agent Policy**
  defaults to Balanced and is never exposed in the flow. See `agentic-vision`
  for the runtime meaning; both live in User State.
- Everything the flow does not touch keeps current defaults. Re-running is
  idempotent: pre-fills from saved state, only overwrites what the flow touched.
- Already-complete users keep current behaviour: the flow only appears when
  onboarding isn't done or the user opts to edit. Existing JSON config remains
  read/written for backward compatibility (see `user-state` migration).

## Testing Decisions

- A good test asserts external behaviour: given the flow's inputs, the expected
  User State is created (Resume Profile, Saved Search with parsed values +
  defaults, Action Policy with ask-first defaults) and the summary sentence is
  shown. Tests don't inspect widget internals.
- The declarative step module is unit-tested directly: validation, pre-fill
  from existing state, save-what-the-flow-touched, and the default action-policy
  configuration.
- Resume detection and the wish-parser are tested as pure input→output
  transforms with a stubbed AI (returning a known parse JSON), covering happy
  path, unclear input → one guided follow-up, and AI-off fallback.
- Each renderer gets a thin integration test proving it renders the shared step
  list and persists through the shared save path. Flask test-client is prior
  art for the web side; Tkinter is exercised via a stub renderer.
- Prior art: `tests/test_app_integration.py`, `tests/test_config_overrides.py`,
  `modules/ai/` answer plumbing.

## Out of Scope

- Changing how the bot runs (application walking, referral scanning, AI answer
  generation) — runtime is the `agentic-vision` spec.
- The structured User State store (SQLite schema, events) — the `user-state`
  spec. This spec only says the flow writes into it and reads pre-fill from it.
- Marketing/landing pages and licensed-vs-free plan mechanics beyond showing
  existing limits/approval behaviour in plain words.
- AI-provider plumbing: the flow only stores one optional AI key.
- Localization into languages other than plain English.

## Further Notes

- Success bar: "a non-technical person can finish alone in about one minute and
  understand what the tool got right". Anything that needs a technical
  explanation belongs behind Advanced.
- The trust moments (resume "Detected:" and the one-sentence parse summary) are
  the product; polish them harder than any settings screen.
- The flow must render identically in desktop and browser; the seam to fix on
  drift is the shared definition, not either renderer.