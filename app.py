'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Local "control panel" web app. It lets a non-technical person configure and run
the tool from a browser instead of editing Python files and using a terminal.

IMPORTANT - how configuration works:
  * This app reads/writes ONLY `user_config.json` at the project root.
  * It NEVER edits the config/*.py files.
  * The config/*.py modules load user_config.json over their built-in defaults
    (see config/_overrides.py), so saving here changes the tool's behaviour
    while leaving the classic "edit the .py files" workflow intact. With no
    user_config.json present the tool behaves exactly as it always has.

SECURITY: this app handles LinkedIn credentials, so it binds to 127.0.0.1 only
(never 0.0.0.0) and runs with debug OFF. Do not change these.
'''

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import csv
from datetime import datetime
import os
import sys
import json
import copy
import signal
import subprocess
import threading
import importlib

import config_schema
import setup_flow
from config import _overrides
from modules.license import (
    is_paid, free_daily_limit, applications_today,
    referral_scans_today, referral_scan_remaining,
    referral_messages_today, referral_msg_remaining,
    can_scan_referral, can_send_referral, referral_paid_daily_limit,
    referral_free_daily_limit, referral_msg_free_daily_limit,
)
from modules.search_parse import next_state as parse_search_sentence

app = Flask(__name__)
CORS(app)

# Project root is the folder this file lives in.
ROOT = os.path.dirname(os.path.abspath(__file__))
USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH
LOG_PATH = os.path.join(ROOT, ".bot_run.log")
PID_PATH = os.path.join(ROOT, ".bot_run.pid")

PATH = 'all excels/'

# Referral-finder outputs (the bot writes referral_results.json; app.py serves it).
REFERRAL_RESULTS_PATH = os.path.join(ROOT, 'referral_results.json')
REFERRAL_LOG_PATH = os.path.join(ROOT, '.referral_run.log')
REFERRAL_PID_PATH = os.path.join(ROOT, '.referral_run.pid')

# Referral messaging outputs
REFERRAL_MSG_LOG_PATH = os.path.join(ROOT, 'referral_message_log.csv')
REFERRAL_SEND_LOG_PATH = os.path.join(ROOT, '.referral_send.log')
REFERRAL_SEND_PID_PATH = os.path.join(ROOT, '.referral_send.pid')


# ===========================================================================
# Default config values (the pristine config/*.py defaults, ignoring any
# user_config.json). Captured once at startup so /api/config can always show
# "default overlaid with the user's current saved values".
# ===========================================================================
def _load_defaults() -> dict:
    '''
    Import each config module with overrides temporarily disabled, so we read
    the untouched Python defaults regardless of whether user_config.json exists
    right now. Returns {config_module: {key: default_value}}.
    '''
    original_loader = _overrides.load_user_config
    _overrides.load_user_config = lambda: {}
    try:
        import config.secrets as _secrets
        import config.personals as _personals
        import config.questions as _questions
        import config.search as _search
        import config.settings as _settings
        modules = {
            "secrets": _secrets,
            "personals": _personals,
            "questions": _questions,
            "search": _search,
            "settings": _settings,
        }
        # Reload in case they were already imported (with real overrides) earlier.
        for module in modules.values():
            importlib.reload(module)
        defaults = {}
        for field in config_schema.iter_fields():
            module_name = field["config_module"]
            key = field["key"]
            module = modules.get(module_name)
            defaults.setdefault(module_name, {})[key] = getattr(module, key, None)
        return defaults
    finally:
        _overrides.load_user_config = original_loader


DEFAULTS = _load_defaults()


# ===========================================================================
# Config API helpers
# ===========================================================================
def _effective_config() -> dict:
    '''
    Return {config_module: {key: value}} of the pristine defaults overlaid with
    the CURRENT contents of user_config.json (re-read from disk on every call).
    Only keys defined in config_schema are included.
    '''
    effective = copy.deepcopy(DEFAULTS)
    user = _overrides.load_user_config()
    for field in config_schema.iter_fields():
        module_name = field["config_module"]
        key = field["key"]
        section = user.get(module_name)
        if isinstance(section, dict) and key in section:
            effective[module_name][key] = section[key]
    return effective


def _coerce(field_type: str, value):
    '''
    Coerce an incoming JSON value into the type declared for the field in the
    schema. Raises ValueError on invalid numbers so the caller can reject them.
    '''
    if field_type in ("text", "password", "textarea", "select"):
        return "" if value is None else str(value)

    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, (int, float)):
            number = value
        else:
            text = str(value).strip()
            if text == "":
                raise ValueError("expected a number, got an empty value")
            number = float(text)
        # Keep whole numbers as ints (the config defaults are ints).
        if isinstance(number, float) and number.is_integer():
            return int(number)
        return number

    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field_type == "list":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() != ""]
        text = str(value).strip()
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip() != ""]

    # Unknown type: pass through untouched.
    return value


# ===========================================================================
# Bot subprocess management (run / stop / status / logs)
# ===========================================================================
_bot_proc = None
_bot_lock = threading.Lock()


# A separate tracked process for referral-finder runs (same runAiBot.py but with
# the --referral flag). Kept apart from the apply run so a referral scan never
# collides with an in-progress apply run, and /api/stop can shut both down.
_referral_proc = None
_referral_lock = threading.Lock()


def _referral_is_running() -> bool:
    '''True if the referral-finder subprocess is still alive.'''
    global _referral_proc
    if _referral_proc is None:
        return False
    if _referral_proc.poll() is None:
        return True
    _referral_proc = None
    try:
        os.remove(REFERRAL_PID_PATH)
    except OSError:
        pass
    return False


def _bot_command():
    '''The command used to launch the bot. Isolated so tests can monkeypatch it.'''
    # "-X utf8" makes print()/stdout use UTF-8 regardless of the console code
    # page, so job titles/descriptions with non-ASCII glyphs can never crash the
    # bot with a cp1252 UnicodeEncodeError.
    return [sys.executable, "-u", "-X", "utf8", os.path.join(ROOT, "runAiBot.py")]


def _referral_command():
    '''The command used to launch the bot in referral-find mode.'''
    return _bot_command() + ["--referral"]


# A separate tracked process for referral-send runs (--send-referrals flag).
_send_proc = None
_send_lock = threading.Lock()


def _send_is_running() -> bool:
    '''True if the referral-send subprocess is still alive.'''
    global _send_proc
    if _send_proc is None:
        return False
    if _send_proc.poll() is None:
        return True
    _send_proc = None
    try:
        os.remove(REFERRAL_SEND_PID_PATH)
    except OSError:
        pass
    return False


def _send_command():
    '''The command used to launch the bot in send-referrals mode.'''
    return _bot_command() + ["--send-referrals"]


def _full_referral_command():
    '''The command used to launch the one-click referral flow: scan THEN send
    referral messages in the same authenticated session.'''
    return _bot_command() + ["--referral", "--send-referrals"]


def _is_running() -> bool:
    '''True if the tracked bot subprocess exists and has not exited.'''
    global _bot_proc
    if _bot_proc is None:
        return False
    if _bot_proc.poll() is None:
        return True
    # Process has exited; clean up tracking + PID file.
    _bot_proc = None
    _remove_pid_file()
    return False


def _remove_pid_file():
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def _terminate(proc) -> None:
    '''Terminate the subprocess and, where feasible, its child processes.'''
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process tree on Windows.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # We launched with start_new_session=True, so the child is its own
            # process-group leader; signal the whole group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    # Give it a moment, then force-kill if still alive.
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


@app.route('/')
def home():
    """Serve the control panel single-page app."""
    return render_template('control_panel.html')


@app.route('/history')
def history():
    """Serve the applied-jobs history page."""
    return render_template('index.html')


@app.route('/setup')
def setup_page():
    """Serve the "Let's get you ready" onboarding flow."""
    return render_template('setup_flow.html')


@app.route('/api/setup/flow', methods=['GET'])
def api_setup_flow():
    '''The shared setup-flow declaration + current saved answers, so the web
    renderer never duplicates any step logic.'''
    answers = setup_flow.prefill()
    return jsonify({
        "title": setup_flow.FLOW_TITLE,
        "welcome_sentence": setup_flow.WELCOME_SENTENCE,
        "welcome_notes": setup_flow.WELCOME_NOTES,
        "steps": setup_flow.STEPS,
        "answers": answers,
        "complete": setup_flow.is_complete(),
        "free_daily_limit": free_daily_limit,
        "unlocked": setup_flow.has_license(),
        "start_step": request.args.get('edit') or None,
    })


@app.route('/api/setup/detect', methods=['POST'])
def api_setup_detect():
    '''Detect a resume profile for a chosen file (the "trust moment"). The file
    stays a snapshot and the extracted profile is a separate record.'''
    payload = request.get_json(silent=True)
    path = str((payload or {}).get("path") or "").strip()
    text, ok = setup_flow.describe_resume_path(path)
    return jsonify({"path": path, "text": text, "ok": ok})


@app.route('/api/setup/parse', methods=['POST'])
def api_setup_parse():
    '''Parse the "what you want" sentence into a Saved Search, or ask the one
    missing plain-word question (guided / clarify) that gets there.'''
    payload = request.get_json(silent=True) or {}
    sentence = str(payload.get("sentence") or "").strip()
    reply = payload.get("reply")
    state = payload.get("guided_state")
    if not isinstance(state, dict):
        state = None
    return jsonify(parse_search_sentence(sentence, reply=reply, state=state))


@app.route('/api/setup', methods=['POST'])
def api_save_setup():
    '''Validates the flow answers and persists them through the shared save
    path (the same user_config.json the tool reads).'''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "answers" not in payload:
        return jsonify({"error": "Expected a JSON object with an `answers` field"}), 400
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return jsonify({"error": "`answers` must be an object"}), 400

    errors = setup_flow.validate_flow(answers)
    if errors:
        return jsonify({"errors": errors}), 400

    setup_flow.save_flow(answers)
    return jsonify({
        "saved": True,
        "answers": setup_flow.prefill(),
        "complete": setup_flow.is_complete(),
        "free_daily_limit": free_daily_limit,
        "unlocked": setup_flow.has_license(),
    })


# The applied-jobs history CSV the bot writes, and how its columns map to the JSON
# keys the history page consumes.
_HISTORY_CSV = 'all_applied_applications_history.csv'
_HISTORY_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'HR Name': 'HR_Name',
    'HR Link': 'HR_Link',
    'Job Link': 'Job_Link',
    'External Job link': 'External_Job_link',
    'Date Applied': 'Date_Applied',
}


@app.route('/applied-jobs', methods=['GET'])
def get_applied_jobs():
    """Return the applied-jobs history as JSON for the history page."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": "No applications history found yet."}), 404
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _HISTORY_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/applied-jobs/<job_id>', methods=['PUT'])
def mark_job_applied(job_id):
    """Stamp one job's 'Date Applied' (matched by Job ID) with the current time."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": f"History file not found at {csv_path}"}), 404
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = list(reader)
        matched = False
        for row in rows:
            if row.get('Job ID') == job_id:
                row['Date Applied'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                matched = True
        if not matched:
            return jsonify({"error": f"Job ID {job_id} not found"}), 404
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"message": "Date Applied updated."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# Control-panel API
# ===========================================================================
@app.route('/api/schema', methods=['GET'])
def api_schema():
    '''Returns the field schema the UI renders its forms from.'''
    return jsonify(config_schema.SCHEMA)


@app.route('/api/config', methods=['GET'])
def api_get_config():
    '''
    Returns the effective config: pristine defaults overlaid with the current
    user_config.json, grouped by config module (secrets, personals, questions,
    search, settings).
    '''
    return jsonify(_effective_config())


@app.route('/api/config', methods=['POST'])
def api_save_config():
    '''
    Accepts {config_module: {key: value}}, validates against the schema, coerces
    each value to its declared type, rejects unknown modules/keys, merges into
    user_config.json (read-modify-write) and returns the full saved config.
    '''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object of {section: {key: value}}"}), 400

    valid = config_schema.valid_keys()
    unknown = []
    coerced = {}

    for section, values in payload.items():
        if not isinstance(values, dict):
            return jsonify({"error": f"Section '{section}' must be an object"}), 400
        if section not in valid:
            unknown.append(section)
            continue
        for key, value in values.items():
            field = valid[section].get(key)
            if field is None:
                unknown.append(f"{section}.{key}")
                continue
            try:
                coerced.setdefault(section, {})[key] = _coerce(field["type"], value)
            except ValueError as err:
                return jsonify({"error": f"Invalid value for '{section}.{key}': {err}"}), 400

    if unknown:
        return jsonify({"error": "Unknown settings rejected", "unknown": unknown}), 400

    # Read-modify-write user_config.json.
    current = _overrides.load_user_config()
    for section, values in coerced.items():
        target = current.get(section)
        if not isinstance(target, dict):
            target = {}
        target.update(values)
        current[section] = target

    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(current, file, indent=2, ensure_ascii=False)
    except OSError as err:
        return jsonify({"error": f"Could not save settings: {err}"}), 500

    return jsonify(current)


@app.route('/api/run', methods=['POST'])
def api_run():
    '''Starts the bot as a subprocess if it isn't already running.'''
    global _bot_proc
    with _bot_lock:
        if _is_running():
            return jsonify({"running": True, "pid": _bot_proc.pid,
                            "message": "The tool is already running."})
        try:
            # Truncate the log at the start of each run.
            log_file = open(LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _bot_proc = subprocess.Popen(_bot_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_bot_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _bot_proc.pid})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    '''Stops the running bot subprocess(es) (and their children where possible).'''
    global _bot_proc, _referral_proc, _send_proc
    with _bot_lock:
        if _bot_proc is not None:
            _terminate(_bot_proc)
            _bot_proc = None
        _remove_pid_file()
    with _referral_lock:
        if _referral_proc is not None:
            _terminate(_referral_proc)
            _referral_proc = None
        try:
            os.remove(REFERRAL_PID_PATH)
        except OSError:
            pass
    with _send_lock:
        if _send_proc is not None:
            _terminate(_send_proc)
            _send_proc = None
        try:
            os.remove(REFERRAL_SEND_PID_PATH)
        except OSError:
            pass
    return jsonify({"running": False})


@app.route('/api/status', methods=['GET'])
def api_status():
    '''Reports whether the bot subprocess is currently running.'''
    with _bot_lock:
        running = _is_running()
        pid = _bot_proc.pid if (running and _bot_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    '''
    Returns the run log starting from byte offset ?offset=N, plus the byte
    offset to read from next time. The UI polls this while the bot runs.
    '''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                # Log was truncated (a new run started); start over.
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


# ===========================================================================
# Referral-finder API
# ===========================================================================
@app.route('/api/referral/run', methods=['POST'])
def api_referral_run():
    '''Starts the bot in referral-find mode if neither an apply run nor a
    referral run is already active.'''
    global _referral_proc
    if not can_scan_referral():
        remaining = referral_scan_remaining() or 0
        return jsonify({"running": False, "error": f"Referral scan daily limit reached ({remaining} left). Upgrade for more scans per day."}), 403
    with _bot_lock:
        if _is_running():
            return jsonify({"running": False, "error": "The main tool is running. Stop it before a referral scan."}), 409
    with _referral_lock:
        if _referral_is_running():
            return jsonify({"running": True, "pid": _referral_proc.pid,
                            "message": "A referral scan is already running."})
        try:
            log_file = open(REFERRAL_LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _referral_proc = subprocess.Popen(_referral_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(REFERRAL_PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_referral_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _referral_proc.pid})


@app.route('/api/referral/status', methods=['GET'])
def api_referral_status():
    '''Reports whether the referral-finder subprocess is currently running.'''
    with _referral_lock:
        running = _referral_is_running()
        pid = _referral_proc.pid if (running and _referral_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/referral/results', methods=['GET'])
def api_referral_results():
    '''Returns the latest referral_results.json (or a clear "not found" error).'''
    if not os.path.exists(REFERRAL_RESULTS_PATH):
        return jsonify({"error": "No referral results yet. Run a referral scan first."}), 404
    try:
        with open(REFERRAL_RESULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as err:
        return jsonify({"error": f"Could not read referral results: {err}"}), 500


@app.route('/api/referral/logs', methods=['GET'])
def api_referral_logs():
    '''Returns the referral-run log from byte offset ?offset=N, mirroring /api/logs.'''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(REFERRAL_LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(REFERRAL_LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


# ===========================================================================
# Referral-messaging API (sends DMs/emails to HR contacts from referral scan)
# ===========================================================================
@app.route('/api/referral/send', methods=['POST'])
def api_referral_send():
    '''Starts the bot in send-referrals mode. Enriches referral results with
    HR info, then sends LinkedIn DMs and/or Gmail emails.'''
    global _send_proc
    if not can_send_referral():
        remaining = referral_msg_remaining() or 0
        return jsonify({"running": False, "error": f"Referral message daily limit reached ({remaining} left). Upgrade for unlimited messages."}), 403
    with _bot_lock:
        if _is_running():
            return jsonify({"running": False, "error": "The main tool is running. Stop it first."}), 409
    with _referral_lock:
        if _referral_is_running():
            return jsonify({"running": False, "error": "A referral scan is running. Wait for it to finish."}), 409
    with _send_lock:
        if _send_is_running():
            return jsonify({"running": True, "pid": _send_proc.pid,
                            "message": "Referral messaging is already running."})
        # Check that referral results exist
        if not os.path.exists(REFERRAL_RESULTS_PATH):
            return jsonify({"running": False, "error": "No referral results found. Run a referral scan first."}), 404
        try:
            log_file = open(REFERRAL_SEND_LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _send_proc = subprocess.Popen(_send_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(REFERRAL_SEND_PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_send_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _send_proc.pid})


@app.route('/api/referral/full', methods=['POST'])
def api_referral_full():
    '''One-click: scan for referral jobs, then send messages in one process.'''
    with _send_lock:
        if _send_is_running():
            return jsonify({"running": True, "error": "A referral send process is already running."}), 409
        if _is_running():
            return jsonify({"running": False, "error": "The auto-apply bot is currently running. Stop it first."}), 409
        if not can_scan_referral():
            return jsonify({"running": False, "error": "You have used all referral scans for today."}), 400
        if not can_send_referral():
            return jsonify({"running": False, "error": "You have used all referral messages for today."}), 400
        try:
            log_file = open(REFERRAL_SEND_LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _send_proc = subprocess.Popen(_full_referral_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
    try:
        with open(REFERRAL_SEND_PID_PATH, "w", encoding="utf-8") as pid_file:
            pid_file.write(str(_send_proc.pid))
    except OSError:
        pass
    return jsonify({"running": True, "pid": _send_proc.pid})


@app.route('/api/referral/send/status', methods=['GET'])
def api_referral_send_status():
    '''Reports whether the referral-send subprocess is currently running.'''
    with _send_lock:
        running = _send_is_running()
        pid = _send_proc.pid if (running and _send_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/referral/send/logs', methods=['GET'])
def api_referral_send_logs():
    '''Returns the referral-send log from byte offset ?offset=N.'''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(REFERRAL_SEND_LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(REFERRAL_SEND_LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


@app.route('/api/referral/send/log', methods=['GET'])
def api_referral_send_log():
    '''Returns the referral_message_log.csv contents for display in the UI.'''
    if not os.path.exists(REFERRAL_MSG_LOG_PATH):
        return jsonify({"rows": [], "count": 0})
    try:
        rows = []
        with open(REFERRAL_MSG_LOG_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return jsonify({"rows": rows, "count": len(rows)})
    except Exception as err:
        return jsonify({"rows": [], "count": 0, "error": str(err)})


# ===========================================================================
# License / usage status API
# ===========================================================================
@app.route('/api/license/status', methods=['GET'])
def api_license_status():
    '''Reports plan + today's usage counters for both apply and referral.'''
    paid = is_paid()
    return jsonify({
        "paid": paid,
        "apply": {
            "used_today": applications_today(),
            "free_daily_limit": free_daily_limit,
            "remaining": None if paid else max(0, free_daily_limit - applications_today()),
        },
        "referral_scan": {
            "used_today": referral_scans_today(),
            "free_daily_limit": referral_free_daily_limit,
            "paid_daily_limit": referral_paid_daily_limit,
            "remaining": referral_scan_remaining(),
            "can_scan": can_scan_referral(),
        },
        "referral_message": {
            "used_today": referral_messages_today(),
            "free_daily_limit": referral_msg_free_daily_limit,
            "remaining": referral_msg_remaining(),
            "can_send": can_send_referral(),
        },
    })


def _resolve_port(preferred: int = 5000) -> int:
    '''
    Pick a port to serve on. Honors the PORT environment variable (the launcher
    scripts set it). Otherwise tries `preferred`, and if that's taken - e.g. port
    5000 is used by AirPlay Receiver on macOS - asks the OS for any free port so
    the panel always starts instead of crashing with "address already in use".
    '''
    import socket
    requested = os.environ.get("PORT", "").strip()
    if requested.isdigit():
        return int(requested)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


if __name__ == '__main__':
    # SECURITY: localhost only, debug OFF. This app handles credentials.
    port = _resolve_port(5000)
    url = "http://127.0.0.1:%d" % port
    print(
        "\n  Control panel ready at:  %s\n"
        "  Keep this window open while you use the tool; close it to stop.\n" % url,
        flush=True,
    )
    # The launcher scripts set PANEL_OPEN_BROWSER=1 so the browser opens itself,
    # to the right port, cross-platform. Running `python app.py` by hand won't.
    if os.environ.get("PANEL_OPEN_BROWSER", "").strip() not in ("", "0", "false", "False"):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
