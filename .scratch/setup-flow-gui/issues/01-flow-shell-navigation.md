# 01: "Let's get you ready" flow shell + navigation + save seam

**What to build:** The shared "Let's get you ready" flow — a welcome screen,
three labelled steps, back/next navigation, required-field validation, a final
"here's everything you told me" plain-words summary, and a finish action that
persists answers through the existing config path. The same flow, driven by one
shared declaration, must work identically in the desktop wizard and the web
control panel. Concrete step fields land in their own tickets; here the steps
are stubbed but wired to real persistence.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] Welcome screen (both UIs) says in one sentence what the tool does.
- [x] Three steps named: "Your resume", "Tell me what you want", "Should I ask before sending?".
- [x] Back/next navigation works on both UIs; each step explains in one short line why it's asked.
- [x] Required fields are marked and validated before Next is allowed; the flow cannot finish with a broken config.
- [x] A final summary lists every answer given in plain words before saving.
- [x] Finish persists answers to the same config the tool already reads; re-opening pre-fills from saved state.
- [x] A single shared `setup_flow` declaration drives both renderers; no duplicate step logic in either UI.
- [x] Tests: the shared declaration is unit-tested (validation, save-what-flow-touched); each renderer has a thin integration test proving it renders and persists through the shared path.