'''
Unit tests for modules/policy.py - the "Should I ask before sending?" step that
maps one plain yes/no onto safe, explicit Agent Policy + Action Policy defaults.

Pins the contract:
  * ask-before-sending is always a plain yes/no with safe default yes,
  * each Agent Policy level maps through one EXPLICIT table onto the existing
    safety settings (no hidden logic),
  * scan is automatic, submit is ask-first unless the user opted out, and
    connect / DM / gmail are always ask-first,
  * apply_policy is pure and reports the level it chose back on the config.

License: MIT  (https://opensource.org/license/mit)
'''

import copy

from modules import policy as p


def test_default_answer_is_safe_ask():
    assert p.level_for_ask(True) == "balanced"
    assert p.level_for_ask(False) == "expedited"


def test_balanced_level_maps_to_explicit_safety_settings():
    safety = p.safety_settings_for(True)
    assert safety["questions"]["pause_before_submit"] is True
    assert safety["questions"]["pause_at_failed_question"] is True
    assert safety["settings"]["run_in_background"] is False


def test_expedited_keeps_failed_question_pause():
    # "Just send it" still never lets the tool answer a question randomly.
    safety = p.safety_settings_for(False)
    assert safety["questions"]["pause_before_submit"] is False
    assert safety["questions"]["pause_at_failed_question"] is True


def test_default_action_policy_scan_automatic_submit_optin():
    policy = p.default_action_policy(True)
    assert policy["scan"] == "automatic"
    assert policy["submit"] == "ask_first"
    for channel in ("connect", "dm", "gmail"):
        assert policy[channel] == "ask_first"


def test_opt_out_makes_only_submit_automatic():
    policy = p.default_action_policy(False)
    assert policy["submit"] == "automatic"
    assert policy["scan"] == "automatic"
    for channel in ("connect", "dm", "gmail"):
        assert policy[channel] == "ask_first"


def test_apply_policy_is_pure_and_reports_level():
    cfg = {"secrets": {"username": "a@b.com"}, "questions": {"years_of_experience": 5}}
    before = copy.deepcopy(cfg)
    out = p.apply_policy(cfg, True)
    assert cfg == before  # input untouched
    assert out["agent_policy"]["level"] == "balanced"
    assert out["agent_policy"]["ask_before_sending"] is True
    assert out["questions"]["pause_before_submit"] is True
    assert out["questions"]["years_of_experience"] == 5  # unrelated keys survive
    assert out["secrets"]["username"] == "a@b.com"


def test_setup_flow_saves_policy_with_agent_policy(monkeypatch, tmp_path):
    import json
    import setup_flow
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)

    setup_flow.save_flow({
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "Data Analyst roles"},
        "policy": {"ask_before_sending": False},
    })
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["pause_before_submit"] is False
    assert saved["agent_policy"]["level"] == "expedited"
    assert saved["agent_policy"]["action_policy"]["submit"] == "automatic"

    pre = setup_flow.prefill()
    assert pre["policy"]["ask_before_sending"] is False
    assert pre["policy"]["agent_policy"]["level"] == "expedited"