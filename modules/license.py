'''
License + daily-usage limiter for the Auto Job Applier.

Free plan:  up to `free_daily_limit` applications per day (no key needed).
Unlimited: unlocked with a Gumroad license key verified against the Gumroad
           verify API at https://api.gumroad.com/v2/licenses/verify.

Usage is tracked per calendar day in `usage.json` at the app root.
'''

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from config.secrets import (
    free_daily_limit, gumroad_license_key, gumroad_product_id,
    referral_free_daily_limit, referral_paid_daily_limit,
    referral_msg_free_daily_limit, referral_msg_paid_daily_limit,
)
from config.settings import run_in_background

LICENSE_API = "https://api.gumroad.com/v2/licenses/verify"

# A special developer/test key that unlocks the Unlimited plan WITHOUT going
# through Gumroad. Handy for testing features (or for sharing a friend's test
# build) without making a real purchase. Set this as the key in user_config.json
# (secrets.gumroad_license_key) and the app treats the user as paid/unlimited.
#
# It only works when AJA_DEV=1 is set in the environment, so it is INERT in a
# shipped (public) build: environment variables never travel with the exe, so a
# normal buyer pasting this key just gets "invalid key" and nothing is saved.
# To enable it for your own testing, run with the env var set:
#     setx AJA_DEV 1   (or launch the exe from a shell with `set AJA_DEV=1`)
TEST_LICENSE_KEY = "TEST-FRIEND-UNLIMITED-1234"


def _test_key_enabled() -> bool:
    '''True only when the special test key should be honored (AJA_DEV=1).'''
    return os.environ.get("AJA_DEV", "") == "1"


def _maybe_popup(message: str, title: str) -> None:
    """
    Pop a modal upsell alert ONLY when it is safe to do so:
      * not running in background/headless mode (a blocking alert on a headless
        run would hang the bot), and
      * a graphical display + pyautogui are actually available.
    Otherwise we already printed/sent the message to the log, so just skip.
    """
    if run_in_background:
        return
    try:
        import pyautogui
        pyautogui.alert(message, title)
    except Exception:
        pass


def _today() -> str:
    return datetime.date.today().isoformat()


def _root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


USAGE_PATH = os.path.join(_root_dir(), "usage.json")
REFERRAL_USAGE_PATH = os.path.join(_root_dir(), "referral_usage.json")
REFERRAL_MSG_USAGE_PATH = os.path.join(_root_dir(), "referral_msg_usage.json")
REFERRAL_JOB_LOG_PATH = os.path.join(_root_dir(), "referral_job_log.json")
USER_CONFIG_PATH = os.path.join(_root_dir(), "user_config.json")


# ---------------------------------------------------------------------------
# Daily usage counter
# ---------------------------------------------------------------------------

def load_usage() -> int:
    '''Applications submitted so far today (0 if the file is missing/stale).'''
    try:
        with open(USAGE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict) and str(data.get("date", "")) == _today():
            return int(data.get("count", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return 0


def _save_usage(count: int) -> None:
    try:
        with open(USAGE_PATH, "w", encoding="utf-8") as file:
            json.dump({"date": _today(), "count": max(0, count)}, file)
    except OSError as e:
        print("License: could not save usage file.", e)


def applications_today() -> int:
    return load_usage()


def record_application() -> int:
    '''Increment today's counter after a successful application. Returns the new count.'''
    new_count = _save_usage_new(load_usage() + 1)
    return new_count


def _save_usage_new(count: int) -> int:
    _save_usage(count)
    return count


def remaining_today() -> int:
    '''Applications left on the Free plan today (None when unlimited).'''
    if is_paid():
        return None
    return max(0, free_daily_limit - load_usage())


def is_paid() -> bool:
    '''True when a Gumroad license key (or the special test key) has been
    stored in user_config.json.'''
    return bool(str(gumroad_license_key or "").strip())


def can_submit() -> bool:
    '''May the bot submit another application right now?'''
    if is_paid():
        return True
    return load_usage() < free_daily_limit


# ---------------------------------------------------------------------------
# Gumroad license verification
# ---------------------------------------------------------------------------

def _read_user_config() -> dict:
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _write_user_config(cfg: dict) -> None:
    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(cfg, file, indent=2, ensure_ascii=False)
    except OSError as e:
        print("License: could not save user config.", e)


def _set_license_key(key: str) -> None:
    cfg = _read_user_config()
    cfg.setdefault("secrets", {})["gumroad_license_key"] = key.strip()
    _write_user_config(cfg)


def verify_gumroad(license_key: str) -> dict:
    '''
    Verifies a license key against the Gumroad API. Returns the parsed JSON
    response. Raises on network / HTTP errors so the caller can fall back.
    '''
    data = urllib.parse.urlencode({
        "product_id": gumroad_product_id,
        "license_key": license_key.strip(),
        "increment_uses_count": "false",
    }).encode("utf-8")
    request = urllib.request.Request(LICENSE_API, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def activate_license(license_key: str) -> tuple:
    '''
    Tries to activate a Gumroad license key. Returns (ok, message).
    On success the valid key is saved into user_config.json -> secrets.
    '''
    key = str(license_key or "").strip()
    if not key:
        return False, "Enter your license key from the Gumroad receipt email."
    if key == TEST_LICENSE_KEY and _test_key_enabled():
        _set_license_key(key)
        return True, "TEST key activated - unlimited unlocked (no Gumroad verification)."
    try:
        result = verify_gumroad(key)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, "Could not reach Gumroad to verify the key. Check your internet and try again. ({}).".format(e)

    if not result.get("success"):
        return False, result.get("message") or "That license key is not valid for this product."

    purchase = result.get("purchase") or {}
    flags = [name for name in ("refunded", "disputed", "chargebacked", "cancelled") if purchase.get(name)]
    if flags:
        return False, "This license is no longer active ({}) - it was refunded or cancelled.".format(", ".join(flags))

    if purchase.get("test") is True:
        return True, "TEST key verified against Gumroad - unlimited unlocked. (This was a test purchase.)"

    _set_license_key(key)
    return True, "License verified - unlimited applications unlocked! 🎉"


# ---------------------------------------------------------------------------
# Upsell
# ---------------------------------------------------------------------------

def show_upsell() -> None:
    '''Hard-stop message shown when the Free plan daily limit is reached.'''
    used = load_usage()
    message = (
        "You have reached the Free plan limit of {} applications per day ({} used today).\n\n"
        "To unlock unlimited applications:\n"
        "  1. Open the app folder and run 'Setup App.bat'.\n"
        "  2. Go to the 'Unlock' step and paste the license key from your\n"
        "     Gumroad receipt email.\n"
        "  3. Click Activate - the 10/day limit is removed instantly.\n"
    ).format(free_daily_limit, used)
    print("LICENSE: " + message.replace("\n", " ").strip())
    _maybe_popup(message, "Free plan limit reached")


# ---------------------------------------------------------------------------
# Referral scan usage counter (referral_usage.json)
# ---------------------------------------------------------------------------

def _load_referral_usage() -> int:
    '''Referral scans performed so far today (0 if missing/stale).'''
    try:
        with open(REFERRAL_USAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and str(data.get("date", "")) == _today():
            return int(data.get("count", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return 0


def _save_referral_usage(count: int) -> None:
    try:
        with open(REFERRAL_USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump({"date": _today(), "count": max(0, count)}, f)
    except OSError as e:
        print("License: could not save referral usage file.", e)


def referral_scans_today() -> int:
    return _load_referral_usage()


def _referral_scan_limit() -> int:
    return referral_paid_daily_limit if is_paid() else referral_free_daily_limit


def can_scan_referral() -> bool:
    '''May the bot perform another referral scan right now?'''
    return _load_referral_usage() < _referral_scan_limit()


def record_referral_scan() -> int:
    '''Increment today's referral scan counter. Returns the new count.'''
    new_count = _load_referral_usage() + 1
    _save_referral_usage(new_count)
    return new_count


def referral_scan_remaining() -> int | None:
    '''Referral scans left today (None when unlimited).'''
    if is_paid() and referral_paid_daily_limit == 0:
        return None
    return max(0, _referral_scan_limit() - _load_referral_usage())


# ---------------------------------------------------------------------------
# Referral message usage counter (referral_msg_usage.json)
# ---------------------------------------------------------------------------

def _load_referral_msg_usage() -> int:
    '''Referral messages sent so far today (0 if missing/stale).'''
    try:
        with open(REFERRAL_MSG_USAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and str(data.get("date", "")) == _today():
            return int(data.get("count", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return 0


def _save_referral_msg_usage(count: int) -> None:
    try:
        with open(REFERRAL_MSG_USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump({"date": _today(), "count": max(0, count)}, f)
    except OSError as e:
        print("License: could not save referral message usage file.", e)


def referral_messages_today() -> int:
    return _load_referral_msg_usage()


def _referral_msg_limit() -> int | None:
    '''Return the daily message limit, or None for unlimited.'''
    if is_paid():
        if referral_msg_paid_daily_limit == 0:
            return None
        return referral_msg_paid_daily_limit
    return referral_msg_free_daily_limit


def can_send_referral() -> bool:
    '''May the bot send another referral message right now?'''
    limit = _referral_msg_limit()
    if limit is None:
        return True
    return _load_referral_msg_usage() < limit


def record_referral_message() -> int:
    '''Increment today's referral message counter. Returns the new count.'''
    new_count = _load_referral_msg_usage() + 1
    _save_referral_msg_usage(new_count)
    return new_count


def referral_msg_remaining() -> int | None:
    '''Referral messages left today (None when unlimited).'''
    limit = _referral_msg_limit()
    if limit is None:
        return None
    return max(0, limit - _load_referral_msg_usage())


# ---------------------------------------------------------------------------
# Referral upsell
# ---------------------------------------------------------------------------

def show_referral_upsell(feature: str = "scan") -> None:
    '''Message shown when the referral daily limit is reached.'''
    if feature == "scan":
        used = referral_scans_today()
        limit = _referral_scan_limit()
        message = (
            "You have reached the Free plan limit of {} referral scan(s) per day ({} used today).\n\n"
            "To unlock up to {} scans per day:\n"
            "  1. Open the app folder and run 'Setup App.bat'.\n"
            "  2. Go to the 'Unlock' step and paste the license key from your\n"
            "     Gumroad receipt email.\n"
            "  3. Click Activate.\n"
        ).format(limit, used, referral_paid_daily_limit)
        title = "Referral scan limit reached"
    else:
        used = referral_messages_today()
        limit = _referral_msg_limit()
        if limit is None:
            return
        message = (
            "You have reached the Free plan limit of {} referral message(s) per day ({} used today).\n\n"
            "To unlock unlimited messages:\n"
            "  1. Open the app folder and run 'Setup App.bat'.\n"
            "  2. Go to the 'Unlock' step and paste the license key from your\n"
            "     Gumroad receipt email.\n"
            "  3. Click Activate.\n"
        ).format(limit, used)
        title = "Referral message limit reached"
    print("LICENSE: " + message.replace("\n", " ").strip())
    _maybe_popup(message, title)


# ---------------------------------------------------------------------------
# Per-job referral log (referral_job_log.json)
# ---------------------------------------------------------------------------
#
# Guarantees the "one job = one referral" rule. Once a referral message has been
# sent for a given job_id it is recorded here so that no later run ever sends a
# second referral to the same job posting (even if the job resurfaces in a fresh
# scan, or a job matches multiple HR contacts). The file maps job_id -> record.

def _load_referral_job_log() -> dict:
    '''Read the persisted per-job referral log ({} when missing/stale).'''
    try:
        with open(REFERRAL_JOB_LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return {}


def _save_referral_job_log(log: dict) -> None:
    try:
        with open(REFERRAL_JOB_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print("License: could not save referral job log.", e)


def referral_sent_for_job(job_id) -> bool:
    '''True when a referral has already been sent for this job_id.'''
    if not str(job_id or "").strip():
        return False
    return str(job_id) in _load_referral_job_log()


def record_referral_job_sent(job_id, job: dict = None) -> None:
    '''Record that a referral message has been sent for this job. If the job_id is
    empty (e.g. personalized mode with inline targets), the entry is keyed by the
    profile URL so per-person outreach is still tracked once.'''
    key = str(job_id or "").strip() or str((job or {}).get("hr_link") or "").strip()
    if not key:
        return
    from datetime import datetime
    log = _load_referral_job_log()
    log[key] = {
        "job_id": str(job_id or ""),
        "company": (job or {}).get("company", ""),
        "title": (job or {}).get("title", ""),
        "hr_name": (job or {}).get("hr_name", ""),
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_referral_job_log(log)


def referral_jobs_sent_total() -> int:
    '''The number of distinct jobs/people that have ever had a referral sent.'''
    return len(_load_referral_job_log())