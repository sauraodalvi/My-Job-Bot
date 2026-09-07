'''
"Tell me what you want" step -> Saved Search.

The user writes ONE plain-English sentence (e.g. "AI Product Manager roles in
Europe, remote or hybrid, EUR 80-130k, posted this week."). This module parses
it into a **Saved Search** record - titles, locations, salary range with
currency, recency - and confirms it back as one plain sentence.

Behaviour (all pure, so both UIs and tests drive the SAME entry point):

    next_state(sentence, reply=None, state=None) -> outcome

  * With AI on and a clean parse,   -> answered  (Saved Search + confirmation)
  * With AI on but the sentence has no job titles, -> need_clarify with EXACTLY
    ONE targeted plain-word question (never an empty form).
  * With AI off / parse failure,    -> guided    (the missing pieces are asked
    one question at a time in plain words, never as a raw form).

The Saved Search is the SINGLE source of truth for salary range and recency;
the legacy search.salary / search.date_posted filter values are DERIVED from it
(documented tables below) - there is no second source of truth.

License: MIT (https://opensource.org/license/mit)
'''

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Saved Search record shape
# ---------------------------------------------------------------------------
# {
#     "sentence":  the original one-liner,
#     "titles":    ["AI Product Manager"],
#     "locations": ["Europe"],
#     "salary":    {"min": 80000, "max": 130000, "currency": "EUR"} | None,
#     "recency":   "past_week" | "past_month" | "past_24h" | "any_time",
#     "on_site":   ["Remote", "Hybrid"],
# }

RECENCY_TOKENS = ("past_24h", "past_week", "past_month", "any_time")

# Legacy search.date_posted value derived from a recency token.
RECENCY_LEGACY = {
    "past_24h": "Past 24 hours",
    "past_week": "Past week",
    "past_month": "Past month",
    "any_time": "",  # leave the legacy filter blank - no second source of truth
}

# Plain-word rephrase of a recency token for the confirmation sentence.
RECENCY_PHRASE = {
    "past_24h": "posted in the last 24 hours",
    "past_week": "posted in the last week",
    "past_month": "posted in the last month",
}

# Legacy search.salary brackets (USD only; other currencies stay on the Saved
# Search and simply don't turn into a legacy filter value).
US_SALARY_BRACKETS = [
    (40000, "$40,000+"),
    (60000, "$60,000+"),
    (80000, "$80,000+"),
    (100000, "$100,000+"),
    (120000, "$120,000+"),
    (140000, "$140,000+"),
    (160000, "$160,000+"),
    (180000, "$180,000+"),
    (200000, "$200,000+"),
]

CURRENCY_SYMBOLS = {"$": "USD", "\u20ac": "EUR", "\u00a3": "GBP", "\u20b9": "INR"}
CURRENCY_WORDS = [
    ("usd", "USD"), ("eur", "EUR"), ("euro", "EUR"), ("euros", "EUR"),
    ("gbp", "GBP"), ("pound", "GBP"), ("pounds", "GBP"),
    ("inr", "INR"), ("rupee", "INR"), ("rupees", "INR"),
]

TITLE_PHRASES = [
    "AI Product Manager", "Technical Product Manager", "Product Manager",
    "Associate Product Manager", "Senior Product Manager", "Product Designer",
    "Product Analyst", "Product Owner", "Machine Learning Engineer",
    "AI Engineer", "Data Scientist", "Data Analyst", "Data Engineer",
    "Software Engineer", "Senior Software Engineer", "Full Stack Developer",
    "Frontend Developer", "Front End Developer", "Backend Developer",
    "Back End Developer", "DevOps Engineer", "Site Reliability Engineer",
    "Solutions Architect", "Engineering Manager", "Project Manager",
    "Program Manager", "Business Analyst", "UX Designer", "UI Designer",
    "QA Engineer", "Sales Manager", "Account Manager", "Marketing Manager",
]

LOCATION_PHRASES = [
    "European Union", "United States", "United Kingdom", "New York",
    "San Francisco", "Chicago", "Austin", "Seattle", "Berlin", "London",
    "Munich", "Amsterdam", "Paris", "Madrid", "Barcelona", "Lisbon",
    "Stockholm", "Toronto", "Vancouver", "Bengaluru", "Pune", "Mumbai",
    "Singapore", "Tokyo", "Dubai", "Sydney", "Remote", "Hybrid", "On-site",
    "Onsite", "Europe", "India", "UK", "USA", "Germany", "France", "Spain",
    "Portugal", "Italy", "Netherlands", "Sweden", "Poland", "Canada",
    "Australia", "Mexico", "Brazil", "Ireland", "Switzerland",
]

ON_SITE_WORDS = {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site", "onsite": "On-site"}

_ONSITE_LABELS = {label.lower(): label for label in ("Remote", "Hybrid", "On-site")}


def _dedup(items) -> list:
    out = []
    for x in items or []:
        if x not in out:
            out.append(x)
    return out


def _split_on_site(locations: list) -> tuple:
    '''
    Separate work-style entries ('remote', 'hybrid', 'on-site') out of a location
    list, so they live only on the search's `on_site` field. Providers (AI or the
    sentence) often list "Remote" as a location AND as a work style; the Saved
    Search must not show it twice or stick a work style into the location filter.
    '''
    locs, site = [], []
    for loc in (locations or []):
        label = _ONSITE_LABELS.get(str(loc).strip().lower())
        if label:
            if label not in site:
                site.append(label)
        elif str(loc).strip() and loc not in locs:
            locs.append(loc)
    return locs, site


# ---------------------------------------------------------------------------
# Deterministic heuristics (used by AI-off / guidance; also fill missed slots)
# ---------------------------------------------------------------------------

def detect_titles(text: str) -> list:
    low = (text or "").lower()
    found = []
    for phrase in sorted(TITLE_PHRASES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", low):
            if phrase not in found:
                found.append(phrase)
    # Quoted phrases are trusted as literal titles too.
    for quoted in re.findall(r"[\"\u201c]([^\"\u201d]+)[\"\u201d]", text or ""):
        t = quoted.strip()
        if t and t not in found:
            found.append(t)
    return found


def detect_locations(text: str) -> list:
    low = (text or "").lower()
    found = []
    for phrase in sorted(LOCATION_PHRASES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", low):
            if phrase not in found:
                found.append(phrase)
    return found


def detect_on_site(text: str) -> list:
    found = []
    low = (text or "").lower()
    for word, label in ON_SITE_WORDS.items():
        if re.search(r"\b" + re.escape(word) + r"\b", low) and label not in found:
            found.append(label)
    return found


def detect_recency(text: str) -> str:
    low = " ".join((text or "").lower().split())
    if any(w in low for w in ("today", "24 hour", "24-hour", "past 24")):
        return "past_24h"
    if any(w in low for w in ("this week", "past week", "last week")):
        return "past_week"
    if any(w in low for w in ("this month", "past month", "last month")):
        return "past_month"
    if any(w in low for w in ("any time", "anytime", "whenever")):
        return "any_time"
    return "any_time"


def _detect_currency(text: str):
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in (text or ""):
            return code
    low = (text or "").lower()
    for word, code in CURRENCY_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", low):
            return code
    return None


_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(\d[\d,.]*)\s*(k|m|thousand|million)?(?![A-Za-z0-9])", re.IGNORECASE)


def _numbers_k(text: str) -> list:
    text = text or ""
    matches = list(_NUMBER_RE.finditer(text))
    got = []  # (value, scale factor, start, end) in reading order
    for m in matches:
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        factor = 1000 if unit in ("k", "thousand") else (1000000 if unit in ("m", "million") else 1)
        got.append((val, factor, m.start(), m.end()))

    out = []
    for i, (val, factor, start, end) in enumerate(got):
        # Spoken ranges put the unit on the last number only: "90 to 130
        # thousand euros" means 90k-130k, so a unit-less lower bound picks up
        # the trailing unit across a plain range connector.
        if factor == 1 and i + 1 < len(got):
            nxt = got[i + 1]
            gap = text[end:nxt[2]]
            if nxt[1] > 1 and re.fullmatch(r"[\s\-–—]*|[\s]*to[\s]*", gap, re.IGNORECASE):
                factor = nxt[1]
        out.append(val * factor)
    return out


def _detect_salary(text: str):
    currency = _detect_currency(text)
    nums = [n for n in _numbers_k(text) if 500 <= n <= 50000000]
    if len(nums) >= 2:
        lo, hi = min(nums), max(nums)
        if 0 < (hi - lo) <= 10000000 and len(nums) <= 4:
            return {"min": float(lo), "max": float(hi), "currency": currency or "USD"}
    if len(nums) == 1:
        return {"min": float(nums[0]), "max": None, "currency": currency or "USD"}
    return None


# ---------------------------------------------------------------------------
# AI parse plumbing  (stubbed out in tests via monkeypatch of _ask_ai)
# ---------------------------------------------------------------------------

SAVED_SEARCH_PROMPT = """You turn a job-seeker's plain-English sentence into a structured Saved Search.
Return ONLY a JSON object with exactly these keys:
- "titles": array of exact job titles to search for (e.g. ["AI Product Manager"]). Empty array is NOT allowed; if the sentence does not say which titles, set it to [].
- "locations": array of locations to search (e.g. ["Europe"]). Empty array if none mentioned.
- "salary": null, or {"min": number|null, "max": number|null, "currency": "USD"|"EUR"|"GBP"|"INR"}.
- "recency": exactly one of "past_24h", "past_week", "past_month", "any_time".
- "on_site": array from ["Remote", "Hybrid", "On-site"] (empty if not mentioned).

Sentence:
{}"""


def _ask_ai(sentence: str):
    '''Ask the configured AI (if any) for a Saved Search JSON. Returns the raw
    model reply, or None when AI is off / setup fails / the call errors.'''
    try:
        from modules.ai import connections as ai
        if not ai.cfg.use_AI:
            return None
        client = ai.create_ai_client()
        if not client:
            return None
        return _msg_text(client.model.invoke(SAVED_SEARCH_PROMPT.format(sentence)))
    except Exception:
        return None


def _msg_text(message) -> str:
    text = getattr(message, "text", None)
    if callable(text):
        try:
            text = text()
        except Exception:
            text = None
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text") or block.get("content") or "" if isinstance(block, dict) else str(block) for block in content)
    return str(content)


def _clean_json(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        return s[start:end + 1]
    return s


def _coerce_salary(salary):
    if not isinstance(salary, dict):
        return None
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    mn, mx = num(salary.get("min")), num(salary.get("max"))
    if mn is None and mx is None:
        return None
    if mn is not None and mx is not None and mn > mx:
        mn, mx = mx, mn
    return {"min": mn, "max": mx, "currency": str(salary.get("currency") or "USD")}


def _clamp_on_site(on_site):
    valid = ["Remote", "Hybrid", "On-site"]
    out = []
    for x in (on_site or []):
        label = ON_SITE_WORDS.get(str(x).strip().lower())
        if label and label not in out:
            out.append(label)
    return out


def _normalize_ai(raw: str, sentence: str):
    '''Build a Saved Search dict from the AI's raw reply, or None when the reply
    has no job titles (unclear).'''
    try:
        data = json.loads(_clean_json(raw))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    titles = [str(t).strip() for t in data.get("titles") or [] if str(t).strip()]
    if not titles:
        return None
    locations = [str(l).strip() for l in data.get("locations") or [] if str(l).strip()]
    recency = data.get("recency") if data.get("recency") in RECENCY_TOKENS else detect_recency(sentence)
    return _build_saved_search(sentence, {
        "titles": titles,
        "locations": locations,
        "on_site": data.get("on_site"),
        "salary": _coerce_salary(data.get("salary")),
        "recency": recency,
    })


# ---------------------------------------------------------------------------
# Speaker: confirmation sentence
# ---------------------------------------------------------------------------

_SALARY_SIGNS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "INR": "\u20b9"}


def _salary_text(salary):
    if not salary or (salary.get("min") is None and salary.get("max") is None):
        return None
    sym = _SALARY_SIGNS.get((salary.get("currency") or "USD").upper(), "")

    def fmt(n):
        n = float(n)
        if n >= 1000 and n % 1000 == 0:
            return "%s%dk" % (sym, int(n // 1000))
        return "%s%d" % (sym, int(n))

    if salary.get("min") is not None and salary.get("max") is not None:
        return "%s\u2013%s" % (fmt(salary["min"]), fmt(salary["max"]))
    n = salary.get("min") if salary.get("min") is not None else salary.get("max")
    return fmt(n) + ("+" if salary.get("min") is not None else "")


def confirmation(saved_search: dict) -> str:
    '''
    One short plain sentence confirming the parsed Saved Search back to the user.
    '''
    ss = saved_search or {}
    titles = ", ".join(ss.get("titles") or []) or "the roles you want"
    places = list(ss.get("locations") or []) + list(ss.get("on_site") or [])
    base = titles
    if places:
        base += " in " + ", ".join(places)
    parts = [base]
    sal = _salary_text(ss.get("salary"))
    if sal:
        parts.append(sal)
    rec = ss.get("recency")
    if rec and rec != "any_time" and rec in RECENCY_PHRASE:
        parts.append(RECENCY_PHRASE[rec])
    return ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Guidance state machine  (one plain-word question at a time)
# ---------------------------------------------------------------------------

GUIDED_ORDER = ["titles", "locations", "salary", "recency"]

GUIDED_QUESTIONS = {
    "titles": "Which job titles should I search for? (plain words, e.g. 'AI Product Manager')",
    "locations": "Where should I look? (regions or cities, e.g. 'Europe' or 'Remote')",
    "salary": "Any pay range you'd like? (plain words, e.g. '80 to 130 thousand euros', or leave blank)",
    "recency": "How recent should the jobs be? Say 'this week', 'this month', 'last 24 hours', or 'any time'.",
}


def _answer_for(step: str, reply: str):
    '''Turn a plain-word guided answer into the Saved Search value for `step`.'''
    reply = (reply or "").strip()
    if step == "titles":
        titles = detect_titles(reply)
        if not titles:
            parts = re.split(r",| and |\band\b", reply)
            titles = [p.strip() for p in parts if p.strip()]
            titles = [t if t[:1].isupper() else t.title() for t in titles]
        return titles or None
    if step == "locations":
        locations = detect_locations(reply)
        if not locations:
            parts = re.split(r",| and |\band\b", reply)
            locations = [p.strip() for p in parts if p.strip()]
        return locations or None
    if step == "salary":
        return _detect_salary(reply)
    if step == "recency":
        return detect_recency(reply) if (reply or "").strip() else "any_time"
    return None


def _missing_steps(saved_search: dict) -> list:
    '''
    The pieces still needed to finish the search, in ask-order. Work-style
    entries (remote / hybrid / on-site) count toward "where to look", so a reply
    of just "Remote" never re-asks for a location.
    '''
    missing = []
    if not saved_search.get("titles"):
        missing.append("titles")
    if not saved_search.get("locations") and not saved_search.get("on_site"):
        missing.append("locations")
    if not saved_search.get("salary"):
        missing.append("salary")
    return [s for s in GUIDED_ORDER if s in missing]


def _answered_outcome(sentence: str, saved_search: dict) -> dict:
    return {
        "status": "answered",
        "saved_search": saved_search,
        "confirmation": confirmation(saved_search),
        "wants_answers": {"sentence": sentence, "parsed": saved_search},
    }


def _guided_outcome(sentence: str, step: str, partial: dict) -> dict:
    return {
        "status": "need_clarify" if partial.get("mode") == "clarify" else "guided",
        "next": step,
        "question": GUIDED_QUESTIONS[step],
        "guided_state": {"step": step, "partial": partial, "sentence": sentence, "mode": partial.get("mode")},
    }


# ---------------------------------------------------------------------------
# THE shared entry point
# ---------------------------------------------------------------------------

def next_state(sentence: str, reply=None, state=None) -> dict:
    '''
    Advance the Saved Search conversation. Returns one outcome dict:

        answered    -> {"status": "answered", "saved_search", "confirmation",
                        "wants_answers"}
        need_clarify-> {"status": "need_clarify", "question",
                        "guided_state"}          (exactly one question)
        guided      -> {"status": "guided", "next", "question", "guided_state"}
                       (AI off / parse failure: one question at a time)

    `state` is the previous outcome's "guided_state". `reply` is the user's
    plain-word answer to the previous question. Tests stub `_ask_ai`.
    '''
    sentence = (sentence or "").strip()
    if not sentence:
        return _guided_outcome(sentence, "titles", {"titles": [], "mode": "guided"})

    # Continuing an active conversation -> apply the user's reply. Once the
    # single clarify question is answered it becomes the guided fill-in flow.
    if isinstance(state, dict):
        step = state.get("step") or "titles"
        mode = "guided"
        partial = dict(state.get("partial") or {})
        partial.setdefault("titles", [])
        value = _answer_for(step, reply)
        if value:
            partial[step] = value
        partial.setdefault("recency", "any_time")

        saved_search = _build_saved_search(sentence, partial)
        missing = _missing_steps(saved_search)
        if missing:
            next_step = missing[0]
            partial["mode"] = mode
            return _guided_outcome(sentence, next_step, partial)
        return _answered_outcome(sentence, saved_search)

    # Fresh parse -> try AI first.
    raw = _ask_ai(sentence)
    if raw:
        saved_search = _normalize_ai(raw, sentence)
        if saved_search:
            return _answered_outcome(sentence, saved_search)
        # AI answered but gave no job titles -> exactly ONE targeted question.
        partial = {
            "titles": detect_titles(sentence) or [],
            "locations": detect_locations(sentence),
            "on_site": detect_on_site(sentence),
            "salary": _detect_salary(sentence),
            "recency": detect_recency(sentence),
            "mode": "clarify",
        }
        return _guided_outcome(sentence, "titles", partial)

    # AI off / parse failure -> guided, missing pieces asked one at a time.
    heuristic = _heuristic_parse(sentence)
    missing = _missing_steps(heuristic)
    if not missing:
        return _answered_outcome(sentence, heuristic)
    partial = dict(heuristic)
    partial["mode"] = "guided"
    return _guided_outcome(sentence, missing[0], partial)


def _heuristic_parse(sentence: str) -> dict:
    return _build_saved_search(sentence, {
        "titles": detect_titles(sentence),
        "locations": detect_locations(sentence),
        "on_site": detect_on_site(sentence),
        "salary": _detect_salary(sentence),
        "recency": detect_recency(sentence),
    })


def _build_saved_search(sentence: str, partial: dict) -> dict:
    titles = _dedup(partial.get("titles") or [])
    locations, extra_site = _split_on_site(partial.get("locations"))
    on_site = _clamp_on_site(partial.get("on_site"))
    for label in extra_site:
        if label not in on_site:
            on_site.append(label)
    recency = partial.get("recency")
    if recency not in RECENCY_TOKENS:
        recency = "any_time"
    salary = partial.get("salary")
    if not isinstance(salary, dict):
        salary = _detect_salary(str(salary or ""))
    return {
        "sentence": sentence,
        "titles": titles,
        "locations": locations,
        "salary": salary,
        "recency": recency,
        "on_site": on_site,
    }


# ---------------------------------------------------------------------------
# Derivation: Saved Search -> legacy search.* filters (single source of truth)
# ---------------------------------------------------------------------------

def derived_date_posted(saved_search: dict) -> str:
    rec = (saved_search or {}).get("recency") or "any_time"
    return RECENCY_LEGACY.get(rec, "")


def derived_salary(saved_search: dict) -> str:
    '''
    Map the Saved Search salary onto a legacy USD bracket label. Currency is the
    single source of truth: non-USD salaries stay on the Saved Search and do not
    become a legacy filter value (they'd be wrong in a USD-only filter).
    '''
    salary = (saved_search or {}).get("salary")
    if not salary:
        return ""
    if (salary.get("currency") or "USD") != "USD":
        return ""
    floor = salary.get("min") if salary.get("min") is not None else salary.get("max")
    if not floor:
        return ""
    chosen = None
    for bracket, label in US_SALARY_BRACKETS:
        if bracket <= floor:
            chosen = label
        else:
            break
    return chosen or ""


def derive_search(saved_search: dict) -> dict:
    '''
    Derive the legacy search.* filter values from a Saved Search. The Saved
    Search remains the single source of truth; these are pure projections.
    '''
    ss = saved_search or {}
    return {
        "search_terms": list(ss.get("titles") or []),
        "search_location": ", ".join(ss.get("locations") or []),
        "on_site": list(ss.get("on_site") or []),
        "date_posted": derived_date_posted(ss),
        "salary": derived_salary(ss),
    }