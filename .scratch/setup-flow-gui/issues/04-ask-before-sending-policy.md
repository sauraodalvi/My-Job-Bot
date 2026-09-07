# 04: "Should I ask before sending?" step → Action Policy defaults

**What to build:** The "Should I ask before sending?" step. A single yes/no in
the user's language, defaulting to **yes, always ask**. Under the hood it sets a
safe recommended configuration: the Agent Policy defaults to Balanced (mapped
through an explicit table to the existing safety settings), and the Action
Policy defaults to scan automatic / submit+connect+DM+gmail ask-first. No policy
engine is exposed to the user. The end screen states plainly that everything
will be asked before sending (and on the free plan, the free limits). Both UIs;
pre-fills on re-run.

**Blocked by:** 01.

**Status:** done

- [x] The step shows one yes/no — "should I ask you before sending anything?" — defaulting to yes.
- [x] The underlying Agent Policy defaults to a safe level with the safety settings derived through one explicit, tested mapping table.
- [x] A default Action Policy is created: scan automatic; submit/connect/DM/gmail ask-first.
- [x] The end screen states plainly ("I'll ask you before sending anything") and shows free-plan limits in plain words.
- [x] Re-opening the flow pre-fills the step with the saved choice and policies.
- [x] Tests: level→settings mapping and the default Action Policy are unit-tested as pure mappings.