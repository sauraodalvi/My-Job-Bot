'''
Unit tests for modules/license.py — the Free-plan daily limiter and Gumroad
license activation. Covers the counter (usage.json) and the activation flow
(verify API result -> save key / error message). The network call is mocked.

License: MIT  (https://opensource.org/license/mit)
'''

import json

import modules.license as license_mod


# ---------------------------------------------------------------------------
# Daily usage counter (referral_usage.json / referral_msg_usage.json)
# ---------------------------------------------------------------------------

def test_load_referral_usage_missing_is_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_USAGE_PATH", str(tmp_path / "referral_usage.json"))
    assert license_mod.referral_scans_today() == 0


def test_load_referral_usage_stale_date_resets(monkeypatch, tmp_path):
    usage = tmp_path / "referral_usage.json"
    usage.write_text(json.dumps({"date": "2099-01-01", "count": 7}), encoding="utf-8")
    monkeypatch.setattr(license_mod, "REFERRAL_USAGE_PATH", str(usage))
    assert license_mod.referral_scans_today() == 0

    usage.write_text(json.dumps({"date": license_mod._today(), "count": 7}), encoding="utf-8")
    assert license_mod.referral_scans_today() == 7


def test_record_referral_scan_increments(monkeypatch, tmp_path):
    usage = tmp_path / "referral_usage.json"
    monkeypatch.setattr(license_mod, "REFERRAL_USAGE_PATH", str(usage))
    usage.write_text(json.dumps({"date": license_mod._today(), "count": 1}), encoding="utf-8")
    assert license_mod.record_referral_scan() == 2
    data = json.loads(usage.read_text(encoding="utf-8"))
    assert data["count"] == 2


def test_can_scan_referral_free_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_USAGE_PATH", str(tmp_path / "referral_usage.json"))
    monkeypatch.setattr(license_mod, "referral_free_daily_limit", 1)
    monkeypatch.setattr(license_mod, "referral_paid_daily_limit", 4)
    monkeypatch.setattr(license_mod, "gumroad_license_key", "")

    monkeypatch.setattr(license_mod, "_load_referral_usage", lambda: 0)
    assert license_mod.can_scan_referral() is True
    assert license_mod.referral_scan_remaining() == 1
    monkeypatch.setattr(license_mod, "_load_referral_usage", lambda: 1)
    assert license_mod.can_scan_referral() is False
    assert license_mod.referral_scan_remaining() == 0


def test_can_scan_referral_paid_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_USAGE_PATH", str(tmp_path / "referral_usage.json"))
    monkeypatch.setattr(license_mod, "referral_free_daily_limit", 1)
    monkeypatch.setattr(license_mod, "referral_paid_daily_limit", 4)
    monkeypatch.setattr(license_mod, "gumroad_license_key", "PAID-KEY")

    monkeypatch.setattr(license_mod, "_load_referral_usage", lambda: 3)
    assert license_mod.can_scan_referral() is True
    monkeypatch.setattr(license_mod, "_load_referral_usage", lambda: 4)
    assert license_mod.can_scan_referral() is False


# ---------------------------------------------------------------------------
# Referral message usage counter
# ---------------------------------------------------------------------------

def test_load_referral_msg_usage_missing_is_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_MSG_USAGE_PATH", str(tmp_path / "referral_msg_usage.json"))
    assert license_mod.referral_messages_today() == 0


def test_record_referral_message_increments(monkeypatch, tmp_path):
    usage = tmp_path / "referral_msg_usage.json"
    monkeypatch.setattr(license_mod, "REFERRAL_MSG_USAGE_PATH", str(usage))
    usage.write_text(json.dumps({"date": license_mod._today(), "count": 4}), encoding="utf-8")
    assert license_mod.record_referral_message() == 5
    data = json.loads(usage.read_text(encoding="utf-8"))
    assert data["count"] == 5


def test_can_send_referral_free_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_MSG_USAGE_PATH", str(tmp_path / "referral_msg_usage.json"))
    monkeypatch.setattr(license_mod, "referral_msg_free_daily_limit", 3)
    monkeypatch.setattr(license_mod, "referral_msg_paid_daily_limit", 0)
    monkeypatch.setattr(license_mod, "gumroad_license_key", "")

    monkeypatch.setattr(license_mod, "_load_referral_msg_usage", lambda: 2)
    assert license_mod.can_send_referral() is True
    assert license_mod.referral_msg_remaining() == 1
    monkeypatch.setattr(license_mod, "_load_referral_msg_usage", lambda: 3)
    assert license_mod.can_send_referral() is False
    assert license_mod.referral_msg_remaining() == 0


def test_can_send_referral_paid_unlimited(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_MSG_USAGE_PATH", str(tmp_path / "referral_msg_usage.json"))
    monkeypatch.setattr(license_mod, "referral_msg_free_daily_limit", 3)
    monkeypatch.setattr(license_mod, "referral_msg_paid_daily_limit", 0)
    monkeypatch.setattr(license_mod, "gumroad_license_key", "PAID-KEY")

    monkeypatch.setattr(license_mod, "_load_referral_msg_usage", lambda: 99)
    assert license_mod.can_send_referral() is True
    assert license_mod.referral_msg_remaining() is None


# ---------------------------------------------------------------------------
# Daily usage counter (usage.json)
# ---------------------------------------------------------------------------

def test_load_usage_missing_file_is_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "USAGE_PATH", str(tmp_path / "usage.json"))
    assert license_mod.load_usage() == 0


def test_load_usage_reads_today_only(monkeypatch, tmp_path):
    usage = tmp_path / "usage.json"
    usage.write_text(json.dumps({"date": "2099-01-01", "count": 7}), encoding="utf-8")
    monkeypatch.setattr(license_mod, "USAGE_PATH", str(usage))
    assert license_mod.load_usage() == 0                  # stale date -> reset

    usage.write_text(json.dumps({"date": license_mod._today(), "count": 7}), encoding="utf-8")
    assert license_mod.load_usage() == 7                  # today -> kept


def test_record_application_increments(monkeypatch, tmp_path):
    usage = tmp_path / "usage.json"
    monkeypatch.setattr(license_mod, "USAGE_PATH", str(usage))
    usage.write_text(json.dumps({"date": license_mod._today(), "count": 3}), encoding="utf-8")

    assert license_mod.record_application() == 4
    data = json.loads(usage.read_text(encoding="utf-8"))
    assert data["count"] == 4
    assert data["date"] == license_mod._today()


# ---------------------------------------------------------------------------
# Free-plan gating
# ---------------------------------------------------------------------------

def test_can_submit_respects_daily_limit(monkeypatch, tmp_path, recwarn):
    monkeypatch.setattr(license_mod, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(license_mod, "free_daily_limit", 10)
    monkeypatch.setattr(license_mod, "gumroad_license_key", "")

    monkeypatch.setattr(license_mod, "load_usage", lambda: 9)
    assert license_mod.can_submit() is True
    monkeypatch.setattr(license_mod, "load_usage", lambda: 10)
    assert license_mod.can_submit() is False
    assert license_mod.remaining_today() == 0


def test_paid_user_never_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(license_mod, "gumroad_license_key", "AAAA-BBBB-CCCC-DDDD")
    monkeypatch.setattr(license_mod, "load_usage", lambda: 99)
    assert license_mod.is_paid() is True
    assert license_mod.can_submit() is True
    assert license_mod.remaining_today() is None


def test_is_paid_blank_key_is_free(monkeypatch):
    monkeypatch.setattr(license_mod, "gumroad_license_key", "   ")
    assert license_mod.is_paid() is False
    monkeypatch.setattr(license_mod, "gumroad_license_key", "")
    assert license_mod.is_paid() is False


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def test_activate_requires_a_key(monkeypatch):
    ok, message = license_mod.activate_license("   ")
    assert ok is False
    assert "Enter your license key" in message


def test_activate_success_saves_key(monkeypatch, tmp_path):
    cfg = tmp_path / "user_config.json"
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(license_mod, "verify_gumroad",
                        lambda key: {"success": True, "purchase": {"test": False}})

    ok, message = license_mod.activate_license("AAAA-BBBB-CCCC-DDDD")
    assert ok is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["secrets"]["gumroad_license_key"] == "AAAA-BBBB-CCCC-DDDD"


def test_activate_test_purchase_does_not_save(monkeypatch, tmp_path):
    cfg = tmp_path / "user_config.json"
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(license_mod, "verify_gumroad",
                        lambda key: {"success": True, "purchase": {"test": True}})

    ok, message = license_mod.activate_license("TEST-KEY")
    assert ok is True
    assert "TEST" in message
    assert not cfg.exists()


def test_activate_rejects_invalid_key(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(tmp_path / "user_config.json"))
    monkeypatch.setattr(license_mod, "verify_gumroad",
                        lambda key: {"success": False, "message": "No such license."})
    ok, message = license_mod.activate_license("BAD-KEY")
    assert ok is False
    assert "No such license" in message


def test_activate_rejects_refunded(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(tmp_path / "user_config.json"))
    monkeypatch.setattr(license_mod, "verify_gumroad",
                        lambda key: {"success": True, "purchase": {"refunded": True}})
    ok, message = license_mod.activate_license("REFUNDED-KEY")
    assert ok is False
    assert "refunded" in message.lower()


def test_activate_handles_network_error(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(tmp_path / "user_config.json"))
    monkeypatch.setattr(license_mod, "verify_gumroad",
                        lambda key: (_ for _ in ()).throw(OSError("offline")))
    ok, message = license_mod.activate_license("OFFLINE-KEY")
    assert ok is False
    assert "Could not reach Gumroad" in message


# ---------------------------------------------------------------------------
# Special test key (bypass for friend testing)
# ---------------------------------------------------------------------------

def test_activate_test_key_offline(monkeypatch, tmp_path):
    cfg = tmp_path / "user_config.json"
    monkeypatch.setattr(license_mod, "USER_CONFIG_PATH", str(cfg))
    # The test key must NOT hit the (unpatched) Gumroad network call.
    ok, message = license_mod.activate_license(license_mod.TEST_LICENSE_KEY)
    assert ok is True
    assert "unlimited" in message.lower()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["secrets"]["gumroad_license_key"] == license_mod.TEST_LICENSE_KEY


def test_test_key_acts_paid(monkeypatch):
    monkeypatch.setattr(license_mod, "gumroad_license_key", license_mod.TEST_LICENSE_KEY)
    assert license_mod.is_paid() is True
    assert license_mod.can_submit() is True   # never blocked
    assert license_mod.remaining_today() is None


# ---------------------------------------------------------------------------
# Per-job referral log (referral_job_log.json) — "one job = one referral"
# ---------------------------------------------------------------------------

def test_referral_sent_for_job_missing_is_false(monkeypatch, tmp_path):
    monkeypatch.setattr(license_mod, "REFERRAL_JOB_LOG_PATH", str(tmp_path / "job_log.json"))
    assert license_mod.referral_sent_for_job("4444967350") is False
    assert license_mod.referral_sent_for_job("") is False


def test_record_and_check_referral_job_sent(monkeypatch, tmp_path):
    log = tmp_path / "job_log.json"
    monkeypatch.setattr(license_mod, "REFERRAL_JOB_LOG_PATH", str(log))
    assert license_mod.referral_sent_for_job("4444967350") is False

    license_mod.record_referral_job_sent("4444967350", {"company": "Acme", "title": "PM", "hr_name": "M"})
    assert license_mod.referral_sent_for_job("4444967350") is True
    assert license_mod.referral_sent_for_job("other") is False
    data = json.loads(log.read_text(encoding="utf-8"))
    assert data["4444967350"]["company"] == "Acme"
    assert data["4444967350"]["title"] == "PM"
    assert license_mod.referral_jobs_sent_total() == 1


def test_referral_job_log_persists_across_calls(monkeypatch, tmp_path):
    log = tmp_path / "job_log.json"
    monkeypatch.setattr(license_mod, "REFERRAL_JOB_LOG_PATH", str(log))
    license_mod.record_referral_job_sent("111", {})
    license_mod.record_referral_job_sent("222", {})
    # Reload from disk (simulating a fresh process) must still see both jobs.
    assert license_mod.referral_jobs_sent_total() == 2
    assert license_mod.referral_sent_for_job("111") is True
    assert license_mod.referral_sent_for_job("222") is True


def test_record_referral_job_sent_empty_key_does_nothing(monkeypatch, tmp_path):
    log = tmp_path / "job_log.json"
    monkeypatch.setattr(license_mod, "REFERRAL_JOB_LOG_PATH", str(log))
    license_mod.record_referral_job_sent("", {})
    license_mod.record_referral_job_sent(None, {})
    assert license_mod.referral_jobs_sent_total() == 0
    assert not log.exists()


def test_referral_job_log_corrupt_file_is_ignored(monkeypatch, tmp_path):
    log = tmp_path / "job_log.json"
    monkeypatch.setattr(license_mod, "REFERRAL_JOB_LOG_PATH", str(log))
    log.write_text("{ not json", encoding="utf-8")
    assert license_mod.referral_sent_for_job("111") is False
    assert license_mod.referral_jobs_sent_total() == 0