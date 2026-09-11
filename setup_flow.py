'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Shared declaration of the "Let's get you ready" onboarding flow.

The whole point of this module is that BOTH renderers - the Tkinter desktop
wizard (setup_wizard.py) and the browser control panel (app.py +
templates/setup_flow.html) - consume this one definition. No step logic lives in
either UI. A step is:

    {
      "id":          short slug,
      "title":       short step title shown in plain words,
      "why":         one short line explaining why this is asked,
      "required":    whether the step must be answered to finish,
      "fields":      [ {"key", "label", "type", "required", "help", options...}, ... ],
    }

Supported field types:
    text      - single line of text
    password  - single masked line (e.g. the LinkedIn sign-in)
    textarea  - multi-line text
    yesno     - a plain Yes / No choice (stored as a bool)

Persistence:
    The flow writes through the SAME user_config.json the tool already reads
    (see config/_overrides.py). It owns these keys:
      * Step 1 account -> secrets.username + secrets.password (the login the
                            bot uses to sign in; only written when filled)
      * Step 2 resume  -> questions.default_resume_path
                          + resume_profiles["<path>"] (file and extracted
                            profile stored as SEPARATE records)
      * Step 3 wants   -> setup_flow.want_sentence + saved_search (the parsed
                            Saved Search; legacy search.salary / search.
                            date_posted / search_terms are DERIVED from it)
      * Step 4 policy  -> questions.pause_before_submit + agent_policy (level
                            + action policy; safety settings derived from an
                            explicit table)
    Everything else in the config file is left untouched (read-modify-write).
'''

import json
import os

from config import _overrides
from modules import policy as agent_policy

USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH

FLOW_TITLE = "Let's get you ready"

WELCOME_SENTENCE = (
    "I watch job sites for you, find the jobs you want, and send the "
    "applications you approve."
)
WELCOME_NOTES = [
    "Tell me about yourself once, and I'll do the applying.",
    "Nothing is sent without you saying it's okay.",
    "Everything you enter stays on this computer.",
]

FIRST_STEP_ID = "account"

STEPS = [
    {
        "id": "account",
        "title": "Sign in to LinkedIn",
        "why": "I log in as you so every application is sent from your account.",
        "required": True,
        "fields": [
            {
                "key": "username",
                "label": "LinkedIn email",
                "type": "text",
                "required": True,
                "help": "The email you use to sign in to LinkedIn.",
            },
            {
                "key": "password",
                "label": "LinkedIn password",
                "type": "password",
                "required": True,
                "help": "Stored only on this PC in user_config.json - the bot never shares it.",
            },
        ],
    },
    {
        "id": "resume",
        "title": "Your resume",
        "why": "This is the resume every application will send.",
        "required": True,
        "fields": [
            {
                "key": "resume_path",
                "label": "Resume file",
                "type": "text",
                "required": True,
                "pick": True,
                "help": "A PDF or Word file with your resume. The tool reads it to fill in application questions.",
            },
            {
                "key": "looks_right",
                "label": "The profile below looks right",
                "type": "yesno",
                "required": False,
                "default": True,
                "yes_label": "Yes, that's me",
                "no_label": "No, let me change the file",
                "help": "Click 'Detect profile' to see what I read from your resume. This profile is what I'll use to fill in applications.",
            },
        ],
    },
    {
        "id": "wants",
        "title": "Tell me what you want",
        "why": "So I know which jobs to look for.",
        "required": True,
        "fields": [
            {
                "key": "sentence",
                "label": "What kind of job do you want?",
                "type": "textarea",
                "required": True,
                "help": "One plain-English sentence, e.g. \"AI Product Manager roles in Europe, remote or hybrid, posted this week.\"",
            },
        ],
    },
    {
        "id": "policy",
        "title": "Should I ask before sending?",
        "why": "So nothing is sent without your okay.",
        "required": False,
        "fields": [
            {
                "key": "ask_before_sending",
                "label": "Ask me before you send anything",
                "type": "yesno",
                "required": False,
                "default": True,
                "yes_label": "Yes, always ask",
                "no_label": "No, just send it",
                "help": "I recommend Yes. You review each application before it goes out.",
            },
        ],
    },
]


def step(step_id):
    '''Return one step definition by id.'''
    for s in STEPS:
        if s["id"] == step_id:
            return s
    return None


def step_index(step_id):
    '''Return the 0-based position of a step in STEPS, or -1.'''
    for i, s in enumerate(STEPS):
        if s["id"] == step_id:
            return i
    return -1


def field(step_id, field_key):
    '''Return one field definition by step id and key.'''
    s = step(step_id)
    if not s:
        return None
    for f in s["fields"]:
        if f["key"] == field_key:
            return f
    return None


def required_fields(step_id):
    '''Return the keys of required fields in a step.'''
    s = step(step_id)
    if not s:
        return []
    return [f["key"] for f in s["fields"] if f.get("required")]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _bool_value(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "on", "y")


def validate_step(step_id, values):
    '''
    Validate the collected values for one step. Returns a list of plain-word
    error messages (empty list when the step is fine).
    '''
    errors = []
    s = step(step_id)
    if not s:
        return ["Unknown step."]
    values = values or {}
    for f in s["fields"]:
        if not f.get("required"):
            continue
        raw = values.get(f["key"])
        if isinstance(raw, str) and raw.strip() == "":
            errors.append("Please fill in: %s." % f["label"])
        elif raw is None:
            errors.append("Please fill in: %s." % f["label"])
    return errors


def validate_flow(answers):
    '''
    Validate every step. Returns {step_id: [error, ...]} for steps with
    problems; an empty dict means the flow can finish.
    '''
    errors = {}
    for s in STEPS:
        if not s.get("required"):
            continue
        step_errors = validate_step(s["id"], answers.get(s["id"]))
        if step_errors:
            errors[s["id"]] = step_errors
    return errors


# ---------------------------------------------------------------------------
# Pre-fill / persistence
# ---------------------------------------------------------------------------
def _read_config():
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _read_secrets():
    return dict((_read_config().get("secrets") or {}))


def has_license():
    return bool(str(_read_secrets().get("gumroad_license_key") or "").strip())


def get_profile_record(resume_path):
    '''
    Return the stored Resume Profile record for a path (None if never saved).
    The file (default_resume_path) and the extracted profile live as SEPARATE
    records under cfg["resume_profiles"].
    '''
    path = str(resume_path or "").strip()
    if not path:
        return None
    cfg = _read_config()
    profiles = cfg.get("resume_profiles")
    if not isinstance(profiles, dict):
        return None
    return profiles.get(path)


def describe_resume_path(resume_path):
    '''
    Detection hint for a resume path. Returns (text, ok) where text is a plain
    sentence a UI can show under the file field. Fresh detection; never raises.
    '''
    from modules.resumes import profile as resume_profile
    path = str(resume_path or "").strip()
    if not path:
        return ("Pick a resume file and click Detect to see what I read from it.", False)
    record = resume_profile.detect_profile(path)
    if record.get("ok"):
        return (record["summary_line"], True)
    return (record["message"], False)


def prefill():
    '''
    Return {"<step_id>": {field_key: value}, ...} read from the current
    user_config.json, so re-opening the flow shows what's already saved.
    '''
    cfg = _read_config()
    secrets_section = _read_secrets()
    questions = cfg.get("questions") or {}
    flow_section = cfg.get("setup_flow") or {}

    resume_value = str(questions.get("default_resume_path", "") or "").strip()
    wants_value = flow_section.get("want_sentence", "") or ""
    ask_value = questions.get("pause_before_submit", True)

    saved_search = cfg.get("saved_search")
    if not isinstance(saved_search, dict):
        saved_search = None
    agent_policy = cfg.get("agent_policy")
    if not isinstance(agent_policy, dict):
        agent_policy = None

    profile_record = get_profile_record(resume_value) if resume_value else None
    profile_text = (profile_record or {}).get("summary_line") or ""

    return {
        "account": {
            "username": str(secrets_section.get("username", "") or "").strip(),
            "password": str(secrets_section.get("password", "") or ""),
        },
        "resume": {
            "resume_path": resume_value,
            "looks_right": True,
            "profile": profile_record,
            "profile_text": profile_text,
        },
        "wants": {"sentence": wants_value, "parsed": saved_search},
        "policy": {"ask_before_sending": _bool_value(ask_value), "agent_policy": agent_policy},
    }


def apply_answers(cfg, answers):
    '''
    Merge the flow's answers into a config dict. Pure: returns a NEW dict and
    only touches the keys this flow owns (resume file + its separate Resume
    Profile record, wants sentence + Saved Search with DERIVED legacy filters,
    ask-before-sending + Agent/Action Policy). Used by both renderers and tests.
    '''
    cfg = json.loads(json.dumps(cfg or {}))

    answers = answers or {}
    account_answers = answers.get("account") or {}
    resume_answers = answers.get("resume") or {}
    wants_answers = answers.get("wants") or {}
    policy_answers = answers.get("policy") or {}

    # --- account: LinkedIn sign-in (only written when filled out) ------------
    if account_answers:
        secrets = dict(cfg.get("secrets") or {})
        username = str(account_answers.get("username", "") or "").strip()
        password = account_answers.get("password") or ""
        if username:
            secrets["username"] = username
        if password:
            secrets["password"] = password
        cfg["secrets"] = secrets

    questions = dict(cfg.get("questions") or {})
    resume_path = str(resume_answers.get("resume_path", "") or "").strip()
    questions["default_resume_path"] = resume_path
    cfg["questions"] = questions

    # --- resume profile: file and extracted profile as separate records ------
    profiles = dict(cfg.get("resume_profiles") or {})
    if resume_path:
        from modules.resumes import profile as resume_profile
        profiles[resume_path] = resume_profile.detect_profile(resume_path)
    cfg["resume_profiles"] = profiles

    # --- wants -> Saved Search ----------------------------------------------
    flow_section = dict(cfg.get("setup_flow") or {})
    flow_section["want_sentence"] = str(wants_answers.get("sentence", "") or "").strip()
    cfg["setup_flow"] = flow_section

    parsed = wants_answers.get("parsed")
    saved_search = parsed if isinstance(parsed, dict) and (parsed.get("titles") or []) else None
    if saved_search:
        from modules.search_parse import derive_search
        cfg["saved_search"] = saved_search
        search = dict(cfg.get("search") or {})
        search.update(derive_search(saved_search))
        cfg["search"] = search
    else:
        cfg.pop("saved_search", None)

    # --- policy: ask-before-sending + Agent/Action Policy defaults ----------
    ask = _bool_value(policy_answers.get("ask_before_sending", True))
    questions = dict(cfg.get("questions") or {})
    questions["pause_before_submit"] = ask
    cfg["questions"] = questions
    cfg = agent_policy.apply_policy(cfg, ask)

    return cfg


def save_flow(answers):
    '''
    Read user_config.json, merge in the flow answers (touch only the flow's
    keys), write it back. Returns the full saved config.
    '''
    cfg = apply_answers(_read_config(), answers)
    cfg = _write_config(cfg)
    return cfg


def _write_config(cfg):
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
        json.dump(cfg, file, indent=2, ensure_ascii=False)
    return cfg


# ---------------------------------------------------------------------------
# Summary (plain words shown before saving)
# ---------------------------------------------------------------------------
def summary_lines(answers):
    '''
    Return a list of one-sentence plain-word lines summarising every answer,
    used by the "here's everything you told me" final screen.
    '''
    answers = answers or {}
    account_answers = answers.get("account") or {}
    resume_answers = answers.get("resume") or {}
    wants_answers = answers.get("wants") or {}
    policy_answers = answers.get("policy") or {}

    resume_path = str(resume_answers.get("resume_path", "") or "").strip()
    sentence = str(wants_answers.get("sentence", "") or "").strip()
    ask = _bool_value(policy_answers.get("ask_before_sending", True))

    resume_text = os.path.basename(resume_path) if resume_path else "not added yet"
    profile_text = str(resume_answers.get("profile_text", "") or "").strip()
    if resume_path and not profile_text:
        record = get_profile_record(resume_path)
        if record and record.get("ok"):
            profile_text = record.get("summary_line") or ""
    if profile_text:
        resume_line = "Resume: %s (I read: %s)" % (resume_text, profile_text)
    else:
        resume_line = "Resume: %s" % resume_text

    parsed = wants_answers.get("parsed") or {}
    if isinstance(parsed, dict) and (parsed.get("titles") or []):
        from modules.search_parse import confirmation as search_confirmation
        wants_text = search_confirmation(parsed)
    else:
        wants_text = sentence

    signin_email = str(account_answers.get("username", "") or "").strip()
    lines = []
    if signin_email:
        lines.append("I'll sign in to LinkedIn as %s." % signin_email)
    lines.append(resume_line)
    lines.append("I'll look for: %s" % (wants_text if wants_text else "nothing yet"))
    if ask:
        lines.append("Before anything is sent, I'll ask you first.")
    else:
        lines.append("I'll send applications without asking first.")
    return lines


def allset_lines(answers=None):
    '''
    Plain-word lines for the "You're all set" end screen: what the policy will
    do, free-plan limits (or unlimited), and what was parsed from the wish.
    '''
    answers = answers or {}
    wants_answers = answers.get("wants") or {}
    policy_answers = answers.get("policy") or {}
    resume_answers = answers.get("resume") or {}

    ask = _bool_value(policy_answers.get("ask_before_sending", True))
    lines = []
    lines.append(
        "I'll ask you before sending anything."
        if ask
        else "You asked me to send applications without pausing."
    )

    if has_license():
        lines.append("Unlimited: your license key has unlocked the daily limit.")
    else:
        from modules.license import free_daily_limit
        lines.append("Free plan: up to %d applications a day. Add a license key to unlock the limit." % free_daily_limit)

    resume_path = str(resume_answers.get("resume_path", "") or "").strip()
    profile_text = str(resume_answers.get("profile_text", "") or "").strip()
    if resume_path and not profile_text:
        record = get_profile_record(resume_path)
        if record and record.get("ok"):
            profile_text = record.get("summary_line") or ""
    if profile_text:
        lines.append("Your resume profile: %s." % profile_text)

    parsed = wants_answers.get("parsed") or {}
    if isinstance(parsed, dict) and (parsed.get("titles") or []):
        from modules.search_parse import confirmation as search_confirmation
        lines.append("Looking for: %s" % search_confirmation(parsed))

    return lines


def is_complete(cfg=None):
    '''
    True once the flow owns a resume and a "wants" sentence. Used by the home
    screens to decide whether to show the flow again.
    '''
    cfg = cfg if cfg is not None else _read_config()
    questions = cfg.get("questions") or {}
    flow_section = cfg.get("setup_flow") or {}
    resume_ok = bool(str(questions.get("default_resume_path", "") or "").strip())
    wants_ok = bool(str(flow_section.get("want_sentence", "") or "").strip())
    return resume_ok and wants_ok