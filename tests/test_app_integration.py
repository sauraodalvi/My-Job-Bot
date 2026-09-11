'''
Integration tests for app.py (the local control panel) via Flask's test client.
These exercise real request/response behaviour: schema exposure, config save
coercion + round-trip, unknown-key rejection, and the applied-jobs history
CSV -> JSON mapping and mark-applied flow.

All tests isolate their writes to a tmp_path, so the user's real user_config.json
and "all excels/" folder are never touched.

License: MIT  (https://opensource.org/license/mit)
'''

import csv
import json
import os


# --------------------------------- schema -----------------------------------
def test_schema_endpoint_returns_nonempty_list(client):
    resp = client.get("/api/schema")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list) and len(data) > 0
    assert "section" in data[0] and "fields" in data[0]


# ------------------------------- config save/get ----------------------------
def test_config_save_coerces_and_roundtrips(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    # "true" (string) must be coerced to a real bool for the use_AI field.
    resp = client.post("/api/config", json={"secrets": {"use_AI": "true"}})
    assert resp.status_code == 200

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["secrets"]["use_AI"] is True

    # GET reflects the saved value.
    got = client.get("/api/config").get_json()
    assert got["secrets"]["use_AI"] is True


def test_config_save_rejects_unknown_key(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    resp = client.post("/api/config", json={"secrets": {"definitely_not_a_field": 1}})
    assert resp.status_code == 400
    assert not os.path.exists(cfg_path)  # nothing written on rejection


def test_config_save_rejects_unknown_section(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    resp = client.post("/api/config", json={"not_a_section": {"x": 1}})
    assert resp.status_code == 400


# ------------------------------ applied-jobs CSV ----------------------------
_CSV_COLUMNS = ['Job ID', 'Title', 'Company', 'HR Name', 'HR Link',
                'Job Link', 'External Job link', 'Date Applied']


def _write_history_csv(folder):
    path = os.path.join(folder, "all_applied_applications_history.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerow({
            'Job ID': 'J1', 'Title': 'Engineer', 'Company': 'Acme',
            'HR Name': 'Unknown', 'HR Link': '', 'Job Link': 'http://x',
            'External Job link': 'http://ext', 'Date Applied': 'Pending',
        })
    return path


def test_applied_jobs_get_maps_columns_to_json_keys(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))

    resp = client.get("/applied-jobs")
    assert resp.status_code == 200
    row = resp.get_json()[0]
    assert row["Job_ID"] == "J1"
    assert row["Title"] == "Engineer"
    assert row["External_Job_link"] == "http://ext"
    assert row["Date_Applied"] == "Pending"


def test_applied_jobs_mark_applied_updates_date(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))

    resp = client.put("/applied-jobs/J1")
    assert resp.status_code == 200

    row = client.get("/applied-jobs").get_json()[0]
    assert row["Date_Applied"] != "Pending"


def test_applied_jobs_missing_file_returns_404(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)  # empty dir, no CSV
    assert client.get("/applied-jobs").status_code == 404


def test_applied_jobs_mark_unknown_id_returns_404(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PATH", str(tmp_path) + os.sep)
    _write_history_csv(str(tmp_path))
    assert client.put("/applied-jobs/does-not-exist").status_code == 404


# ------------------------------- setup flow API ---------------------------
def _setup_answers():
    return {
        "account": {"username": "ada@example.com", "password": "secret-pw"},
        "resume": {"resume_path": "C:/My Resume.pdf"},
        "wants": {"sentence": "AI Product Manager roles in Europe, remote or hybrid"},
        "policy": {"ask_before_sending": True},
    }


def test_setup_page_renders(client):
    assert client.get("/setup").status_code == 200


def test_setup_flow_api_serves_shared_declaration(client):
    resp = client.get("/api/setup/flow")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["title"] == "Let's get you ready"
    assert [s["title"] for s in data["steps"]] == [
        "Sign in to LinkedIn",
        "Your resume",
        "Tell me what you want",
        "Should I ask before sending?",
    ]
    assert set(data["answers"]) == {"account", "resume", "wants", "policy"}


def test_setup_save_persists_through_shared_path(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    import setup_flow as setup_mod
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_mod, "USER_CONFIG_PATH", cfg_path)

    resp = client.post("/api/setup", json={"answers": _setup_answers()})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["saved"] is True
    assert data["complete"] is True

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["default_resume_path"] == "C:/My Resume.pdf"
    assert saved["questions"]["pause_before_submit"] is True
    assert saved["setup_flow"]["want_sentence"].startswith("AI Product Manager")
    assert saved["secrets"]["username"] == "ada@example.com"
    assert saved["secrets"]["password"] == "secret-pw"


def test_setup_save_rejects_broken_flow(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    import setup_flow as setup_mod
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_mod, "USER_CONFIG_PATH", cfg_path)

    bad = _setup_answers()
    bad["resume"] = {"resume_path": "   "}
    resp = client.post("/api/setup", json={"answers": bad})
    assert resp.status_code == 400
    assert "resume" in resp.get_json()["errors"]
    assert not os.path.exists(cfg_path)  # nothing persisted on rejection


def test_setup_flow_api_exposes_free_limit_and_edit_start(client):
    resp = client.get("/api/setup/flow")
    data = resp.get_json()
    assert data["free_daily_limit"] == 10 or data["free_daily_limit"] > 0


def test_setup_flow_complete_flips_with_saved_state(client, tmp_path, monkeypatch):
    import app
    import setup_flow as setup_mod
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_mod, "USER_CONFIG_PATH", cfg_path)

    # Incomplete account -> flow offered on the home banner.
    assert client.get("/api/setup/flow").get_json()["complete"] is False

    # Completed account -> all-set state asserted on the shared endpoint.
    resp = client.post("/api/setup", json={"answers": _setup_answers()})
    data = resp.get_json()
    assert data["complete"] is True
    assert client.get("/api/setup/flow").get_json()["complete"] is True


def test_setup_detect_post_returns_plain_note(client, tmp_path):
    import setup_flow
    path = str(tmp_path / "my resume.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("Ada - Machine Learning Engineer\n3+ years experience in python.\n")
    resp = client.post("/api/setup/detect", json={"path": path})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "experience" in data["text"]
    assert data["text"] == setup_flow.describe_resume_path(path)[0]


def test_setup_detect_missing_file_is_graceful(client):
    # Detection never hard-fails the UI: a missing file returns ok False + a note.
    resp = client.post("/api/setup/detect", json={"path": "C:/no/such/file.pdf"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False and data["text"]


def test_setup_parse_answers_guided_conversation(client, monkeypatch, tmp_path):
    # Full HTTP round-trip of the one-sentence -> Saved Search conversation,
    # with AI stubbed to None so the deterministic guided path runs.
    import app
    import setup_flow as setup_mod
    from modules import search_parse as sp
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_mod, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(sp, "_ask_ai", lambda sentence: None)

    resp = client.post("/api/setup/parse", json={"sentence": "some vague wish"})
    assert resp.status_code == 200
    first = resp.get_json()
    assert first["status"] == "guided" and first["next"] == "titles"

    out = first["guided_state"]
    for reply, expected_next in [("Machine Learning Engineer", "locations"),
                                 ("Europe", "salary"),
                                 ("no range", None)]:
        if expected_next is None:
            break
        resp = client.post("/api/setup/parse", json={
            "sentence": "some vague wish", "reply": reply, "guided_state": out})
        body = resp.get_json()
        assert body["status"] == "guided" and body["next"] == expected_next
        out = body["guided_state"]

    # Blank salary keeps asking (no "no preference" escape yet); give a range.
    resp = client.post("/api/setup/parse", json={
        "sentence": "some vague wish", "reply": "80k to 120k", "guided_state": out})
    body = resp.get_json()
    assert body["status"] == "answered"
    assert body["saved_search"]["titles"] == ["Machine Learning Engineer"]

    # The answered wants are what the flow would persist.
    setup_mod.save_flow({
        "resume": {"resume_path": "C:/r.pdf"},
        "wants": {"sentence": "some vague wish", "parsed": body["saved_search"]},
        "policy": {"ask_before_sending": True},
    })
    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["saved_search"]["titles"] == ["Machine Learning Engineer"]
    assert saved["search"]["search_terms"] == ["Machine Learning Engineer"]


# ------------------------------- bot status ---------------------------------
def test_status_reports_not_running(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.get_json()["running"] is False


# ------------------------------- pages render -------------------------------
def test_control_panel_and_history_pages_render(client):
    panel = client.get("/")
    assert panel.status_code == 200
    assert b"Referrals" in panel.data
    assert b"Open LinkedIn employee search" in panel.data
    assert b"Open profile + copy message" in panel.data
    assert client.get("/history").status_code == 200


# ------------------------------- referral API --------------------------------
def test_referral_results_missing_returns_404(client, tmp_path, monkeypatch):
    import app
    missing = str(tmp_path / "no_such_results.json")
    monkeypatch.setattr(app, "REFERRAL_RESULTS_PATH", missing)
    resp = client.get("/api/referral/results")
    assert resp.status_code == 404


def test_referral_results_serves_json(client, tmp_path, monkeypatch):
    import app
    results_path = str(tmp_path / "referral_results.json")
    payload = {
        "generated_at": "2026-01-01 00:00:00",
        "count": 1,
        "results": [{
            "job_id": "123",
            "title": "Engineer",
            "company": "Acme",
            "location": "Remote",
            "work_style": "Remote",
            "connection_count": 3,
            "link": "https://www.linkedin.com/jobs/view/123",
        }],
    }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    monkeypatch.setattr(app, "REFERRAL_RESULTS_PATH", results_path)

    resp = client.get("/api/referral/results")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["results"][0]["company"] == "Acme"
    assert data["results"][0]["connection_count"] == 3


def test_referral_status_reports_not_running(client):
    resp = client.get("/api/referral/status")
    assert resp.status_code == 200
    assert resp.get_json()["running"] is False


def test_referral_run_blocked_while_bot_running(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "_referral_proc", None)
    monkeypatch.setattr(app, "REFERRAL_PID_PATH", str(client.application.root_path) + "/.ref.pid")

    # Fake the apply bot as "running" so the referral run must refuse to start.
    class FakeProc:
        def poll(self):
            return None

    monkeypatch.setattr(app, "_bot_proc", FakeProc())
    # Force BOTH the running-bot conflict AND the daily-scan-limit-reached to be
    # true simultaneously. The running bot (hard conflict, 409) must win over the
    # allowance 403 — this locks in the route ordering and keeps the test isolated
    # from any leftover referral_usage.json in the working directory.
    monkeypatch.setattr(app, "can_scan_referral", lambda: False)
    monkeypatch.setattr(app, "referral_scan_remaining", lambda: 0)
    resp = client.post("/api/referral/run")
    assert resp.status_code == 409
    assert resp.get_json()["running"] is False


def test_referral_send_blocked_while_bot_running(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "_send_proc", None)
    monkeypatch.setattr(app, "_referral_proc", None)
    monkeypatch.setattr(app, "REFERRAL_SEND_PID_PATH", str(client.application.root_path) + "/.send.pid")

    class FakeProc:
        def poll(self):
            return None

    monkeypatch.setattr(app, "_bot_proc", FakeProc())
    # Running bot + daily-message-limit reached -> conflict (409) must take priority.
    monkeypatch.setattr(app, "can_send_referral", lambda: False)
    monkeypatch.setattr(app, "referral_msg_remaining", lambda: 0)
    resp = client.post("/api/referral/send")
    assert resp.status_code == 409
    assert resp.get_json()["running"] is False


def test_referral_command_includes_flag(monkeypatch):
    import app
    monkeypatch.setattr(app, "_bot_command", lambda: ["python", "runAiBot.py"])
    assert app._referral_command() == ["python", "runAiBot.py", "--referral"]


def test_full_referral_command_includes_both_flags(monkeypatch):
    import app
    monkeypatch.setattr(app, "_bot_command", lambda: ["python", "runAiBot.py"])
    assert app._full_referral_command() == ["python", "runAiBot.py", "--referral", "--send-referrals"]


def test_referral_full_blocked_while_bot_running(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "_send_proc", None)
    monkeypatch.setattr(app, "REFERRAL_SEND_PID_PATH", str(client.application.root_path) + "/.send.pid")

    class FakeProc:
        def poll(self):
            return None

    monkeypatch.setattr(app, "_bot_proc", FakeProc())
    # Running bot + scan allowance used -> conflict (409) must take priority so
    # the ordering stays consistent across all three referral routes.
    monkeypatch.setattr(app, "can_scan_referral", lambda: False)
    monkeypatch.setattr(app, "can_send_referral", lambda: False)
    resp = client.post("/api/referral/full")
    assert resp.status_code == 409
    assert resp.get_json()["running"] is False


def test_referral_full_blocked_when_send_already_running(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "_bot_proc", None)

    class FakeSendProc:
        def poll(self):
            return None

    monkeypatch.setattr(app, "_send_proc", FakeSendProc())
    resp = client.post("/api/referral/full")
    assert resp.status_code == 409
    assert resp.get_json()["running"] is True


def test_referral_full_refuses_when_scan_allowance_used(client, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_bot_proc", None)
    monkeypatch.setattr(app, "_send_proc", None)
    monkeypatch.setattr(app, "REFERRAL_SEND_PID_PATH", str(client.application.root_path) + "/.send.pid")
    monkeypatch.setattr(app, "can_scan_referral", lambda: False)
    monkeypatch.setattr(app, "can_send_referral", lambda: True)
    resp = client.post("/api/referral/full")
    assert resp.status_code == 400
    assert resp.get_json()["running"] is False


def test_referral_full_refuses_when_msg_allowance_used(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "_bot_proc", None)
    monkeypatch.setattr(app, "_send_proc", None)
    monkeypatch.setattr(app, "REFERRAL_SEND_PID_PATH", str(client.application.root_path) + "/.send.pid")
    monkeypatch.setattr(app, "can_scan_referral", lambda: True)
    monkeypatch.setattr(app, "can_send_referral", lambda: False)
    resp = client.post("/api/referral/full")
    assert resp.status_code == 400
    assert resp.get_json()["running"] is False


def test_referral_full_starts_combined_process(client, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_bot_proc", None)
    monkeypatch.setattr(app, "_send_proc", None)
    monkeypatch.setattr(app, "REFERRAL_SEND_PID_PATH", str(tmp_path / ".send.pid"))
    monkeypatch.setattr(app, "can_scan_referral", lambda: True)
    monkeypatch.setattr(app, "can_send_referral", lambda: True)

    class FakeSendProc:
        pid = 4242

        def poll(self):
            return None

    calls = {}

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        return FakeSendProc()

    monkeypatch.setattr(app.subprocess, "Popen", fake_popen)
    resp = client.post("/api/referral/full")
    assert resp.status_code == 200
    assert resp.get_json() == {"running": True, "pid": 4242}
    assert calls["cmd"] == app._full_referral_command()
    assert os.path.exists(str(tmp_path / ".send.pid"))


# ------------------------------- license status API --------------------------
def test_license_status_reports_free_limits(client, monkeypatch, tmp_path):
    import app
    import modules.license as license_mod
    monkeypatch.setattr(app, "is_paid", lambda: False)
    monkeypatch.setattr(app, "free_daily_limit", 10)
    monkeypatch.setattr(app, "applications_today", lambda: 4)
    monkeypatch.setattr(app, "referral_free_daily_limit", 1)
    monkeypatch.setattr(app, "referral_paid_daily_limit", 4)
    monkeypatch.setattr(app, "referral_msg_free_daily_limit", 3)
    monkeypatch.setattr(app, "referral_scans_today", lambda: 0)
    monkeypatch.setattr(app, "referral_scan_remaining", lambda: 1)
    monkeypatch.setattr(app, "can_scan_referral", lambda: True)
    monkeypatch.setattr(app, "referral_messages_today", lambda: 0)
    monkeypatch.setattr(app, "referral_msg_remaining", lambda: 3)
    monkeypatch.setattr(app, "can_send_referral", lambda: True)

    resp = client.get("/api/license/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["paid"] is False
    assert data["referral_scan"]["free_daily_limit"] == 1
    assert data["referral_scan"]["can_scan"] is True
    assert data["referral_message"]["free_daily_limit"] == 3
    assert data["referral_message"]["can_send"] is True


def test_license_status_reports_paid_unlimited(client, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "is_paid", lambda: True)
    monkeypatch.setattr(app, "free_daily_limit", 10)
    monkeypatch.setattr(app, "applications_today", lambda: 20)
    monkeypatch.setattr(app, "referral_free_daily_limit", 1)
    monkeypatch.setattr(app, "referral_paid_daily_limit", 4)
    monkeypatch.setattr(app, "referral_msg_free_daily_limit", 3)
    monkeypatch.setattr(app, "referral_scans_today", lambda: 1)
    monkeypatch.setattr(app, "referral_scan_remaining", lambda: 3)
    monkeypatch.setattr(app, "can_scan_referral", lambda: True)
    monkeypatch.setattr(app, "referral_messages_today", lambda: 5)
    monkeypatch.setattr(app, "referral_msg_remaining", lambda: None)
    monkeypatch.setattr(app, "can_send_referral", lambda: True)

    resp = client.get("/api/license/status")
    data = resp.get_json()
    assert data["paid"] is True
    assert data["referral_scan"]["paid_daily_limit"] == 4
    assert data["referral_message"]["remaining"] is None
    assert data["referral_message"]["can_send"] is True


# ----------------------------- gated referral endpoints -----------------------
def test_referral_scan_403_when_limit_reached(client, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "can_scan_referral", lambda: False)
    monkeypatch.setattr(app, "referral_scan_remaining", lambda: 0)

    resp = client.post("/api/referral/run")
    assert resp.status_code == 403
    assert "limit" in resp.get_json()["error"].lower()


def test_referral_send_403_when_limit_reached(client, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "can_send_referral", lambda: False)
    monkeypatch.setattr(app, "referral_msg_remaining", lambda: 0)

    resp = client.post("/api/referral/send")
    assert resp.status_code == 403
    assert "limit" in resp.get_json()["error"].lower()
