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

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
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
        return getattr(questions, "linkedin", "") or ""
    if has("github"):
        return getattr(questions, "github", "") or ""
    if has("website") or has("portfolio"):
        return getattr(questions, "website", "") or ""
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


def _fill_controls_in_context(driver, ai_client, job_description: str) -> dict:
    '''Fill every fillable control currently in the active browsing context.'''
    counts = {"filled": 0, "skipped_existing": 0, "empty": 0, "unresolved": 0}
    try:
        controls = driver.find_elements(By.CSS_SELECTOR, "input, select, textarea")
    except StaleElementReferenceException:
        return counts

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
                else:
                    continue

            if not el.is_enabled():
                continue
            if kind in ("select", "text", "textarea") and not el.is_displayed():
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
                if any(marker in hint for marker in _CHECKBOX_AGREE_MARKERS) or (
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

            if kind in ("text", "textarea"):
                if mapped is None and ai_client and hint:
                    mapped = answer_question(
                        ai_client, label, question_type="text",
                        job_description=job_description, user_information_all=questions.user_information_all,
                    )
                if not mapped:
                    counts["unresolved"] += 1
                    continue
                try:
                    el.clear()
                    el.send_keys(mapped)
                    counts["filled"] += 1
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


def fill_external_form(driver, ai_client=None, job_description: str = "", max_steps: int = 12) -> dict:
    '''
    Fill the external job application form on the current page, walking the
    steps of any multi-step wizard (clicking only "Continue"/"Next"). Returns a
    dict of outcome counters.

    The caller is responsible for switching tabs, recording the application
    link, and (optionally) confirming before any submission.
    '''
    totals = {"filled": 0, "skipped_existing": 0, "empty": 0, "unresolved": 0}
    prev_fp = ""

    for _ in range(max_steps):
        step_fp = _page_fingerprint(driver)
        if prev_fp and step_fp and step_fp == prev_fp:
            print_lg("[external_fill] Page did not change (a required field is probably missing). Stopping the wizard walk.")
            break
        prev_fp = step_fp

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

        advance = _find_step_advance_button(driver)
        if advance is None:
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", advance)
            driver.execute_script("arguments[0].click();", advance)
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