'''
Fill external (non-LinkedIn Easy Apply) job application forms.

When a job listing only offers an "Apply" button that leaves LinkedIn, the bot
opens the careers page in a new tab, finds the real form controls (text/email/
phone inputs, textareas, selects, radio groups, checkboxes) - including inside
iframes like Workday/Greenhouse portals - and answers them.

Answer source, in order:
    1. Static config (config.personals / config.questions) for well-known fields
       like name, email, phone, address, salary, notice period, EEO questions.
    2. The AI (`answer_question`, which sees the resume context + job
       description) for everything else, including choosing from a page's own
       option list for selects/radios. Cached answers are reused across runs.

The bot NEVER clicks Submit on its own for external forms. With
`pause_before_submit` enabled the caller prompts the user to review and finish.
'''

from __future__ import annotations

import re
import time
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)

import config.personals as personals
import config.questions as questions
from modules.helpers import print_lg
from modules.ai.connections import answer_question


# Fields we must never touch.
_SKIP_FIELD_MARKERS = (
    "password", "secret", "otp", "captcha", "recaptcha", "honeypot",
    "verify human", "csrf", "token", "authenticity", "search", "query",
    "-hp-", "faux", "fake_", "trap",
)

# Markers that make a checkbox safe(ish) to check for the user.
_CHECKBOX_AGREE_MARKERS = (
    "agree", "consent", "terms", "accept", "acknowledge", "affirm",
    "authorization", "i am submitting", "submission",
)

_DEFAULT_PLACEHOLDER_SELECT_OPTIONS = ("select", "choose", "--", "please select", "none", "select one", "make a selection")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _static_answer(hint: str) -> str | None:
    '''Return a static answer for a field, or None if the AI should handle it.'''
    h = _norm(hint)
    if not h:
        return None
    full_name = " ".join(x for x in [personals.first_name, personals.middle_name, personals.last_name] if x and x.strip())

    def has(*terms: str) -> bool:
        return any(term in h for term in terms)

    # Essay questions must be answered before the generic "role"/"title" branch:
    # "WHY THIS ROLE ...?" would otherwise be filled with the work title.
    essays = getattr(questions, "essay_questions", None) or {}
    if has("why this role") or has("why athena") or has("why do you want to work here") or (has("why") and has("apply here")):
        return str(essays.get("why_role", "") or "") or None
    if has("something you built") or (has("built") and has("owned")) or has("proud of"):
        return str(essays.get("built_owned", "") or "") or None
    if has("decided not to build") or (has("time you decided") and has("build")):
        return str(essays.get("decided_not_to_build", "") or "") or None

    projects = getattr(questions, "projects_summary", None) or []
    # Project cards (NAME / LINK / WHAT IS IT) are filled in order. Only engage
    # in "project mode" (activated when a "what is it / what was hard" textarea
    # is present in the current step) so a bare "name"/"link" field elsewhere is
    # never shadowed. The "*" required-marker is stripped before exact matching.
    if projects and _PROJECT_CARD["active"]:
        h_clean = h.replace("*", "").strip()
        if h_clean == "name":
            idx = _PROJECT_CARD["idx"]
            if idx < len(projects):
                _PROJECT_CARD["idx"] += 1
                return str(projects[idx].get("name", "") or "")
        elif h_clean == "link":
            idx = _PROJECT_CARD["idx"] - 1
            if 0 <= idx < len(projects):
                return str(projects[idx].get("link", "") or "")
        elif has("what is it") or has("what was hard"):
            idx = _PROJECT_CARD["idx"] - 1
            if 0 <= idx < len(projects):
                return str(projects[idx].get("description", "") or "")
        return None

    if has("full name"):
        return full_name
    if has("first name") or has("given name"):
        return personals.first_name
    if has("last name") or has("family name") or has("surname"):
        return personals.last_name
    if has("middle name"):
        return personals.middle_name or ""
    if has("email"):
        got = (getattr(personals, "email", "") or "").strip()
        if not got:
            try:
                from config.secrets import username as _login
                if _login and "@" in _login:
                    got = _login
            except Exception:
                got = ""
        return got
    if has("phone") or has("mobile") or has("telephone"):
        return personals.phone_number
    if has("linkedin"):
        return getattr(questions, "linkedin", getattr(questions, "linkedIn", "")) or ""
    if has("github"):
        return getattr(questions, "github", "") or ""
    if has("website") or has("portfolio"):
        return getattr(questions, "website", "") or ""
    # Education (degree/institution/field/cgpa/years) — matched before location
    # terms so e.g. "Institution location" or "Degree (location)" resolve correctly.
    if has("degree") or has("qualification") or has("course name"):
        return getattr(questions, "education_degree", "") or ""
    if has("institution") or has("university") or has("college") or has("school"):
        return getattr(questions, "education_institution", "") or ""
    if has("field of study") or has("major") or has("specializ"):
        return getattr(questions, "education_field_of_study", "") or ""
    if has("cgpa") or has("gpa"):
        return getattr(questions, "education_cgpa", "") or ""
    if has("start year") or has("starting year") or has("year of joining"):
        return getattr(questions, "education_start_year", "") or ""
    if has("end year") or has("graduation") or has("year of passing") or has("completion year"):
        return getattr(questions, "education_end_year", "") or ""
    # Work experience (current / most recent role). Company/role must be matched
    # before generic "location"/"years" branches so e.g. "company location" or
    # "how many years at this role" resolve correctly.
    if has("company") or has("employer") or has("organization") or has("works at"):
        return getattr(questions, "work_company", "") or ""
    if has("job title") or has("position") or has("role") or has("designation") or has("title"):
        return getattr(questions, "work_role", "") or ""
    if has("responsibilities") or has("describe your work") or (has("job") and has("description")) or has("work summary") or has("what did you do") or has("what did you own"):
        return getattr(questions, "work_summary", "") or ""
    if (has("work") and has("location")) or has("workplace") or has("work city") or has("work state") or has("work country"):
        return getattr(questions, "work_location", "") or ""
    if has("currently working") or has("still working") or has("currently employed") or has("work here") or has("present"):
        return getattr(questions, "work_end_date", "") or ""
    if (has("start date") or has("start month") or has("started") or has("from month") or has("from date") or (has("start") and not has("year"))) and not has("salary"):
        return getattr(questions, "work_start_date", "") or ""
    if (has("end date") or has("end month") or has("ended") or has("until") or has("to date") or has("till") or (has("end") and not has("year"))) and not has("salary"):
        return getattr(questions, "work_end_date", "") or ""
    if has("skills") or has("skill set") or has("competenc"):
        return getattr(questions, "skills_summary", "") or ""
    # Work authorization / eligibility must be matched before location terms:
    # e.g. "right to work in this country" should NOT hit the country branch.
    if has("work permit") or has("right to work") or has("eligible to work") or (has("work authorization") and not has("visa")):
        return "Yes"
    if has("visa") or has("sponsor"):
        return getattr(questions, "require_visa", "No")
    if has("employment eligib") or (has("authoriz") and not has("visa")):
        return "Yes"
    if has("citizenship") or has("citizen"):
        return getattr(questions, "us_citizenship", "Yes") or "Yes"
    if has("street"):
        return personals.street
    if has("address"):
        return personals.street
    if has("city") or has("location"):
        return personals.current_city or ""
    if has("state") or has("province") or has("region"):
        return personals.state
    if has("zip") or has("postal"):
        return personals.zipcode
    if has("country"):
        return personals.country
    if has("gender") or has(" sex"):
        return personals.gender
    if has("disability"):
        return personals.disability_status
    if has("veteran"):
        return personals.veteran_status
    if has("ethnicity"):
        return personals.ethnicity
    if has("years") or has("experience"):
        return str(getattr(questions, "years_of_experience", "") or "")
    if has("proficien"):
        return "Professional"
    if has("salary") or has("compensation") or has("expected ctc"):
        return str(getattr(questions, "desired_salary", "") or "")
    if has("notice"):
        return str(getattr(questions, "notice_period", "") or "")
    return None


def _resolve_label(element) -> str:
    '''Best-effort human readable label for a form control.'''
    try:
        elem_id = element.get_attribute("id")
        if elem_id:
            esc = elem_id.replace("'", "''")
            try:
                label = element.find_element(By.XPATH, f"//label[@for='{esc}']")
                if label.text:
                    return label.text.strip()
            except NoSuchElementException:
                pass
        for attr in ("aria-label", "title", "placeholder", "name"):
            value = element.get_attribute(attr)
            if value and value.strip():
                return value.strip()
    except StaleElementReferenceException:
        return ""
    return ""


def _option_matches(option_text: str, target: str) -> bool:
    o, t = _norm(option_text), _norm(target)
    if not o or not t:
        return False
    if o == t or t in o or o in t:
        return True
    if o.startswith(t) or t.startswith(o):
        return True
    return False


def _yes_no_option(options: list[str]) -> str | None:
    '''Pick the best "Yes"-ish option if the select looks like a yes/no question.'''
    for text in options:
        if _norm(text) in ("yes", "i do", "i have", "i am eligible"):
            return text
    for text in options:
        if _norm(text).startswith("yes"):
            return text
    return None


def _select_target(select_element, mapped: str) -> bool:
    '''Select the option matching `mapped` with fuzzy fallback. Never random.'''
    try:
        select = Select(select_element)
        options = [opt.text.strip() for opt in select.options if opt.text.strip()]
        if not options:
            return False
        current = _norm(select.first_selected_option.text)
        is_placeholder = not current or any(ph in current for ph in _DEFAULT_PLACEHOLDER_SELECT_OPTIONS)
        if not is_placeholder and not questions.overwrite_previous_answers:
            return False
        try:
            select.select_by_visible_text(mapped)
            return True
        except NoSuchElementException:
            pass
        candidates = [mapped]
        t = _norm(mapped)
        yn = _yes_no_option(options)
        if t in ("yes", "no"):
            candidates += ["Yes", "No"]
        elif t in ("decline", "prefer not", "not wish", "don't wish"):
            candidates += ["Decline", "Prefer not to say", "I don't wish", "I do not wish"]
        for cand in candidates:
            for opt in options:
                if _option_matches(opt, cand):
                    select.select_by_visible_text(opt)
                    return True
        if yn and t in ("yes", "no"):
            select.select_by_visible_text(yn)
            return True
    except StaleElementReferenceException:
        pass
    return False


def _fill_radio(inputs, mapped: str) -> bool:
    '''Click the radio whose option matches `mapped`.'''
    for radio in inputs:
        try:
            option_texts = []
            r_id = radio.get_attribute("id")
            if r_id:
                esc = r_id.replace("'", "''")
                try:
                    lbl = radio.find_element(By.XPATH, f"//label[@for='{esc}']")
                    if lbl.text:
                        option_texts.append(lbl.text.strip())
                except NoSuchElementException:
                    pass
            value = radio.get_attribute("value")
            if value:
                option_texts.append(value)
            for ot in option_texts:
                if _option_matches(ot, mapped):
                    if radio.is_enabled() and radio.is_displayed():
                        radio.click()
                        return True
                    return False
        except StaleElementReferenceException:
            continue
    return False


def _fill_yes_no_radio(inputs) -> bool:
    for radio in inputs:
        try:
            value = (radio.get_attribute("value") or "").lower().strip()
            if value in ("yes", "true", "1"):
                if radio.is_enabled() and radio.is_displayed():
                    radio.click()
                    return True
        except StaleElementReferenceException:
            continue
    return False


def _is_tag_input(el) -> bool:
    '''
    Best-effort detection of a "chips"/tags input (the kind where you type a
    value and press Enter/Space, or where the page shows already-added chips
    next to the field, e.g. "Press Enter after each" skill pickers).
    '''
    try:
        parent = el.find_element(By.XPATH, "..")
        text = (parent.get_attribute("innerText") or "")
        if "press enter" in text.lower() or "press return" in text.lower():
            return True
        # The container may already hold chips (buttons with aria-label="Remove X").
        chips = parent.find_elements(By.CSS_SELECTOR, "button[aria-label^='Remove'], [role='listbox'] button")
        if chips:
            return True
    except StaleElementReferenceException:
        pass
    return False


_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _to_input_date(value: str, input_type: str) -> str:
    '''
    Best-effort conversion of a configured date-ish value ("Apr 2026",
    "2026-04", "01/2026", "Jan 2025 - Present") into the format an HTML
    month/date/time input expects. "Present"/"now"/"current"/"today" map to the
    current month. Returns "" when the value cannot be parsed at all.
    '''
    v = _norm(str(value or ""))
    # "Jan 2024 - Present" -> "Jan 2024" (separator must be space-bound).
    v = re.split(r"\s+[-–—~]\s+|\s+to\s+", v)[0].strip()
    if not v or v in ("present", "now", "current", "today"):
        today = datetime.now()
        if input_type == "month":
            return f"{today.year:04d}-{today.month:02d}"
        if input_type == "date":
            return f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
        return ""
    # Already an ISO-ish date/YYYY-MM with a real year.
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", v)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if input_type == "month":
            return f"{y:04d}-{mo:02d}"
        if input_type == "date":
            d = int(m.group(3) or 1)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return v
    m = re.match(r"^(\d{1,2})[/.](\d{4})$", v)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        if input_type == "month":
            return f"{y:04d}-{mo:02d}"
        if input_type == "date":
            return f"{y:04d}-{mo:02d}-01"
        return v
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", v)
    if m:
        mo = _MONTH_NAMES.get(m.group(1).lower()[:3])
        y = int(m.group(2))
        if mo:
            if input_type == "month":
                return f"{y:04d}-{mo:02d}"
            if input_type == "date":
                return f"{y:04d}-{mo:02d}-01"
            return v
    # Fall back to a plain 4-digit year (education years as dates).
    m = re.match(r"^(\d{4})$", v)
    if m:
        y = int(m.group(1))
        return f"{y:04d}-01-01" if input_type == "date" else f"{y:04d}-01"
    return ""


def _type_value(el, mapped: str, input_type: str = "text") -> bool:
    '''
    Type `mapped` into a text element. For tag/chips inputs the value is sent
    one comma-separated chunk at a time, each followed by Enter, so the page
    commits every entry as its own chip (the way "Press Enter after each"
    skill/tech pickers behave). Date/month inputs set the value through the
    native JS path (send_keys is unreliable on native month pickers) and fire
    input/change so React-style forms register it.
    '''
    if input_type in ("month", "date", "week", "time", "datetime-local"):
        val = _to_input_date(mapped, input_type)
        if not val:
            return False
        try:
            el.click()
            driver = el.parent
            driver.execute_script(
                "var e=arguments[0];"
                "var proto=e.tagName.toLowerCase()==='textarea'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;"
                "var setter=Object.getOwnPropertyDescriptor(proto,'value').set;"
                "setter.call(e, arguments[1]);"
                "e.dispatchEvent(new Event('input',{bubbles:true}));"
                "e.dispatchEvent(new Event('change',{bubbles:true}));",
                el, val,
            )
            return True
        except Exception:
            try:
                el.clear()
                el.send_keys(val)
                return True
            except Exception:
                return False
    if not _is_tag_input(el):
        el.clear()
        el.send_keys(mapped)
        return True
    parts = [p.strip() for p in mapped.split(",") if p.strip()]
    if not parts:
        el.clear()
        el.send_keys(mapped)
        return True
    el.clear()
    for part in parts:
        el.send_keys(part)
        el.send_keys(Keys.ENTER)
    return True


# Reveal-style buttons that expand more fields ("Add a role", "Add another", ...).
# Never includes submit/finish terms; these must not accidentally submit the form.
_REVEAL_ADD_TERMS = (
    "add a ", "add another", "add more", "add qualification", "add education",
    "add a role", "add role", "add work", "add experience", "add a project",
    "add project", "add certification", "add an achievement", "add language",
)


def _reveal_target(button_text: str) -> int:
    '''
    How many times an "Add ..."-style button should be clicked, driven by how
    much data we actually have to fill. Never creates empty cards we can't fill.
    - project buttons: once per configured project
    - role/work/experience buttons: once (we answer the most recent role)
    - everything else (certifications, languages, achievements): nothing to answer
    '''
    t = _norm(button_text)
    if not any(term in t for term in _REVEAL_ADD_TERMS):
        return 0
    if "project" in t:
        return max(0, len(getattr(questions, "projects_summary", None) or []))
    if any(x in t for x in ("role", "work", "experience", "job")):
        if getattr(questions, "work_role", "") or getattr(questions, "work_company", ""):
            return 1
        return 0
    return 0


def _reveal_add_fields(driver, max_clicks: int = 12) -> int:
    '''
    Click visible expand/"add"-style buttons (e.g. "Add a project") the number of
    times that makes sense for the data we hold, so we never open empty cards we
    then cannot fill. Returns how many clicks were made. Never clicks
    submit/continue buttons.
    '''
    clicked: dict[str, int] = {}
    clicks = 0
    for _ in range(max_clicks):
        try:
            button = None
            for b in driver.find_elements(By.XPATH, "//button"):
                try:
                    if not b.is_displayed() or not b.is_enabled():
                        continue
                    t = _norm(b.text)
                    if len(t) < 2 or any(term in t for term in _SUBMIT_TERMS):
                        continue
                    target = _reveal_target(t)
                    if target <= 0 or clicked.get(t, 0) >= target:
                        continue
                    button = b
                    break
                except StaleElementReferenceException:
                    continue
            if button is None:
                break
            btn_text = _norm(button.text)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            driver.execute_script("arguments[0].click();", button)
            time.sleep(1.0)
            clicked[btn_text] = clicked.get(btn_text, 0) + 1
            clicks += 1
        except Exception as e:
            print_lg(f"[external_fill] Could not click a reveal/add button: {e}")
            break
    return clicks


# Module-level state, reset once per form fill, so project cards are filled in
# order (name, link, description, name, link, ...) regardless of DOM order.
_PROJECT_CARD = {"idx": 0, "active": False}


def _reset_project_state():
    _PROJECT_CARD["idx"] = 0
    _PROJECT_CARD["active"] = False


def _fill_controls_in_context(driver, ai_client, job_description: str) -> dict:
    '''Fill every fillable control currently in the active browsing context.'''
    _reset_project_state()
    counts = {"filled": 0, "skipped_existing": 0, "empty": 0, "unresolved": 0}
    try:
        controls = driver.find_elements(By.CSS_SELECTOR, "input, select, textarea")
    except StaleElementReferenceException:
        return counts

    # User activated "project mode" if the step carries project-card markers:
    # a "what is it / what was hard" textarea, optionally paired with LINK/NAME
    # fields. Requiring the essay-ish marker keeps a standalone "Link" or "Name"
    # input from switching project mode on unrelated steps.
    if getattr(questions, "projects_summary", None):
        hints = []
        for probe in controls:
            try:
                hints.append((probe, _norm(_resolve_label(probe))))
            except Exception:
                continue
        if any("what is it" in h or "what was hard" in h for _, h in hints):
            _PROJECT_CARD["active"] = True

    radio_groups: dict[str, list] = {}

    for el in controls:
        try:
            tag = el.tag_name.lower()
            if tag == "select":
                kind = "select"
            elif tag == "textarea":
                kind = "textarea"
            else:
                input_type = (el.get_attribute("type") or "text").lower()
                if input_type == "radio":
                    kind = "radio"
                elif input_type == "checkbox":
                    kind = "checkbox"
                elif input_type in ("text", "email", "tel", "number", "search", "url"):
                    kind = "text"
                elif input_type in ("month", "date", "week", "time", "datetime-local"):
                    kind = "date"
                else:
                    continue

            if not el.is_enabled():
                continue
            if kind in ("select", "text", "textarea", "date") and not el.is_displayed():
                continue

            name_attr = _norm(el.get_attribute("name") or "")
            ident = _norm(el.get_attribute("aria-label") or "")
            if any(marker in name_attr or marker in ident for marker in _SKIP_FIELD_MARKERS):
                continue

            label = _resolve_label(el)
            hint = _norm(label)

            if kind == "radio":
                radio_key = hint or ident or name_attr
                radio_groups.setdefault(radio_key, []).append(el)
                continue

            if kind == "checkbox":
                if el.is_selected() and not questions.overwrite_previous_answers:
                    counts["skipped_existing"] += 1
                    continue
                # Ancestor text helps disambiguate unlabeled boxes (fresher / no
                # experience vs. currently working here).
                ctx_terms = ""
                try:
                    ctx_terms = _norm(el.find_element(By.XPATH, "..").get_attribute("innerText") or "")
                except Exception:
                    pass
                is_fresher = any(t in ctx_terms or t in hint for t in ("fresher", "no formal work experience", "no work experience", "i am a fresher", "student", "graduate with no"))
                is_current_job = (
                    any(marker in hint for marker in ("currently working", "still working", "currently employed", "work here", "current role"))
                    or any(m in ctx_terms for m in ("currently working here", "i currently work here", "still working here", "current role"))
                ) and "present" in _norm(str(getattr(questions, "work_end_date", "") or ""))
                if is_fresher:
                    counts["skipped_existing"] += 1
                    continue
                if any(marker in hint for marker in _CHECKBOX_AGREE_MARKERS) or is_current_job or (
                    not hint and (el.get_attribute("aria-required") or "").lower() == "true"
                ):
                    try:
                        if el.is_displayed():
                            el.click()
                            counts["filled"] += 1 if el.is_selected() else 0
                            if not el.is_selected():
                                counts["unresolved"] += 1
                        else:
                            counts["unresolved"] += 1
                    except Exception:
                        counts["unresolved"] += 1
                    continue
                counts["unresolved"] += 1
                continue

            has_value = False
            if kind in ("text", "textarea"):
                has_value = bool((el.get_attribute("value") or "").strip())
            elif kind == "select":
                try:
                    has_value = bool(Select(el).first_selected_option.text.strip())
                except (NoSuchElementException, StaleElementReferenceException):
                    continue

            if has_value and not questions.overwrite_previous_answers:
                counts["skipped_existing"] += 1
                continue

            mapped = _static_answer(hint) if hint else None

            input_type = (el.get_attribute("type") or "text").lower()

            if kind in ("text", "textarea", "date"):
                if mapped is None and ai_client and hint:
                    mapped = answer_question(
                        ai_client, label, question_type="text",
                        job_description=job_description, user_information_all=questions.user_information_all,
                    )
                if not mapped:
                    counts["unresolved"] += 1
                    continue
                try:
                    if _type_value(el, mapped, input_type):
                        counts["filled"] += 1
                    else:
                        counts["unresolved"] += 1
                except Exception:
                    counts["unresolved"] += 1

            elif kind == "select":
                options = [opt.text.strip() for opt in Select(el).options if opt.text.strip()]
                if not options:
                    counts["unresolved"] += 1
                    continue
                if mapped is None:
                    mapped = _yes_no_option(options)
                    if not mapped and ai_client and hint:
                        mapped = answer_question(
                            ai_client, label, options=options, question_type="single_select",
                            job_description=job_description, user_information_all=questions.user_information_all,
                        )
                if mapped and _select_target(el, mapped):
                    counts["filled"] += 1
                else:
                    counts["unresolved"] += 1
        except StaleElementReferenceException:
            continue

    # Handle grouped radios after the loop so a group is answered once.
    for inputs in radio_groups.values():
        mapped = None
        hint = _norm(_resolve_label(inputs[0]))
        if hint:
            mapped = _static_answer(hint)
        if not mapped and ai_client and hint:
            mapped = answer_question(
                ai_client, hint, options=None, question_type="single_select",
                job_description=job_description, user_information_all=questions.user_information_all,
            )
        if mapped:
            if _fill_radio(inputs, mapped):
                counts["filled"] += 1
            else:
                counts["unresolved"] += 1
        elif _fill_yes_no_radio(inputs):
            counts["filled"] += 1
        else:
            counts["unresolved"] += 1

    return counts


def _collect_frames(driver, depth: int = 2) -> list[list]:
    '''Return iframe paths (lists of WebElements) up to `depth` deep.'''
    paths: list[list] = []
    frontier: list[list] = [[]]
    for _ in range(depth):
        next_frontier: list[list] = []
        for path in frontier:
            try:
                for frame in path:
                    driver.switch_to.frame(frame)
                frames = driver.find_elements(By.TAG_NAME, "iframe")
                for frame in frames:
                    paths.append(path + [frame])
                    next_frontier.append(path + [frame])
                driver.switch_to.default_content()
            except StaleElementReferenceException:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
        frontier = next_frontier
        if not frontier:
            break
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return paths


_ADVANCE_TERMS = ("continue", "next", "save and continue", "save & continue", "proceed", "go to")
_SUBMIT_TERMS = ("submit", " apply", "finish", "send", "done", "review")


def _find_step_advance_button(driver):
    '''Return the "Continue"/"Next" button for a wizard step, or None. Never a submit.'''
    try:
        buttons = driver.find_elements(By.XPATH, "//button")
    except Exception:
        return None
    for btn in buttons:
        try:
            if not btn.is_displayed() or not btn.is_enabled():
                continue
            text = _norm(btn.text)
            if len(text) < 2:
                continue
            if any(term in text for term in _SUBMIT_TERMS):
                continue
            if any(term in text for term in _ADVANCE_TERMS):
                return btn
        except StaleElementReferenceException:
            continue
    return None


def _page_fingerprint(driver) -> str:
    try:
        return driver.execute_script(
            "return (document.title + '|' + (document.body && document.body.innerText ? document.body.innerText.slice(0, 2000) : ''))"
        )
    except Exception:
        return ""


def fill_external_form(driver, ai_client=None, job_description: str = "", max_steps: int = 12, advance: bool = True) -> dict:
    '''
    Fill the external job application form on the current page, walking the
    steps of any multi-step wizard (clicking only "Continue"/"Next"). Returns a
    dict of outcome counters.

    The caller is responsible for switching tabs, recording the application
    link, and (optionally) confirming before any submission.

    `advance=False` fills the current step only and returns without clicking the
    wizard's Continue button (useful for step-by-step inspection).
    '''
    totals = {"filled": 0, "skipped_existing": 0, "empty": 0, "unresolved": 0}
    prev_fp = ""

    for _ in range(max_steps):
        step_fp = _page_fingerprint(driver)
        if prev_fp and step_fp and step_fp == prev_fp:
            print_lg("[external_fill] Page did not change (a required field is probably missing). Stopping the wizard walk.")
            break
        prev_fp = step_fp

        # Expand reveal-style sections (e.g. "Add a role", "Add another") so the
        # fields they hide are present when we scan for controls.
        _reveal_add_fields(driver, max_clicks=12)

        contexts = [[]] + _collect_frames(driver, depth=2)
        for path in contexts:
            try:
                for frame in path:
                    driver.switch_to.frame(frame)
                counts = _fill_controls_in_context(driver, ai_client, job_description)
                for key in totals:
                    totals[key] += counts[key]
            except Exception as e:
                print_lg(f"[external_fill] Could not process a frame: {e}")
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

        advance_btn = _find_step_advance_button(driver)
        if advance_btn is None or not advance:
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", advance_btn)
            driver.execute_script("arguments[0].click();", advance_btn)
            time.sleep(1.5)
        except Exception as e:
            print_lg(f"[external_fill] Could not advance to the next step: {e}")
            break

    print_lg(
        "[external_fill] filled {} field(s) | skipped already filled {} | left unresolved {}".format(
            totals["filled"], totals["skipped_existing"], totals["unresolved"],
        )
    )
    return totals