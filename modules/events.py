"""
Structured event log (JSONL) for the bot runtime.

Every meaningful decision/action in the auto-apply and referral flows is
recorded as a single line of JSON in `logs/events.jsonl`. This is the ordered
event stream that later becomes the persistence layer of the agent: it defines
the vocabulary (JOB_OPENED, EXPERIENCE_CHECK, EXPERIENCE_UNKNOWN,
EASY_APPLY_OPENED, OVERLAY_DETECTED, OVERLAY_DISMISSED, QUESTION_DETECTED,
ANSWER_FILLED, REVIEW_REACHED, SUBMIT_ATTEMPTED, SUBMIT_SUCCESS, FAILURE,
SKIPPED, ...) so every failure is attributable instead of a bare "Failed to
apply".

Instrumentation is a no-op on failure and never blocks the bot.
"""

import json
import os
import time
import uuid

_EVENTS_FILE = "events.jsonl"


def _log_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs")


def _events_path() -> str:
    return os.path.join(_log_dir(), _EVENTS_FILE)


_RUN_ID = uuid.uuid4().hex[:12]


def run_id() -> str:
    return _RUN_ID


def reset_run_id() -> None:
    global _RUN_ID
    _RUN_ID = uuid.uuid4().hex[:12]


def emit(event: str, **props) -> None:
    """Append one event. Never raises."""
    try:
        record = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "run_id": _RUN_ID,
            "event": event,
        }
        record.update(props)
        path = _events_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def tail(path: str = None, n: int = 50) -> list[dict]:
    """Read the last n events (for diagnostics/test assertions)."""
    try:
        p = path or _events_path()
        with open(p, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        return lines[-n:]
    except Exception:
        return []


def reset_events_file() -> None:
    """Delete the event file so each run starts clean (test/smoke helper)."""
    try:
        p = _events_path()
        if os.path.isfile(p):
            os.remove(p)
    except Exception:
        pass