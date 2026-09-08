"""Unit tests for the curated personalized referral messaging module."""
import json
import sys

import pytest

sys.path.insert(0, ".")

from modules.referral_personalized import (
    load_targets,
    _compose_personalized,
    _ai_draft_message,
    _pick,
)


class DummyClient:
    def __init__(self, text: str):
        self.model = DummyModel(text)


class DummyModel:
    def __init__(self, text: str):
        self._text = text

    def invoke(self, prompt):
        class R:
            content = prompt and self._text

        return R()


@pytest.fixture(autouse=True)
def _settings_patch(monkeypatch):
    monkeypatch.setattr("modules.referral_personalized.referral_ai_draft", True)


def test_load_targets_normalizes_and_aliases(tmp_path):
    f = tmp_path / "targets.json"
    f.write_text(json.dumps({
        "targets": [{
            "name": "Martina Santoro",
            "url": "https://www.linkedin.com/in/martina-santoro/en/?x=1",
            "link": "https://www.linkedin.com/jobs/view/4444967350",
            "job_id": "4444967350",
            "job_title": "Senior PM",
            "company_name": "Product Heroes",
            "hint": "met at Product School",
        }]
    }), encoding="utf-8")
    targets = load_targets(str(f))
    assert len(targets) == 1
    t = targets[0]
    assert t["name"] == "Martina Santoro"
    assert t["profile_url"] == "https://www.linkedin.com/in/martina-santoro"
    assert t["job_url"] == "https://www.linkedin.com/jobs/view/4444967350"
    assert t["job_id"] == "4444967350"
    assert t["title"] == "Senior PM"
    assert t["company"] == "Product Heroes"
    assert t["note"] == "met at Product School"


def test_load_targets_respects_real_two_char_username(tmp_path):
    f = tmp_path / "targets.json"
    f.write_text(json.dumps({
        "targets": [{
            "name": "Alice Blake",
            "url": "https://www.linkedin.com/in/ab",
        }]
    }), encoding="utf-8")
    targets = load_targets(str(f))
    assert targets[0]["profile_url"] == "https://www.linkedin.com/in/ab"


def test_load_targets_missing_file_returns_empty(tmp_path):
    assert load_targets(str(tmp_path / "nope.json")) == []


def test_load_targets_invalid_json_returns_empty(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{ not json", encoding="utf-8")
    assert load_targets(str(f)) == []


def test_load_targets_skips_entries_without_name(tmp_path):
    f = tmp_path / "targets.json"
    f.write_text(json.dumps({"targets": [{"url": "https://www.linkedin.com/in/x"}]}), encoding="utf-8")
    assert load_targets(str(f)) == []


def test_pick_aliases():
    assert _pick({"hr_link": "https://x"}, "profile_url", "hr_link", "url") == "https://x"
    assert _pick({"url": "https://x"}, "profile_url", "url") == "https://x"
    assert _pick({"name": "M"}, "name", "hr_name") == "M"
    assert _pick({}, "name", "hr_name") is None


def test_ai_draft_fallback_without_client():
    message = _compose_personalized(None, {"text": "profile text"}, {
        "name": "Test", "hr_name": "Martina Santoro",
        "title": "Senior PM", "company": "Product Heroes",
        "link": "https://www.linkedin.com/jobs/view/1",
        "note": "",
    })
    assert "Martina Santoro" in message
    assert "Product Heroes" in message
    assert "https://www.linkedin.com/jobs/view/1" in message


def test_ai_draft_recovers_from_empty_output():
    client = DummyClient("")
    message = _compose_personalized(client, {"name": "M", "headline": "x", "text": "body"}, {
        "name": "Test", "hr_name": "Martina", "title": "PM", "company": "Acme",
        "job_url": "https://www.linkedin.com/jobs/view/9", "note": "",
    })
    assert "Martina" in message or "Acme" in message


def test_ai_draft_message_returns_content():
    client = DummyClient("Hi Martina! Would you be open to referring me?")
    text = _ai_draft_message(client, {"name": "Martina", "headline": "PM", "text": "body"}, {
        "title": "PM", "company": "Acme", "job_url": "https://x", "note": "",
    })
    assert "Martina" in text


def test_ai_draft_message_returns_empty_without_client():
    assert _ai_draft_message(None, {"text": "body"}, {"title": "t"}) == ""