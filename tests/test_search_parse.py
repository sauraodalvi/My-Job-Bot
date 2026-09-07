'''
Unit tests for modules/search_parse.py - the "Tell me what you want" step that
turns ONE plain-English sentence into a Saved Search.

Pins the contract:
  * next_state(sentence) is THE entry point for both UIs and tests,
  * AI-on clean parse      -> answered with a Saved Search + one plain confirmation,
  * AI-on but no job titles-> need_clarify with EXACTLY ONE targeted question,
  * AI-off / parse failure -> guided, missing pieces asked one at a time,
  * the Saved Search is the single source of truth: legacy search.* filters are
    DERIVED from it (salary: USD-only by documented bracket; recency: by table),
  * setup_flow.save_flow stores the Saved Search + derived filters for it.

AI calls are stubbed by monkeypatching search_parse._ask_ai.

License: MIT  (https://opensource.org/license/mit)
'''

import json

import pytest

import setup_flow
from modules import search_parse as sp


# --------------------------------- AI on ------------------------------------

def test_ai_clean_parse_answers_with_saved_search(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: json.dumps({
        "titles": ["AI Product Manager"], "locations": ["Europe"],
        "salary": {"min": 80000, "max": 130000, "currency": "EUR"},
        "recency": "past_week", "on_site": ["Remote", "Hybrid"],
    }))
    out = sp.next_state("AI Product Manager roles in Europe, remote or hybrid, EUR 80-130k, this week.")
    assert out["status"] == "answered"
    ss = out["saved_search"]
    assert ss["titles"] == ["AI Product Manager"]
    assert ss["locations"] == ["Europe"]
    assert ss["salary"]["currency"] == "EUR"
    assert ss["recency"] == "past_week"
    assert "Remote" in ss["on_site"]
    assert "80k" in out["confirmation"] and "last week" in out["confirmation"]


def test_ai_without_job_titles_asks_exactly_one_question(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: json.dumps({
        "titles": [], "locations": ["Europe"],
        "salary": None, "recency": "past_week", "on_site": ["Remote"],
    }))
    out = sp.next_state("I want a job in Europe, remote, this week.")
    assert out["status"] == "need_clarify"
    assert out["next"] == "titles"
    assert "titles" in out["question"].lower()
    assert out["guided_state"]["mode"] == "clarify"


def test_ai_answering_reply_after_clarify_answers(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: json.dumps({
        "titles": [], "locations": ["Europe"],
        "salary": None, "recency": "past_week", "on_site": ["Remote"],
    }))
    first = sp.next_state("I want a job in Europe, remote, this week.")
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("I want a job in Europe, remote, this week.",
                        reply="Data Analyst and Product Manager",
                        state=first["guided_state"])
    assert out["status"] == "guided" and out["next"] == "salary"
    out = sp.next_state("I want a job in Europe, remote, this week.",
                        reply="80k to 100k",
                        state=out["guided_state"])
    assert out["status"] == "answered"
    assert set(out["saved_search"]["titles"]) == {"Data Analyst", "Product Manager"}


# --------------------------------- AI off -----------------------------------

def test_ai_off_full_sentence_answers_without_guidance(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("Data Analyst jobs in Europe, $70k to $100k, this month.")
    assert out["status"] == "answered"
    ss = out["saved_search"]
    assert "Data Analyst" in ss["titles"]
    assert ss["locations"] == ["Europe"]
    assert ss["salary"]["currency"] == "USD"
    assert ss["recency"] == "past_month"


def test_empty_sentence_asks_for_titles(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("")
    assert out["status"] == "guided"
    assert out["question"] == sp.GUIDED_QUESTIONS["titles"]


def test_guided_conversation_asks_missing_pieces_one_at_a_time(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("some job")
    assert out["status"] == "guided" and out["next"] == "titles"

    out = sp.next_state("some job", "Machine Learning Engineer and Data Scientist", out["guided_state"])
    assert out["status"] == "guided" and out["next"] == "locations"

    out = sp.next_state("some job", "Europe", out["guided_state"])
    assert out["status"] == "guided" and out["next"] == "salary"

    out = sp.next_state("some job", "80k to 120k dollars", out["guided_state"])
    assert out["status"] == "answered"
    ss = out["saved_search"]
    assert ss["titles"] == ["Machine Learning Engineer", "Data Scientist"]
    assert ss["locations"] == ["Europe"]
    assert ss["salary"]["currency"] == "USD"
    assert ss["salary"]["min"] == 80000


def test_guided_salary_accepts_word_units_thousand_and_million(monkeypatch):
    # The guided help text itself says e.g. '80 to 130 thousand euros' - the
    # word units must scale exactly like 'k' / 'm' (regression: the regex
    # matched 'thousand' but _numbers_k never multiplied it).
    assert sp._detect_salary("90 to 130 thousand euros")["min"] == 90000
    assert sp._detect_salary("90 to 130 thousand euros")["max"] == 130000
    assert sp._detect_salary("1 million dollars")["min"] == 1000000

    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("some job")
    assert out["status"] == "guided" and out["next"] == "titles"
    out = sp.next_state("some job", "Machine Learning Engineer", out["guided_state"])
    out = sp.next_state("some job", "Europe", out["guided_state"])
    out = sp.next_state("some job", "90 to 130 thousand euros", out["guided_state"])
    assert out["status"] == "answered"
    assert out["saved_search"]["salary"] == {"min": 90000, "max": 130000, "currency": "EUR"}


# -------------------- single source: derived legacy filters ------------------

def test_recency_derives_legacy_date_posted():
    assert sp.derived_date_posted({"recency": "past_week"}) == "Past week"
    assert sp.derived_date_posted({"recency": "past_24h"}) == "Past 24 hours"
    assert sp.derived_date_posted({"recency": "any_time"}) == ""
    assert sp.derived_date_posted({}) == ""


def test_usd_salary_maps_to_documented_bracket():
    assert sp.derived_salary({"salary": {"min": 90000, "max": 140000, "currency": "USD"}}) == "$80,000+"
    assert sp.derived_salary({"salary": {"min": 45000, "currency": "USD"}}) == "$40,000+"
    assert sp.derived_salary({"salary": {"min": 250000, "currency": "USD"}}) == "$200,000+"
    assert sp.derived_salary({"salary": {"min": 30000, "currency": "USD"}}) == ""
    assert sp.derived_salary({}) == ""


def test_non_usd_salary_stays_on_search_not_legacy_filter():
    ss = {"salary": {"min": 80000, "max": 130000, "currency": "EUR"}}
    assert sp.derived_salary(ss) == ""
    assert ss["salary"]["currency"] == "EUR"


def test_derive_search_is_a_pure_projection():
    ss = {
        "titles": ["AI Product Manager"], "locations": ["Europe"],
        "salary": {"min": 100000, "currency": "USD"},
        "recency": "past_week", "on_site": ["Remote"],
    }
    derived = sp.derive_search(ss)
    assert derived["search_terms"] == ["AI Product Manager"]
    assert derived["search_location"] == "Europe"
    assert derived["date_posted"] == "Past week"
    assert derived["salary"] == "$100,000+"
    assert derived["on_site"] == ["Remote"]


# ------------------- setup_flow stores single source ------------------------

def test_save_flow_stores_saved_search_and_derived_filters(monkeypatch, tmp_path):
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)

    sentence = "Data Analyst roles in Europe, $80k+, this week."
    out = sp.next_state(sentence)
    assert out["status"] == "answered"
    setup_flow.save_flow({
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": sentence, "parsed": out["saved_search"]},
        "policy": {"ask_before_sending": True},
    })

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["setup_flow"]["want_sentence"] == sentence
    assert saved["saved_search"]["titles"] == out["saved_search"]["titles"]
    assert saved["search"]["search_terms"] == out["saved_search"]["titles"]
    assert saved["search"]["search_location"] == "Europe"
    assert saved["search"]["date_posted"] == "Past week"
    assert saved["search"]["salary"] == "$80,000+"

    pre = setup_flow.prefill()
    assert pre["wants"]["sentence"] == sentence
    assert pre["wants"]["parsed"]["titles"] == out["saved_search"]["titles"]


def test_apply_answers_stores_unparsed_sentence_without_saved_search(monkeypatch, tmp_path):
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)
    cfg = setup_flow.apply_answers({}, {
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "some vague wish"},
        "policy": {"ask_before_sending": True},
    })
    assert "saved_search" not in cfg
    assert cfg["setup_flow"]["want_sentence"] == "some vague wish"


# --------------- remote/hybrid live in locations must not duplicate ----------
def test_ai_locations_workstyles_moved_to_on_site_and_never_duplicated(monkeypatch):
    # Real-world AI output: "Remote"/"Hybrid" listed as locations AND on_site.
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: json.dumps({
        "titles": ["AI Product Manager"], "locations": ["Remote", "Hybrid", "Europe"],
        "salary": {"min": 90000, "max": 130000, "currency": "EUR"},
        "recency": "past_week", "on_site": ["Remote", "Hybrid"],
    }))
    out = sp.next_state("AI Product Manager roles in Europe, remote or hybrid, EUR 90k to 130k, this week.")
    ss = out["saved_search"]
    assert ss["locations"] == ["Europe"]
    assert set(ss["on_site"]) == {"Remote", "Hybrid"}
    # The confirmation must not list a work style twice.
    assert out["confirmation"].count("Remote") == 1
    assert out["confirmation"].count("Hybrid") == 1
    derived = sp.derive_search(ss)
    assert derived["search_location"] == "Europe"
    assert set(derived["on_site"]) == {"Remote", "Hybrid"}


def test_guided_reply_of_just_remote_satisfies_location(monkeypatch):
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)
    out = sp.next_state("some job")
    assert out["status"] == "guided" and out["next"] == "titles"
    out = sp.next_state("some job", "Data Analyst", out["guided_state"])
    assert out["status"] == "guided" and out["next"] == "locations"
    out = sp.next_state("some job", "Remote", out["guided_state"])
    assert out["status"] == "guided" and out["next"] == "salary"  # no re-ask
    out = sp.next_state("some job", "80k", out["guided_state"])
    assert out["status"] == "answered"
    assert out["saved_search"]["locations"] == []
    assert out["saved_search"]["on_site"] == ["Remote"]