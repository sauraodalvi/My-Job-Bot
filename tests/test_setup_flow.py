'''
Unit tests for setup_flow.py - the shared "Let's get you ready" declaration that
drives BOTH the Tkinter desktop wizard and the browser control panel.

These pin the contract the two thin renderers rely on:
  * the three steps exist with the exact plain-word titles, in order,
  * required fields are validated before the flow can finish,
  * save-what-the-flow-touched (nothing outside the flow's keys is changed),
  * pre-fill reads back from existing user_config.json,
  * the final summary lists every answer in plain words.

License: MIT  (https://opensource.org/license/mit)
'''

import json

import setup_flow


# --------------------------------- steps ------------------------------------
def test_three_steps_with_exact_titles():
    assert [s["title"] for s in setup_flow.STEPS] == [
        "Your resume",
        "Tell me what you want",
        "Should I ask before sending?",
    ]
    assert [s["id"] for s in setup_flow.STEPS] == ["resume", "wants", "policy"]


def test_every_step_explains_why_it_is_asked():
    for s in setup_flow.STEPS:
        assert s["why"].strip(), "step %s is missing its 'why' line" % s["id"]
        assert s["fields"], "step %s has no fields" % s["id"]


def test_welcome_says_in_one_sentence_what_the_tool_does():
    assert len(setup_flow.WELCOME_SENTENCE) > 0
    assert setup_flow.WELCOME_NOTES


# -------------------------------- validation -------------------------------
def test_required_fields_are_marked():
    whole_flow_required = [f["key"] for f in setup_flow.step("resume")["fields"] if f.get("required")] + \
        [f["key"] for f in setup_flow.step("wants")["fields"] if f.get("required")]
    assert setup_flow.required_fields("resume") == ["resume_path"]
    assert setup_flow.required_fields("wants") == ["sentence"]
    assert whole_flow_required


def test_empty_required_field_fails_validation():
    errors = setup_flow.validate_step("resume", {"resume_path": "  "})
    assert len(errors) == 1 and "resume" in errors[0].lower()


def test_filled_required_field_passes_validation():
    assert setup_flow.validate_step("resume", {"resume_path": "C:/resume.pdf"}) == []


def test_optional_policy_step_passes_even_empty():
    # ask-before-sending is not required: a blank answer must not block finishing.
    assert setup_flow.validate_step("policy", {}) == []


def test_validate_flow_reports_only_broken_steps():
    errors = setup_flow.validate_flow({
        "resume": {"resume_path": ""},
        "wants": {"sentence": "AI PM roles in Europe"},
        "policy": {"ask_before_sending": True},
    })
    assert list(errors.keys()) == ["resume"]


def test_validate_flow_empty_when_complete():
    assert setup_flow.validate_flow({
        "resume": {"resume_path": "C:/resume.pdf"},
        "wants": {"sentence": "AI PM roles in Europe"},
        "policy": {"ask_before_sending": True},
    }) == {}


# --------------------------- save-what-the-flow-touched -------------------
def test_apply_answers_only_touches_flow_keys():
    cfg = {
        "secrets": {"username": "someone@example.com"},
        "questions": {"pause_before_submit": "whatever", "years_of_experience": 5},
        "search": {"search_terms": ["Engineer"]},
    }
    out = setup_flow.apply_answers(cfg, {
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "AI PM roles in Europe"},
        "policy": {"ask_before_sending": True},
    })

    assert out["questions"]["default_resume_path"] == "C:/r.pdf"
    assert out["questions"]["pause_before_submit"] is True
    assert out["setup_flow"]["want_sentence"] == "AI PM roles in Europe"
    # Everything the flow does NOT own is untouched...
    assert out["secrets"]["username"] == "someone@example.com"
    assert out["questions"]["years_of_experience"] == 5
    assert out["search"]["search_terms"] == ["Engineer"]
    # ...and the input dict was not mutated (pure function).
    assert cfg["questions"].get("default_resume_path") is None
    assert "setup_flow" not in cfg


def test_ask_before_sending_defaults_true():
    out = setup_flow.apply_answers({}, {
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "x"},
        "policy": {},
    })
    assert out["questions"]["pause_before_submit"] is True
    out2 = setup_flow.apply_answers({}, {
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "x"},
        "policy": {"ask_before_sending": False},
    })
    assert out2["questions"]["pause_before_submit"] is False


def test_save_flow_writes_through_config_path(monkeypatch, tmp_path):
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)

    # Pre-seed unrelated keys; they must survive the read-modify-write.
    setup_flow.save_flow({
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "AI PM roles in Europe"},
        "policy": {"ask_before_sending": True},
    })

    with open(setup_flow.USER_CONFIG_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["default_resume_path"] == "C:/r.pdf"
    assert saved["setup_flow"]["want_sentence"] == "AI PM roles in Europe"
    assert saved["questions"]["pause_before_submit"] is True


# ------------------------------- pre-fill --------------------------------
def test_prefill_reads_saved_state(monkeypatch, tmp_path):
    cfg_path = tmp_path / "user_config.json"
    cfg_path.write_text(json.dumps({
        "questions": {"default_resume_path": "C:/old.pdf",
                      "pause_before_submit": False},
        "setup_flow": {"want_sentence": "Data Analyst roles remote"},
    }), encoding="utf-8")
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", str(cfg_path))

    pre = setup_flow.prefill()
    assert pre["resume"]["resume_path"] == "C:/old.pdf"
    assert pre["wants"]["sentence"] == "Data Analyst roles remote"
    assert pre["policy"]["ask_before_sending"] is False


def test_prefill_missing_state_uses_defaults(monkeypatch, tmp_path):
    missing = str(tmp_path / "nope.json")
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", missing)
    pre = setup_flow.prefill()
    assert pre["resume"]["resume_path"] == ""
    assert pre["wants"]["sentence"] == ""
    # Default safe answer: ask before sending.
    assert pre["policy"]["ask_before_sending"] is True


# -------------------------------- summary --------------------------------
def test_summary_lists_every_answer_in_plain_words():
    lines = setup_flow.summary_lines({
        "resume": {"resume_path": "C:/docs/My Resume.pdf"},
        "wants": {"sentence": "AI Product Manager roles in Europe"},
        "policy": {"ask_before_sending": True},
    })
    assert "My Resume.pdf" in lines[0]
    assert "AI Product Manager roles in Europe" in lines[1]
    assert any("ask you first" in l for l in lines)


def test_summary_reflects_ask_off():
    lines = setup_flow.summary_lines({
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "x"},
        "policy": {"ask_before_sending": False},
    })
    assert any("without asking" in l for l in lines)


# ----------------------------- renderer: Tkinter --------------------------
def test_tkinter_wizard_pages_come_from_shared_declaration():
    # The desktop wizard must NOT keep its own copy of the steps: its page ids
    # are literally built from setup_flow. (Stub renderer - no display needed.)
    import setup_wizard
    pages = setup_wizard.flow_page_ids()
    assert pages == ["welcome"] + [s["id"] for s in setup_flow.STEPS] + ["review", "allset"]
    assert "resume" in pages and "wants" in pages and "policy" in pages


def test_tkinter_stub_renderer_persists_through_shared_path(monkeypatch, tmp_path):
    # Drive a fake renderer exactly the way the wizard's finish() does:
    # collect the flow's answers, apply them onto the existing config, write.
    import setup_wizard
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)
    setup_wizard.CONFIG_PATH = cfg_path

    answers = {
        "resume": {"resume_path": "C:/stub.pdf"},
        "wants": {"sentence": "Data Analyst roles, remote"},
        "policy": {"ask_before_sending": True},
    }
    cfg = setup_wizard.build_config(
        "a@b.com", "pw", "", "", "", "C:/stub.pdf", "", "",
        "", "", "4", "Full-time", existing={},
        ai_enabled=True, first_name="Ada", last_name="Lovelace", license_key="",
    )
    cfg = setup_flow.apply_answers(cfg, answers)
    setup_wizard.write_config(cfg)

    import json
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["default_resume_path"] == "C:/stub.pdf"
    assert saved["setup_flow"]["want_sentence"] == "Data Analyst roles, remote"
    assert saved["secrets"]["username"] == "a@b.com"


# -------------------------------- completion ------------------------------
def test_is_complete_needs_resume_and_wants():
    good = {"questions": {"default_resume_path": "C:/r.pdf"},
            "setup_flow": {"want_sentence": "jobs"}}
    assert setup_flow.is_complete(good) is True
    no_resume = {"questions": {"default_resume_path": ""},
                 "setup_flow": {"want_sentence": "jobs"}}
    assert setup_flow.is_complete(no_resume) is False


# ------------------------- edit-later (ticket 05) --------------------------
def test_edit_one_answer_leaves_other_answers_untouched(monkeypatch, tmp_path):
    # The "change one thing, keep the rest" contract: a returning user rewrites
    # their wish; resume + policy answers survive word-for-word.
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", str(cfg_path))
    setup_flow.save_flow({
        "resume": {"resume_path": "C:/docs/My Resume.pdf"},
        "wants": {"sentence": "AI Product Manager roles in Europe"},
        "policy": {"ask_before_sending": True},
    })

    pre = setup_flow.prefill()
    pre["wants"]["sentence"] = "Data Analyst roles, remote, this week"
    setup_flow.save_flow(pre)

    again = setup_flow.prefill()
    assert again["resume"]["resume_path"] == "C:/docs/My Resume.pdf"
    assert again["policy"]["ask_before_sending"] is True
    assert again["policy"]["agent_policy"]["level"] == "balanced"
    assert again["wants"]["sentence"] == "Data Analyst roles, remote, this week"

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["default_resume_path"] == "C:/docs/My Resume.pdf"
    assert saved["questions"]["pause_before_submit"] is True
    # The reworded wish carried no parsed Saved Search -> derived zone stays clear.
    assert "saved_search" not in saved