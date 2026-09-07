# 03: "Tell me what you want" step → Saved Search via one-sentence parse

**What to build:** The "Tell me what you want" step. The user writes one
plain-English sentence (e.g. "AI Product Manager roles in Europe, remote or
hybrid, €80–130k, posted this week."). With AI on, the tool parses it into a
**Saved Search** (titles, locations, salary range with currency, recency) and
shows the result back as one plain sentence for confirmation. If the sentence is
unclear, it asks one targeted follow-up question in plain words (never an empty
form); if AI is off or parsing fails, it asks a guided plain-word question set
one at a time. The Saved Search is the single source of truth for salary and
recency, with legacy filter values derived from it. Both UIs; pre-fills on
re-run.

**Blocked by:** 01.

**Status:** done

- [x] One plain-English box accepts the user's wish; at least one sentence is required.
- [x] With AI on, the sentence parses into a Saved Search (titles, locations, salary min/max/currency, recency).
- [x] The parsed result is confirmed back as one short plain sentence before continuing.
- [x] Unclear input triggers exactly one targeted plain-word follow-up question, never an empty form.
- [x] With AI off (or parse failure), the step falls back to a guided one-question-at-a-time plain-word set, never a raw form.
- [x] Salary range and recency are stored once on the Saved Search; the legacy salary/date filter settings are derived from them (no second source of truth).
- [x] Re-opening the flow pre-fills the step with the saved search.
- [x] Tests: parser tested as pure input→output transform with a stubbed AI (happy path, unclear→one follow-up, AI-off fallback); range/filter derivation matches documented mapping.