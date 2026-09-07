import sys

sys.path.insert(0, ".")

import pytest

from modules import dry_run


@pytest.fixture(autouse=True)
def reset_counts():
    dry_run._counts.clear()
    yield


def test_flag_off_by_default():
    assert "--dry-run" not in sys.argv
    assert dry_run.DRY_RUN is False
    assert dry_run.is_dry_run() is False


def test_flag_on_when_arg_present():
    assert dry_run.DRY_RUN == ("--dry-run" in sys.argv)


def test_max_jobs_default():
    assert isinstance(dry_run.DRY_MAX_JOBS, int)
    assert dry_run.DRY_MAX_JOBS > 0
    assert 1 <= dry_run.DRY_MAX_JOBS <= 30


def test_max_jobs_env_override(monkeypatch):
    monkeypatch.setattr(dry_run, "DRY_MAX_JOBS", 2)
    assert dry_run.is_dry_run() is False
    assert dry_run.DRY_MAX_JOBS == 2


def test_counts_only_accumulate_when_enabled(monkeypatch):
    monkeypatch.setattr(dry_run, "DRY_RUN", True)
    dry_run.count("easy_apply")
    dry_run.count("easy_apply")
    dry_run.count("external")
    assert dry_run._counts.get("easy_apply") == 2
    assert dry_run._counts.get("external") == 1
    assert "referral_dm" not in dry_run._counts


def test_summary_formats_labels():
    dry_run._counts.clear()
    dry_run._counts["referral_gmail"] = 4
    s = dry_run.summary()
    assert "4" in s
    assert "Referral Gmails rehearsed" in s


def test_empty_summary():
    assert dry_run.summary() == "[DRY RUN] No actions rehearsed."


def test_reset():
    dry_run._counts["easy_apply"] = 7
    dry_run.reset()
    assert dry_run._counts.get("easy_apply") is None