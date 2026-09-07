'''
"Should I ask before sending?" step -> Action Policy defaults.

A single yes/no in the user's language (default: yes, always ask). Under the
hood this maps to a safe recommended configuration, expressed as explicit,
unit-testable tables. No policy engine is exposed to the user.

Two projections of the answer:

  * Agent Policy level  - "balanced" (safe) when asking, "expedited" when the
    user said just-send-it. Each level maps through an explicit table onto the
    EXISTING safety settings so the rest of the tool keeps behaving exactly as
    the level promises.
  * Action Policy       - one dict per channel: scan is always automatic;
    submit is ask-first unless the user opted out; connect / DM / gmail are
    always ask-first.

These are named "defaults": the user's later, explicit panel choices override
them, but re-saving the flow reinstates the recommended values.

License: MIT (https://opensource.org/license/mit)
'''

from __future__ import annotations

import copy

# ---------------------------------------------------------------------------
# Agent Policy levels -> existing safety settings (explicit mapping table)
# ---------------------------------------------------------------------------

AGENT_LEVELS = {
    "balanced": {
        "label": "Balanced (recommended)",
        "safety": {
            "questions": {
                "pause_before_submit": True,        # review every application
                "pause_at_failed_question": True,   # never answer randomly
            },
            "settings": {
                "run_in_background": False,         # pauses stay active
            },
        },
    },
    "expedited": {
        "label": "Expedited",
        "safety": {
            "questions": {
                "pause_before_submit": False,       # the user said just send it
                "pause_at_failed_question": True,   # still never answer randomly
            },
            "settings": {
                "run_in_background": False,
            },
        },
    },
}

ACTION_CHANNELS = ["submit", "connect", "dm", "gmail"]

ASK_FIRST_ACTION_POLICY = {
    "scan": "automatic",
    "submit": "ask_first",
    "connect": "ask_first",
    "dm": "ask_first",
    "gmail": "ask_first",
}


# ---------------------------------------------------------------------------
# Pure mappings
# ---------------------------------------------------------------------------

def level_for_ask(ask_before_sending: bool) -> str:
    '''True (safe default) -> "balanced"; False -> "expedited".'''
    return "balanced" if ask_before_sending else "expedited"


def safety_settings_for(ask_before_sending: bool) -> dict:
    '''
    The existing-safety-setting values implied by the chosen Agent Policy level.
    Returns {"questions": {...}, "settings": {...}}, straight from the table.
    '''
    level = level_for_ask(ask_before_sending)
    return copy.deepcopy(AGENT_LEVELS[level]["safety"])


def default_action_policy(ask_before_sending: bool) -> dict:
    '''
    The default Action Policy. Scan is always automatic; submit is ask-first
    unless the user opted out (then it is automatic); connect / DM / gmail are
    always ask-first.
    '''
    policy = dict(ASK_FIRST_ACTION_POLICY)
    if not ask_before_sending:
        policy["submit"] = "automatic"
    return policy


# ---------------------------------------------------------------------------
# Projection onto a config dict
# ---------------------------------------------------------------------------

def apply_policy(cfg: dict, ask_before_sending: bool) -> dict:
    '''
    Merge the policy defaults into a config dict. Pure: returns a NEW dict.
    Sets cfg["agent_policy"] (level + action policy) and derives the existing
    safety settings from the explicit level table.
    '''
    cfg = copy.deepcopy(cfg or {})

    ask = bool(ask_before_sending)
    safety = safety_settings_for(ask)

    questions = dict(cfg.get("questions") or {})
    questions.update(safety.get("questions", {}))
    cfg["questions"] = questions

    settings = dict(cfg.get("settings") or {})
    settings.update(safety.get("settings", {}))
    cfg["settings"] = settings

    cfg["agent_policy"] = {
        "level": level_for_ask(ask),
        "label": AGENT_LEVELS[level_for_ask(ask)]["label"],
        "action_policy": default_action_policy(ask),
        "ask_before_sending": ask,
    }
    return cfg