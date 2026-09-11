'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08
'''


# Imports
import os
import csv
import re
import time
import json
import sys
import pyautogui
from urllib.parse import quote

# Raise the CSV field-size cap so very long job descriptions don't trip the writer.
csv.field_size_limit(1000000)

from random import choice, shuffle, randint
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, NoSuchWindowException, ElementNotInteractableException, WebDriverException

from config.personals import *
from config.questions import *
from config.search import *
from config.secrets import use_AI, username, password, ai_provider, free_daily_limit
from config.settings import *

from modules.open_chrome import *
from modules.helpers import *
from modules.clickers_and_finders import *
from modules.validator import validate_config
from modules import events
from config._overrides import candidate_experience_years
from modules.external_fill import fill_external_form
from modules import dry_run
from modules.dry_run import is_dry_run
from modules.license import (
    applications_today, can_submit, is_paid, record_application, show_upsell,
    can_scan_referral, record_referral_scan, show_referral_upsell,
    can_send_referral, referral_scans_today, referral_messages_today,
)

if use_AI:
    from modules.ai.connections import create_ai_client, extract_skills, answer_question, close_ai_client

from typing import Literal


pyautogui.FAILSAFE = False
# if use_resume_generator:    from resume_generator import is_logged_in_GPT, login_GPT, open_resume_chat, create_custom_resume


#< Hard company blocklist (exact company-name match, independent of the
#< 'About company' text). Populated once at startup from config/search.py and,
#< when enabled, from the employers detected on the resume file.
_hard_skip_companies = None


def _app_dir() -> str:
    '''The folder that holds the project / the bundled app's executable.'''
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _has_any_setup() -> bool:
    '''True once the user has saved anything via setup (config file present, or a
    resume path already set). Used by the first-run guard to tell a truly brand-new
    user to run setup instead of launching the browser with blanks.'''
    try:
        if os.path.exists(os.path.join(_app_dir(), "user_config.json")):
            return True
    except OSError:
        pass
    return bool(default_resume_path)


def _init_hard_skip() -> set:
    '''Build the exact-company-name blocklist set (lowercased names).'''
    global _hard_skip_companies
    names = {str(c).strip().lower() for c in (skip_companies or []) if str(c).strip()}
    if skip_resume_companies:
        try:
            from modules.resumes.profile import detect_companies, extract_text
            if default_resume_path:
                companies = detect_companies(extract_text(str(default_resume_path)))
                names.update(c.lower() for c in companies if c.strip())
                if companies:
                    print_lg(f'Blocking {len(companies)} companies from your resume: {", ".join(companies)}')
        except Exception as e:
            print_lg("Could not read companies from resume for the blocklist.", e)
    _hard_skip_companies = names
    return names


def _hard_skip_company(company: str | None) -> bool:
    '''True when this job's company is on the blocklist.

    Substring-matched both ways so "FlytBase", "FlytBase Inc" and
    "FlytBase Technologies" all count as the same company.
    '''
    if _hard_skip_companies is None:
        _init_hard_skip()
    if not company:
        return False
    c = company.strip().lower()
    if c in _hard_skip_companies:
        return True
    return any(c in name or name in c for name in _hard_skip_companies)


#< Global Variables and logics

if run_in_background == True:
    pause_at_failed_question = False
    pause_before_submit = False
    run_non_stop = False

first_name = first_name.strip()
middle_name = middle_name.strip()
last_name = last_name.strip()
full_name = first_name + " " + middle_name + " " + last_name if middle_name else first_name + " " + last_name

useNewResume = True
randomly_answered_questions = set()

tabs_count = 1
easy_applied_count = 0
external_jobs_count = 0
failed_count = 0
skip_count = 0
dailyEasyApplyLimitReached = False

re_experience = re.compile(
    r'[(]?\s*(\d+)\s*[)]?\s*[-to]*\s*\d*[+]*\s*'
    r'(?:years?|ans|an\b|ann\S*|a[ñn]os|Jahre|Jahr|Jahren|Jahres|anni|anno|年|년)',
    re.IGNORECASE)

desired_salary_lakhs = str(round(desired_salary / 100000, 2))
desired_salary_monthly = str(round(desired_salary/12, 2))
desired_salary = str(desired_salary)

current_ctc_lakhs = str(round(current_ctc / 100000, 2))
current_ctc_monthly = str(round(current_ctc/12, 2))
current_ctc = str(current_ctc)

# Candidate's true experience: the persisted Resume Profile wins; the
# `search.current_experience` config value is only a fallback (never the truth).
_profile_years = candidate_experience_years()
if _profile_years is not None:
    if current_experience != int(round(_profile_years)):
        print_lg(
            f"Using Resume Profile experience ({_profile_years} years) for the experience gate "
            f"(search.current_experience was {current_experience})."
        )
        current_experience = int(round(_profile_years))


def _dismiss_page_overlay() -> None:
    """Dismiss a LinkedIn page-level overlay (not the Easy Apply modal)."""
    # 1) Escape first: closes the common modal/promo floaters without touching
    #    any Easy Apply modal (which is never open at this point).
    try:
        actions.send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    sleep(1)
    # 2) Click the generic modal backdrop if one is present.
    try:
        backdrop = driver.find_element(By.CSS_SELECTOR, "div.artdeco-modal-overlay")
        if backdrop.is_displayed():
            driver.execute_script("arguments[0].click();", backdrop)
    except Exception:
        pass
    sleep(1)
    # 3) Fall back to any Dismiss/Close button.
    try:
        dismiss_buttons = driver.find_elements(
            By.CSS_SELECTOR,
            "button[aria-label*='Dismiss'], button[aria-label*='Close'], button[aria-label*='close']",
        )
        if dismiss_buttons and dismiss_buttons[0].is_displayed():
            dismiss_buttons[0].click()
    except Exception:
        pass


def robust_click(
    element: WebElement,
    description: str = "element",
    attempts: int = 5,
    verify=None,
    resolver=None,
    js_fallback: bool = True,
) -> bool:
    '''
    Click with overlay detection/dismiss/retry/verify.

    Attempts the click up to `attempts` times. On a click-intercepted failure it
    dismisses a page-level overlay and retries (emitting OVERLAY_DETECTED /
    OVERLAY_DISMISSED events). An optional `verify` expected-conditions predicate
    confirms the click landed. `resolver`, when given, re-resolves the element on
    each attempt (elements can go stale after an overlay dismiss or a re-render).
    When `js_fallback` is enabled, the last attempt uses a direct DOM click via
    JavaScript, which dispatches straight to the target element and bypasses any
    overlay that intercepts Selenium's synthesized pointer event.
    Raises ElementClickInterceptedException only after all attempts are exhausted.
    '''
    last_error = None
    for attempt in range(attempts):
        try:
            el = resolver() if resolver is not None else element
            if not hasattr(el, "click"):
                raise ElementClickInterceptedException(f"resolver returned non-element {el!r}")
            try:
                scroll_to_view(driver, el, True)
            except Exception as se:
                last_error = se
                events.emit("OVERLAY_DETECTED", description=description, attempt=attempt + 1, reason=f"scroll-failed: {str(se)[:120]}")
            try:
                el.click()
                if verify is not None:
                    try:
                        WebDriverWait(driver, 8).until(verify)
                    except Exception as ve:
                        last_error = ve
                        events.emit("OVERLAY_DETECTED", description=description, attempt=attempt + 1, reason="click-not-verified")
                        _dismiss_page_overlay()
                        sleep(1)
                        continue
                return True
            except ElementClickInterceptedException as e:
                last_error = e
                events.emit("OVERLAY_DETECTED", description=description, attempt=attempt + 1)
                _dismiss_page_overlay()
                events.emit("OVERLAY_DISMISSED", description=description, attempt=attempt + 1)
                if js_fallback and attempt >= attempts - 1:
                    # Final attempt: dispatch the click directly on the DOM node. This
                    # defeats overlay interception for plain <button> elements.
                    el = resolver() if resolver is not None else element
                    try:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        except Exception:
                            pass
                        driver.execute_script("arguments[0].click();", el)
                        events.emit("APPLY_JS_CLICK", description=description)
                        return True
                    except Exception as je:
                        last_error = je
                        events.emit("FAILURE", description=description, stage="apply_click_js_fallback", error=str(je)[:200])
                sleep(1)
        except NoSuchWindowException:
            raise
        except Exception as e:
            last_error = e
            sleep(1)
    raise ElementClickInterceptedException(f"Failed to click {description!r} after {attempts} attempts ({last_error})")

notice_period_months = str(notice_period//30)
notice_period_weeks = str(notice_period//7)
notice_period = str(notice_period)

aiClient = None
about_company_for_ai = None  # filled in later, once we're processing a specific job

#>


#< Login Functions
def is_logged_in_LN() -> bool:
    '''
    Function to check if user is logged-in in LinkedIn
    * Returns: `True` if user is logged-in or `False` if not
    '''
    url = driver.current_url or ""
    if "authwall" in url: return False
    if driver.current_url == "https://www.linkedin.com/feed/": return True
    if "linkedin.com/login" in url: return False
    if try_linkText(driver, "Sign in"): return False
    if try_xp(driver, '//button[@type="submit" and contains(text(), "Sign in")]'):  return False
    if try_linkText(driver, "Join now"): return False
    print_lg("Didn't find Sign in link, so assuming user is logged in!")
    return True


def login_LN() -> None:
    '''
    Function to login for LinkedIn
    * Tries to login using given `username` and `password` from `secrets.py`
    * If failed, tries to login using saved LinkedIn profile button if available
    * If both failed, asks user to login manually
    '''
    driver.get("https://www.linkedin.com/login")
    if username == "username@example.com" and password == "example_password":
        print_lg("User did not configure username and password in secrets.py, hence can't login automatically! Please login manually!")
        manual_login_retry(is_logged_in_LN, 60)
        return

    sleep(2)

    def _visible_input(selectors: list[str], wait_secs: float = 12):
        '''
        Return the first VISIBLE input matching any of the given CSS selectors,
        retrying for up to wait_secs. LinkedIn renders hidden duplicate fields
        (e.g. a hidden webauthn/passkey variant), so the first match may not be
        the real field - only a displayed one is usable.
        '''
        deadline = time.time() + wait_secs
        while time.time() < deadline:
            for sel in selectors:
                try:
                    for el in driver.find_elements(By.CSS_SELECTOR, sel):
                        try:
                            if el.is_displayed():
                                return el
                        except Exception:
                            continue
                except Exception:
                    continue
            sleep(1)
        return None

    # Try finding username field
    user_input = _visible_input([
        "#username",
        "#session_key",
        "input[name='session_key']",
        "input[autocomplete='username']",
        "input[type='email']",
    ])

    if user_input:
        try:
            user_input.clear()
            user_input.send_keys(username)
        except Exception as e:
            print_lg("Error entering username:", e)
    else:
        print_lg("Couldn't find username field (may already be on feed or challenge page).")

    # Try finding password field
    pass_input = _visible_input([
        "#password",
        "#session_password",
        "input[name='session_password']",
        "input[autocomplete='current-password']",
        "input[type='password']",
    ])

    if pass_input:
        try:
            pass_input.clear()
            pass_input.send_keys(password)
        except Exception as e:
            print_lg("Error entering password:", e)
    else:
        print_lg("Couldn't find password field.")

    # Click Sign In button
    try:
        for selector in [
            "//button[@type='submit' and contains(text(), 'Sign in')]",
            "//button[@type='submit']",
            "//button[contains(., 'Sign in')]",
            "//input[@type='submit']"
        ]:
            try:
                btn = driver.find_element(By.XPATH, selector)
                if btn and btn.is_displayed():
                    btn.click()
                    break
            except Exception:
                continue
    except Exception as e1:
        try:
            profile_button = find_by_class(driver, "profile__details")
            profile_button.click()
        except Exception as e2:
            print_lg("Couldn't Login automatically.")

    try:
        WebDriverWait(driver, 8).until(
            lambda d: "feed" in d.current_url or is_logged_in_LN()
        )
        print_lg("Login successful!")
        return
    except Exception:
        print_lg("Auto-login pending (LinkedIn may require verification or captcha).")
        manual_login_retry(is_logged_in_LN, 240)

#>


#< Authenticated-session probes (shared by the referral send flow and tests)
def _session_has_li_at(some_driver=driver) -> bool:
    '''
    True if LinkedIn's session cookie `li_at` is present in the current
    browser profile. This is the definitive "am I logged in" signal: it works
    on ANY page, needs no DOM and no navigation, unlike checking for nav
    markers. Selenium returns HttpOnly cookies (like li_at) from get_cookies().
    '''
    try:
        for c in some_driver.get_cookies():
            if c.get("name") == "li_at" and c.get("value"):
                return True
    except Exception:
        pass
    return False


def _signed_in_markers(some_driver=driver) -> bool:
    '''
    True if the current page renders LinkedIn's authenticated top-nav markers
    (global-nav header, "My Network", the Me menu, the search box). Defensive:
    any one match is enough so a single probe miss can't fail the check.
    '''
    try:
        def _ok(probe) -> bool:
            try:
                return probe is not False
            except Exception:
                return False
        return any([
            _ok(try_xp(some_driver, "//header[contains(@class, 'global-nav')]", click=False)),
            _ok(try_linkText(some_driver, "My Network")),
            _ok(some_driver.find_element(By.CLASS_NAME, "global-nav__me")),
            _ok(some_driver.find_element(By.CSS_SELECTOR, "input[placeholder*='Search']")),
        ])
    except Exception:
        return False


def _real_session_ready(some_driver=driver) -> bool:
    '''
    Reliable authenticated-session probe for the referral-send flow. Unlike the
    old check it does NOT force-navigate to /feed/ first - that abrupt jump is
    exactly what makes LinkedIn throw a challenge interstitial which falsely
    reads as "not logged in". Instead:
      1. The `li_at` cookie alone decides on any page (no navigation needed).
      2. Failing that, the CURRENT page's signed-in markers decide - after a
         referral scan we are standing on a logged-in jobs-search page with the
         full top nav, so this passes without navigating anywhere.
      3. Only if the current page is ambiguous (or a login/authwall itself) do
         we probe /feed/ as a last resort.
    '''
    try:
        if _session_has_li_at(some_driver):
            return True
        url = some_driver.current_url or ""
        if "login" not in url and "authwall" not in url:
            if _signed_in_markers(some_driver):
                return True
        some_driver.get("https://www.linkedin.com/feed/")
        sleep(3)
        url = some_driver.current_url or ""
        if "login" in url or "authwall" in url:
            return False
        return _signed_in_markers(some_driver)
    except Exception:
        return False

#>



def get_applied_job_ids() -> set[str]:
    '''
    Function to get a `set` of applied job's Job IDs
    * Returns a set of Job IDs from existing applied jobs history csv file
    '''
    job_ids: set[str] = set()
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                job_ids.add(row[0])
    except FileNotFoundError:
        print_lg(f"The CSV file '{file_name}' does not exist.")
    return job_ids



def set_search_location(desired_location: str = search_location) -> None:
    '''
    Function to set the search location box to a single location.
    LinkedIn only accepts one location at a time - a comma-joined list is
    ignored and the results silently fall back to the account's default
    location. Each call handles ONE token ("Remote", "Pune", "Singapore", ...).
    '''
    desired_location = (desired_location or "").strip()
    if not desired_location:
        return
    try:
        search_location_ele = try_xp(driver, ".//input[@aria-label='City, state, or zip code' and not(@disabled)]", False) #  and not(@aria-hidden='true')]")
        if not search_location_ele:
            search_location_ele = try_xp(driver, ".//input[@placeholder='City, state, or zip code' and not(@disabled)]", False)
        if not search_location_ele:
            search_location_ele = try_xp(driver, ".//input[contains(@aria-label, 'ocation') and not(@disabled)]", False)
        if search_location_ele and search_location_ele.get_attribute("value"):
            current = search_location_ele.get_attribute("value").strip()
            if desired_location.lower() in current.lower():
                print_lg(f'Search location already set to "{current}".')
                return
        if not search_location_ele:
            print_lg("Search Location input was not given!")
            return
        print_lg(f'Setting search location as: "{desired_location}"')
        search_location_ele.click()
        sleep(1)
        search_location_ele.send_keys(Keys.CONTROL, "a")
        search_location_ele.send_keys(desired_location)
        sleep(2)
        search_location_ele.send_keys(Keys.ENTER)
        sleep(2)
        try_xp(driver, ".//button[@aria-label='Cancel']")
    except ElementNotInteractableException:
        try_xp(driver, ".//label[@class='jobs-search-box__input-icon jobs-search-box__keywords-label']")
        actions.send_keys(Keys.TAB, Keys.TAB).perform()
        actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
        actions.send_keys(desired_location).perform()
        sleep(2)
        actions.send_keys(Keys.ENTER).perform()
        try_xp(driver, ".//button[@aria-label='Cancel']")
    except Exception as e:
        try_xp(driver, ".//button[@aria-label='Cancel']")
        print_lg("Failed to update search location, continuing with default location!", e)


def apply_filters(location_value: str = search_location) -> bool:
    '''
    Function to apply job search filters. Returns True on success, False when
    the filters could not be applied (caller re-loads the location-scoped URL).
    '''
    try:
        set_search_location(location_value)

        recommended_wait = 1 if click_gap < 1 else 0

        wait.until(EC.presence_of_element_located((By.XPATH, '//button[normalize-space()="All filters"]'))).click()
        buffer(recommended_wait)

        wait_span_click(driver, sort_by)
        wait_span_click(driver, date_posted)
        buffer(recommended_wait)

        multi_sel_noWait(driver, experience_level) 
        multi_sel_noWait(driver, companies, actions)
        if experience_level or companies: buffer(recommended_wait)

        multi_sel_noWait(driver, job_type)
        multi_sel_noWait(driver, on_site)
        if job_type or on_site: buffer(recommended_wait)

        if easy_apply_only: boolean_button_click(driver, actions, "Easy Apply")
        
        multi_sel_noWait(driver, location)
        multi_sel_noWait(driver, industry)
        if location or industry: buffer(recommended_wait)

        multi_sel_noWait(driver, job_function)
        multi_sel_noWait(driver, job_titles)
        if job_function or job_titles: buffer(recommended_wait)

        if under_10_applicants: boolean_button_click(driver, actions, "Under 10 applicants")
        if in_your_network: boolean_button_click(driver, actions, "In your network")
        if fair_chance_employer: boolean_button_click(driver, actions, "Fair Chance Employer")

        wait_span_click(driver, salary)
        buffer(recommended_wait)
        
        multi_sel_noWait(driver, benefits)
        multi_sel_noWait(driver, commitments)
        if benefits or commitments: buffer(recommended_wait)

        show_results_button: WebElement = driver.find_element(By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "apply current filters to show")]')
        show_results_button.click()

        global pause_after_filters
        if pause_after_filters and "Turn off Pause after search" == pyautogui.confirm("These are your configured search results and filter. It is safe to change them while this dialog is open, any changes later could result in errors and skipping this search run.", "Please check your results", ["Turn off Pause after search", "Look's good, Continue"]):
            pause_after_filters = False

    except Exception as e:
        print_lg("Setting the preferences failed!")
        try: pyautogui.confirm(f"Faced error while applying filters. Please make sure correct filters are selected, click on show results and click on any button of this dialog, I know it sucks. Can't turn off Pause after search when error occurs! ERROR: {e}", ["Doesn't look good, but Continue XD", "Look's good, Continue"])
        except Exception: pass
        return False

    return True



def get_page_info() -> tuple[WebElement | None, int | None]:
    '''
    Function to get pagination element and current page number
    '''
    try:
        pagination_element = try_find_by_classes(driver, ["jobs-search-pagination__pages", "artdeco-pagination", "artdeco-pagination__pages"])
        scroll_to_view(driver, pagination_element)
        current_page = int(pagination_element.find_element(By.XPATH, "//button[contains(@class, 'active')]").text)
    except Exception as e:
        print_lg("Failed to find Pagination element, hence couldn't scroll till end!")
        pagination_element = None
        current_page = None
        print_lg(e)
    return pagination_element, current_page



def get_job_main_details(job: WebElement, blacklisted_companies: set, rejected_jobs: set) -> tuple[str, str, str, str, str, bool]:
    '''
    # Function to get job main details.
    Returns a tuple of (job_id, title, company, work_location, work_style, skip)
    * job_id: Job ID
    * title: Job title
    * company: Company name
    * work_location: Work location of this job
    * work_style: Work style of this job (Remote, On-site, Hybrid)
    * skip: A boolean flag to skip this job
    '''
    skip = False
    job_id = job.get_dom_attribute('data-occludable-job-id') or "unknown"
    buttons = job.find_elements(By.TAG_NAME, 'a')
    if not buttons:
        print_lg(f'Job card {job_id} has no title link, skipping it.')
        return (job_id, "Unknown", "Unknown", "Unknown", "Unknown", True)
    job_details_button = buttons[0]
    scroll_to_view(driver, job_details_button, True)
    title = job_details_button.text
    title = title[:title.find("\n")]
    try:
        other_details = job.find_element(By.CLASS_NAME, 'artdeco-entity-lockup__subtitle').text
        index = other_details.find(' · ')
        company = other_details[:index]
        work_location = other_details[index+3:]
        work_style = work_location[work_location.rfind('(')+1:work_location.rfind(')')]
        work_location = work_location[:work_location.rfind('(')].strip()
    except Exception as subtitle_error:
        print_lg(f'Could not read details for job card {job_id}, skipping it.', subtitle_error)
        return (job_id, title, "Unknown", "Unknown", "Unknown", True)
    
    # Skip if previously rejected due to blacklist or already applied
    if company in blacklisted_companies:
        print_lg(f'Skipping "{title} | {company}" job (Blacklisted Company). Job ID: {job_id}!')
        skip = True
    elif _hard_skip_company(company):
        print_lg(f'Skipping "{title} | {company}" job (Company on your blocklist). Job ID: {job_id}!')
        skip = True
    elif job_id in rejected_jobs: 
        print_lg(f'Skipping previously rejected "{title} | {company}" job. Job ID: {job_id}!')
        skip = True
    try:
        if job.find_element(By.CLASS_NAME, "job-card-container__footer-job-state").text == "Applied":
            skip = True
            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
    except: pass
    if not skip:
        last_error = None
        for attempt in range(5):
            try:
                scroll_to_view(driver, job_details_button, True)
                job_details_button.click()
                try:
                    WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CLASS_NAME, "jobs-company__box")))
                except Exception as pane_error:
                    print_lg(f'Details pane did not load for "{title}" (Job ID: {job_id}), skipping it.', pane_error)
                    skip = True
                break
            except NoSuchWindowException:
                raise  # session really lost: let the outer error handler decide
            except ElementClickInterceptedException as e:
                last_error = e
                print_lg(f'Click on "{title}" was blocked by an overlay ({attempt + 1}/5), dismissing it and retrying...')
                discard_job()
                try:
                    dismiss_buttons = driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Dismiss'], button[aria-label*='Close'], button[aria-label*='close']")
                    if dismiss_buttons and dismiss_buttons[0].is_displayed():
                        dismiss_buttons[0].click()
                except Exception:
                    pass
                sleep(1)
            except Exception as e:
                last_error = e
                print_lg(f'Click on "{title}" was blocked ({attempt + 1}/5), waiting for the result list to settle...')
                try:
                    overlay = driver.find_element(By.CLASS_NAME, "jobs-loader")
                    if overlay.is_displayed():
                        sleep(2)
                except Exception:
                    sleep(1)
        else:
            print_lg(f'Failed to click "{title} | {company}" job on details button. Job ID: {job_id}!', last_error)
            skip = True  # Skip this job instead of crashing the whole run
    buffer(click_gap)
    return (job_id,title,company,work_location,work_style,skip)


# Function to check for Blacklisted words in About Company
def check_blacklist(rejected_jobs: set, job_id: str, company: str, blacklisted_companies: set) -> tuple[set, set, WebElement] | ValueError:
    jobs_top_card = try_find_by_classes(driver, ["job-details-jobs-unified-top-card__primary-description-container","job-details-jobs-unified-top-card__primary-description","jobs-unified-top-card__primary-description","jobs-details__main-content"])
    about_company_org = find_by_class(driver, "jobs-company__box")
    scroll_to_view(driver, about_company_org)
    about_company_org = about_company_org.text
    about_company = about_company_org.lower()
    skip_checking = False
    for word in about_company_good_words:
        if word.lower() in about_company:
            print_lg(f'Found the word "{word}". So, skipped checking for blacklist words.')
            skip_checking = True
            break
    if not skip_checking:
        for word in about_company_bad_words: 
            if word.lower() in about_company: 
                rejected_jobs.add(job_id)
                blacklisted_companies.add(company)
                raise ValueError(f'\n"{about_company_org}"\n\nContains "{word}".')
    buffer(click_gap)
    scroll_to_view(driver, jobs_top_card)
    return rejected_jobs, blacklisted_companies, jobs_top_card



# Function to extract years of experience required from About Job
def extract_years_of_experience(text: str) -> int | str:
    # Extract all patterns like '10+ years', '5 years', '3-5 years',
    # '5 ans', '3 Jahre', '4 anni', etc.
    matches = re.findall(re_experience, text)
    if len(matches) == 0:
        print_lg(f'\n{text}\n\nCouldn\'t find experience requirement in About the Job!')
        return "Unknown"
    values = [int(match) for match in matches if int(match) <= 12]
    if not values:
        return "Unknown"
    return max(values)



def get_job_description(
) -> tuple[
    str | Literal['Unknown'],
    int | Literal['Unknown'],
    bool,
    str | None,
    str | None
    ]:
    '''
    # Job Description
    Function to extract job description from About the Job.
    ### Returns:
    - `jobDescription: str | 'Unknown'`
    - `experience_required: int | 'Unknown'`
    - `skip: bool`
    - `skipReason: str | None`
    - `skipMessage: str | None`
    '''
    # Initialise every return value before the try, so an early failure (e.g. the
    # description element not being found) can never leave them unbound.
    jobDescription = "Unknown"
    experience_required = "Unknown"
    skip = False
    skipReason = None
    skipMessage = None
    try:
        found_masters = 0
        jobDescription = find_by_class(driver, "jobs-box__html-content").text
        jobDescriptionLow = jobDescription.lower()
        for word in bad_words:
            if word.lower() in jobDescriptionLow:
                skipMessage = f'\n{jobDescription}\n\nContains bad word "{word}". Skipping this job!\n'
                skipReason = "Found a Bad Word in About Job"
                skip = True
                break
        if not skip and security_clearance == False and ('polygraph' in jobDescriptionLow or 'clearance' in jobDescriptionLow or 'secret' in jobDescriptionLow):
            skipMessage = f'\n{jobDescription}\n\nFound "Clearance" or "Polygraph". Skipping this job!\n'
            skipReason = "Asking for Security clearance"
            skip = True
        if not skip:
            if did_masters and 'master' in jobDescriptionLow:
                print_lg(f'Found the word "master" in \n{jobDescription}')
                found_masters = 2
            experience_required = extract_years_of_experience(jobDescription)
            if current_experience > -1 and isinstance(experience_required, int) and experience_required > current_experience + found_masters:
                skipMessage = f'\n{jobDescription}\n\nExperience required {experience_required} > Current Experience {current_experience + found_masters}. Skipping this job!\n'
                skipReason = "Required experience is high"
                skip = True
    except Exception as e:
        if jobDescription == "Unknown":    print_lg("Unable to extract job description!")
        else:
            experience_required = "Error in extraction"
            print_lg("Unable to extract years of experience required!")
            # print_lg(e)
    return jobDescription, experience_required, skip, skipReason, skipMessage
        


# Function to upload resume
def upload_resume(modal: WebElement, resume: str) -> tuple[bool, str]:
    try:
        modal.find_element(By.NAME, "file").send_keys(os.path.abspath(resume))
        return True, os.path.basename(default_resume_path)
    except: return False, "Previous resume"

# Function to answer common questions for Easy Apply
def answer_common_questions(label: str, answer: str) -> str:
    if 'sponsorship' in label or 'visa' in label: answer = require_visa
    return answer


# Function to answer the questions for Easy Apply
def answer_questions(modal: WebElement, questions_list: set, work_location: str, job_description: str | None = None ) -> set:
    # Get all questions from the page

    all_questions = modal.find_elements(By.XPATH, ".//div[@data-test-form-element]")

    def _track(label_org: str, answer: str, qtype: str, prev_answer) -> None:
        questions_list.add((label_org, answer, qtype, prev_answer))
        events.emit("ANSWER_FILLED", qtype=qtype, question=label_org[:160], answer=str(answer)[:120])

    for Question in all_questions:
        events.emit("QUESTION_DETECTED")
        # Check if it's a select Question
        select = try_xp(Question, ".//select", False)
        if select:
            label_org = "Unknown"
            try:
                label = Question.find_element(By.TAG_NAME, "label")
                label_org = label.find_element(By.TAG_NAME, "span").text
            except: pass
            answer = 'Yes'
            label = label_org.lower()
            select = Select(select)
            selected_option = select.first_selected_option.text
            optionsText = []
            options = '"List of phone country codes"'
            if label != "phone country code":
                optionsText = [option.text for option in select.options]
                options = "".join([f' "{option}",' for option in optionsText])
            prev_answer = selected_option
            if overwrite_previous_answers or selected_option == "Select an option":
                # Pick a sensible answer for the dropdown from the question label.
                if 'email' in label or 'phone' in label:
                    answer = prev_answer
                elif 'gender' in label or 'sex' in label:
                    answer = gender
                elif 'disability' in label:
                    answer = disability_status
                elif 'proficiency' in label:
                    answer = 'Professional'
                elif any(term in label for term in ['location', 'city', 'state', 'country']):
                    if 'country' in label:
                        answer = country
                    elif 'state' in label:
                        answer = state
                    elif 'city' in label:
                        answer = current_city if current_city else work_location
                    else:
                        answer = work_location
                else:
                    answer = answer_common_questions(label, answer)
                try:
                    select.select_by_visible_text(answer)
                except NoSuchElementException:
                    # The exact text isn't an option; map our answer onto the nearest option.
                    lower_answer = answer.lower()
                    if answer == 'Decline':
                        candidate_phrases = ["Decline", "not wish", "don't wish", "Prefer not", "not want"]
                    elif 'yes' in lower_answer:
                        candidate_phrases = ["Yes", "Agree", "I do", "I have"]
                    elif 'no' in lower_answer:
                        candidate_phrases = ["No", "Disagree", "I don't", "I do not"]
                    else:
                        candidate_phrases = [answer, lower_answer, answer.upper(),
                                             ''.join(ch for ch in answer if ch.isalnum())]
                    matched = False
                    for phrase in candidate_phrases:
                        low_phrase = phrase.lower()
                        for option in optionsText:
                            low_option = option.lower()
                            if low_phrase in low_option or low_option in low_phrase:
                                select.select_by_visible_text(option)
                                answer = option
                                matched = True
                                break
                        if matched:
                            break
                    if not matched:
                        print_lg(f'No option matched "{answer}" for "{label_org}", picking one at random.')
                        select.select_by_index(randint(1, len(select.options) - 1))
                        answer = select.first_selected_option.text
                        randomly_answered_questions.add((f'{label_org} [ {options} ]', "select"))
            _track(f'{label_org} [ {options} ]', answer, "select", prev_answer)
            continue
        
        # Check if it's a radio Question
        radio = try_xp(Question, './/fieldset[@data-test-form-builder-radio-button-form-component="true"]', False)
        if radio:
            prev_answer = None
            label = try_xp(radio, './/span[@data-test-form-builder-radio-button-form-component__title]', False)
            try: label = find_by_class(label, "visually-hidden", 2.0)
            except: pass
            label_org = label.text if label else "Unknown"
            answer = 'Yes'
            label = label_org.lower()

            label_org += ' [ '
            options = radio.find_elements(By.TAG_NAME, 'input')
            options_labels = []
            
            for option in options:
                id = option.get_attribute("id")
                option_label = try_xp(radio, f'.//label[@for="{id}"]', False)
                options_labels.append( f'"{option_label.text if option_label else "Unknown"}"<{option.get_attribute("value")}>' ) # Saving option as "label <value>"
                if option.is_selected(): prev_answer = options_labels[-1]
                label_org += f' {options_labels[-1]},'

            if overwrite_previous_answers or prev_answer is None:
                if 'citizenship' in label or 'employment eligibility' in label: answer = us_citizenship
                elif 'veteran' in label or 'protected' in label: answer = veteran_status
                elif 'disability' in label or 'handicapped' in label: 
                    answer = disability_status
                else: answer = answer_common_questions(label,answer)
                foundOption = try_xp(radio, f".//label[normalize-space()='{answer}']", False)
                if foundOption: 
                    actions.move_to_element(foundOption).click().perform()
                else:    
                    possible_answer_phrases = ["Decline", "not wish", "don't wish", "Prefer not", "not want"] if answer == 'Decline' else [answer]
                    ele = options[0]
                    answer = options_labels[0]
                    for phrase in possible_answer_phrases:
                        for i, option_label in enumerate(options_labels):
                            if phrase in option_label:
                                foundOption = options[i]
                                ele = foundOption
                                answer = f'Decline ({option_label})' if len(possible_answer_phrases) > 1 else option_label
                                break
                        if foundOption: break
                    # if answer == 'Decline':
                    #     answer = options_labels[0]
                    #     for phrase in ["Prefer not", "not want", "not wish"]:
                    #         foundOption = try_xp(radio, f".//label[normalize-space()='{phrase}']", False)
                    #         if foundOption:
                    #             answer = f'Decline ({phrase})'
                    #             ele = foundOption
                    #             break
                    actions.move_to_element(ele).click().perform()
                    if not foundOption: randomly_answered_questions.add((f'{label_org} ]',"radio"))
            else: answer = prev_answer
            _track(label_org+" ]", answer, "radio", prev_answer)
            continue
        
        # Check if it's a text question
        text = try_xp(Question, ".//input[@type='text']", False)
        if text: 
            do_actions = False
            label = try_xp(Question, ".//label[@for]", False)
            try: label = label.find_element(By.CLASS_NAME,'visually-hidden')
            except: pass
            label_org = label.text if label else "Unknown"
            answer = "" # years_of_experience
            label = label_org.lower()

            prev_answer = text.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                if 'experience' in label or 'years' in label: answer = years_of_experience
                elif 'phone' in label or 'mobile' in label: answer = phone_number
                elif 'street' in label: answer = street
                elif 'city' in label or 'location' in label or 'address' in label:
                    answer = current_city if current_city else work_location
                    do_actions = True
                elif 'signature' in label: answer = full_name # 'signature' in label or 'legal name' in label or 'your name' in label or 'full name' in label: answer = full_name     # What if question is 'name of the city or university you attend, name of referral etc?'
                elif 'name' in label:
                    if 'full' in label: answer = full_name
                    elif 'first' in label and 'last' not in label: answer = first_name
                    elif 'middle' in label and 'last' not in label: answer = middle_name
                    elif 'last' in label and 'first' not in label: answer = last_name
                    elif 'employer' in label: answer = recent_employer
                    else: answer = full_name
                elif 'notice' in label:
                    if 'month' in label:
                        answer = notice_period_months
                    elif 'week' in label:
                        answer = notice_period_weeks
                    else: answer = notice_period
                elif 'salary' in label or 'compensation' in label or 'ctc' in label or 'pay' in label: 
                    if 'current' in label or 'present' in label:
                        if 'month' in label:
                            answer = current_ctc_monthly
                        elif 'lakh' in label:
                            answer = current_ctc_lakhs
                        else:
                            answer = current_ctc
                    else:
                        if 'month' in label:
                            answer = desired_salary_monthly
                        elif 'lakh' in label:
                            answer = desired_salary_lakhs
                        else:
                            answer = desired_salary
                elif 'linkedin' in label: answer = linkedIn
                elif 'website' in label or 'blog' in label or 'portfolio' in label or 'link' in label: answer = website
                elif 'scale of 1-10' in label: answer = confidence_level
                elif 'headline' in label: answer = linkedin_headline
                elif ('hear' in label or 'come across' in label) and 'this' in label and ('job' in label or 'position' in label): answer = "https://github.com/GodsScion/Auto_job_applier_linkedIn"
                elif 'state' in label or 'province' in label: answer = state
                elif 'zip' in label or 'postal' in label or 'code' in label: answer = zipcode
                elif 'country' in label: answer = country
                else: answer = answer_common_questions(label,answer)
                if answer == "":
                    ai_answer = ""
                    if use_AI and aiClient:
                        try:
                            ai_answer = answer_question(aiClient, label_org, question_type="text", job_description=job_description, user_information_all=user_information_all)
                        except Exception as e:
                            print_lg("Failed to get AI answer!", e)
                    if ai_answer and isinstance(ai_answer, str) and ai_answer.strip():
                        answer = ai_answer.strip()
                        print_lg(f'AI answered "{label_org}": "{answer}"')
                    else:
                        randomly_answered_questions.add((label_org, "text"))
                        answer = years_of_experience
                text.clear()
                text.send_keys(answer)
                if do_actions:
                    sleep(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.send_keys(Keys.ENTER).perform()
            _track(label, text.get_attribute("value"), "text", prev_answer)
            continue

        # Check if it's a textarea question
        text_area = try_xp(Question, ".//textarea", False)
        if text_area:
            label = try_xp(Question, ".//label[@for]", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = ""
            prev_answer = text_area.get_attribute("value")
            if not prev_answer or overwrite_previous_answers:
                if 'summary' in label: answer = linkedin_summary
                elif 'cover' in label: answer = cover_letter
                if answer == "":
                    ai_answer = ""
                    if use_AI and aiClient:
                        try:
                            ai_answer = answer_question(aiClient, label_org, question_type="textarea", job_description=job_description, user_information_all=user_information_all)
                        except Exception as e:
                            print_lg("Failed to get AI answer!", e)
                    if ai_answer and isinstance(ai_answer, str) and ai_answer.strip():
                        answer = ai_answer.strip()
                        print_lg(f'AI answered "{label_org}": "{answer}"')
                    else:
                        randomly_answered_questions.add((label_org, "textarea"))
            text_area.clear()
            text_area.send_keys(answer)
            if do_actions:
                    sleep(2)
                    actions.send_keys(Keys.ARROW_DOWN)
                    actions.send_keys(Keys.ENTER).perform()
            _track(label, text_area.get_attribute("value"), "textarea", prev_answer)
            continue

        # Check if it's a checkbox question
        checkbox = try_xp(Question, ".//input[@type='checkbox']", False)
        if checkbox:
            label = try_xp(Question, ".//span[@class='visually-hidden']", False)
            label_org = label.text if label else "Unknown"
            label = label_org.lower()
            answer = try_xp(Question, ".//label[@for]", False)  # Sometimes multiple checkboxes are given for 1 question, Not accounted for that yet
            answer = answer.text if answer else "Unknown"
            prev_answer = checkbox.is_selected()
            checked = prev_answer
            if not prev_answer:
                try:
                    actions.move_to_element(checkbox).click().perform()
                    checked = True
                except Exception as e: 
                    print_lg("Checkbox click failed!", e)
                    pass
            _track(f'{label} ([X] {answer})', checked, "checkbox", prev_answer)
            continue


    # Select todays date
    try_xp(driver, "//button[contains(@aria-label, 'This is today')]")

    # Collect important skills
    # if 'do you have' in label and 'experience' in label and ' in ' in label -> Get word (skill) after ' in ' from label
    # if 'how many years of experience do you have in ' in label -> Get word (skill) after ' in '

    return questions_list




def external_apply(pagination_element: WebElement, job_id: str, job_link: str, resume: str, date_listed, application_link: str, screenshot_name: str, ai_client=None, job_description: str = "") -> tuple[bool, str, int, bool]:
    '''
    Function to open new tab and save external job application links.

    With `fill_external_forms` enabled it also fills the external form with
    static + AI answers and lets the user review before finishing. Returns
    (skip, application_link, tabs_count, submitted_by_user).
    '''
    global tabs_count, dailyEasyApplyLimitReached, external_application_submitted
    external_application_submitted = False
    events.emit("EXTERNAL_APPLY_STARTED", job_id=job_id, title="", fallback=easy_apply_only and not fill_external_forms)
    if easy_apply_only and not fill_external_forms:
        try:
            if "exceeded the daily application limit" in driver.find_element(By.CLASS_NAME, "artdeco-inline-feedback__message").text: dailyEasyApplyLimitReached = True
        except: pass
        print_lg("Easy apply failed I guess!")
        if pagination_element != None: return True, application_link, tabs_count, False
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, ".//button[contains(@class,'jobs-apply-button') and contains(@class, 'artdeco-button--3')]"))).click() # './/button[contains(span, "Apply") and not(span[contains(@class, "disabled")])]'
        wait_span_click(driver, "Continue", 1, True, False)
        windows = driver.window_handles
        tabs_count = len(windows)
        driver.switch_to.window(windows[-1])
        application_link = driver.current_url
        print_lg('Got the external application link "{}"'.format(application_link))
        if easy_apply_only and fill_external_forms:
            print_lg("Filling the external application form (static + AI answers)...")
            fill_external_form(driver, ai_client=ai_client, job_description=job_description)
            if pause_before_submit and not run_in_background:
                decision = pyautogui.confirm(
                    'The bot filled the application form on the external site.\n'
                    '1. REVIEW every answer now.\n'
                    '2. If anything looks wrong, edit it on the page directly.\n'
                    '3. Submit the form yourself if it looks right.\n\n'
                    'The application link is saved either way.',
                    "Confirm external application",
                    ["I submitted it", "Leave it open, save link", "Discard application"],
                )
                if decision == "Discard application":
                    raise Exception("External application discarded by user!")
                external_application_submitted = decision == "I submitted it"
        if close_tabs and driver.current_window_handle != linkedIn_tab: driver.close()
        driver.switch_to.window(linkedIn_tab)
        return False, application_link, tabs_count, external_application_submitted
    except Exception as e:
        # print_lg(e)
        print_lg("Failed to apply!")
        events.emit("FAILURE", job_id=job_id, title="", stage="external_apply", error=str(e)[:300])
        failed_job(job_id, job_link, resume, date_listed, "Probably didn't find Apply button or unable to switch tabs.", e, application_link, screenshot_name)
        global failed_count
        failed_count += 1
        return True, application_link, tabs_count, False



def follow_company(modal: WebDriver = driver) -> None:
    '''
    Function to follow or un-follow easy applied companies based om `follow_companies`
    '''
    try:
        follow_checkbox_input = try_xp(modal, ".//input[@id='follow-company-checkbox' and @type='checkbox']", False)
        if follow_checkbox_input and follow_checkbox_input.is_selected() != follow_companies:
            try_xp(modal, ".//label[@for='follow-company-checkbox']")
    except Exception as e:
        print_lg("Failed to update follow companies checkbox!", e)
    


#< Failed attempts logging
def failed_job(job_id: str, job_link: str, resume: str, date_listed, error: str, exception: Exception, application_link: str, screenshot_name: str) -> None:
    '''
    Function to update failed jobs list in excel
    '''
    try:
        with open(failed_file_name, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['Job ID', 'Job Link', 'Resume Tried', 'Date listed', 'Date Tried', 'Assumed Reason', 'Stack Trace', 'External Job link', 'Screenshot Name']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Job Link': job_link, 'Resume Tried': resume,
                'Date listed': date_listed, 'Date Tried': datetime.now(),
                'Assumed Reason': error, 'Stack Trace': exception,
                'External Job link': application_link, 'Screenshot Name': screenshot_name,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
            file.close()
    except Exception as e:
        print_lg("Failed to update failed jobs list!", e)
        pyautogui.alert("Failed to update the excel of failed jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")


def screenshot(driver: WebDriver, job_id: str, failedAt: str) -> str:
    '''
    Function to to take screenshot for debugging
    - Returns screenshot name as String
    '''
    screenshot_name = "{} - {} - {}.png".format( job_id, failedAt, str(datetime.now()) )
    path = logs_folder_path+"/screenshots/"+screenshot_name.replace(":",".")
    # special_chars = {'*', '"', '\\', '<', '>', ':', '|', '?'}
    # for char in special_chars:  path = path.replace(char, '-')
    driver.save_screenshot(path.replace("//","/"))
    return screenshot_name
#>



def submitted_jobs(job_id: str, title: str, company: str, work_location: str, work_style: str, description: str, experience_required: int | Literal['Unknown', 'Error in extraction'], 
                   skills: list[str] | Literal['In Development'], hr_name: str | Literal['Unknown'], hr_link: str | Literal['Unknown'], resume: str, 
                   reposted: bool, date_listed: datetime | Literal['Unknown'], date_applied:  datetime | Literal['Pending'], job_link: str, application_link: str, 
                   questions_list: set | None, connect_request: Literal['In Development']) -> None:
    '''
    Function to create or update the Applied jobs CSV file, once the application is submitted successfully
    '''
    try:
        with open(file_name, mode='a', newline='', encoding='utf-8') as csv_file:
            fieldnames = ['Job ID', 'Title', 'Company', 'Work Location', 'Work Style', 'About Job', 'Experience required', 'Skills required', 'HR Name', 'HR Link', 'Resume', 'Re-posted', 'Date Posted', 'Date Applied', 'Job Link', 'External Job link', 'Questions Found', 'Connect Request']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            if csv_file.tell() == 0: writer.writeheader()
            record = {
                'Job ID': job_id, 'Title': title, 'Company': company, 'Work Location': work_location,
                'Work Style': work_style, 'About Job': description, 'Experience required': experience_required,
                'Skills required': skills, 'HR Name': hr_name, 'HR Link': hr_link, 'Resume': resume,
                'Re-posted': reposted, 'Date Posted': date_listed, 'Date Applied': date_applied,
                'Job Link': job_link, 'External Job link': application_link,
                'Questions Found': questions_list, 'Connect Request': connect_request,
            }
            writer.writerow({key: truncate_for_csv(value) for key, value in record.items()})
        csv_file.close()
    except Exception as e:
        print_lg("Failed to update submitted jobs list!", e)
        pyautogui.alert("Failed to update the excel of applied jobs!\nProbably because of 1 of the following reasons:\n1. The file is currently open or in use by another program\n2. Permission denied to write to the file\n3. Failed to find the file", "Failed Logging")



# Function to discard the job application
def discard_job() -> None:
    actions.send_keys(Keys.ESCAPE).perform()
    wait_span_click(driver, 'Discard', 2)






# Function to apply to jobs
def apply_to_jobs(search_terms: list[str]) -> None:
    applied_jobs = get_applied_job_ids()
    rejected_jobs = set()
    blacklisted_companies = set()
    global current_city, failed_count, skip_count, easy_applied_count, external_jobs_count, tabs_count, pause_before_submit, pause_at_failed_question, useNewResume
    current_city = current_city.strip()

    if randomize_search_order:  shuffle(search_terms)
    locations = [s.strip() for s in search_location.split(",") if s.strip()] or [""]
    search_runs = [(term, location) for term in search_terms for location in locations]
    dry_done = 0
    for searchTerm, location in search_runs:
        URL = f"https://www.linkedin.com/jobs/search/?keywords={quote(searchTerm)}"
        if location:
            URL += f"&location={quote(location)}"
        driver.get(URL)
        print_lg("\n________________________________________________________________________________________________________________________\n")
        print_lg(f'\n>>>> Now searching for "{searchTerm}"  |  Location: "{location if location else "LinkedIn default"}" <<<<\n\n')

        filters_ok = True
        try:
            filters_ok = apply_filters(location)
        except Exception as filter_error:
            print_lg("Filter stage raised unexpectedly; continuing on the location-scoped URL.", filter_error)
            filters_ok = False
        if not filters_ok:
            print_lg(f'Re-loading location-scoped results for "{location if location else "LinkedIn default"}" after filter failure.')
            driver.get(URL)
            buffer(2)

        current_count = 0
        try:
            while current_count < switch_number:
                # Wait until job listings are loaded
                wait.until(EC.presence_of_all_elements_located((By.XPATH, "//li[@data-occludable-job-id]")))

                pagination_element, current_page = get_page_info()

                # Find all job listings in current page
                buffer(3)
                job_listings = driver.find_elements(By.XPATH, "//li[@data-occludable-job-id]")  

            
                for job in job_listings:
                    if keep_screen_awake: pyautogui.press('shiftright')
                    if is_dry_run() and dry_done >= dry_run.DRY_MAX_JOBS:
                        print_lg(f"[DRY RUN] Reached rehearsal cap of {dry_run.DRY_MAX_JOBS} jobs.")
                        current_count = switch_number
                        break
                    if current_count >= switch_number: break
                    print_lg("\n-@-\n")

                    job_id,title,company,work_location,work_style,skip = get_job_main_details(job, blacklisted_companies, rejected_jobs)
                    
                    if skip: continue
                    events.emit("JOB_OPENED", job_id=job_id, title=title, company=company, work_location=work_location)

                    # Stop applying once the Free plan daily limit is reached (hard stop + upsell).
                    if not can_submit():
                        show_upsell()
                        return
                    # Redundant fail safe check for applied jobs!
                    try:
                        if job_id in applied_jobs or find_by_class(driver, "jobs-s-apply__application-link", 2):
                            print_lg(f'Already applied to "{title} | {company}" job. Job ID: {job_id}!')
                            continue
                    except Exception as e:
                        print_lg(f'Trying to Apply to "{title} | {company}" job. Job ID: {job_id}')

                    job_link = "https://www.linkedin.com/jobs/view/"+job_id
                    application_link = "Easy Applied"
                    date_applied = "Pending"
                    hr_link = "Unknown"
                    hr_name = "Unknown"
                    connect_request = "In Development" # Still in development
                    date_listed = "Unknown"
                    skills = "Needs an AI" # Still in development
                    resume = "Pending"
                    reposted = False
                    questions_list = None
                    screenshot_name = "Not Available"

                    try:
                        rejected_jobs, blacklisted_companies, jobs_top_card = check_blacklist(rejected_jobs,job_id,company,blacklisted_companies)
                    except ValueError as e:
                        print_lg(e, 'Skipping this job!\n')
                        events.emit("SKIPPED", job_id=job_id, reason="blacklisted_company")
                        failed_job(job_id, job_link, resume, date_listed, "Found Blacklisted words in About Company", e, "Skipped", screenshot_name)
                        skip_count += 1
                        continue
                    except Exception as e:
                        print_lg("Failed to scroll to About Company!")
                        # print_lg(e)



                    # Hiring Manager info
                    try:
                        hr_info_card = WebDriverWait(driver,2).until(EC.presence_of_element_located((By.CLASS_NAME, "hirer-card__hirer-information")))
                        hr_link = hr_info_card.find_element(By.TAG_NAME, "a").get_attribute("href")
                        hr_name = hr_info_card.find_element(By.TAG_NAME, "span").text
                        # if connect_hr:
                        #     driver.switch_to.new_window('tab')
                        #     driver.get(hr_link)
                        #     wait_span_click("More")
                        #     wait_span_click("Connect")
                        #     wait_span_click("Add a note")
                        #     message_box = driver.find_element(By.XPATH, "//textarea")
                        #     message_box.send_keys(connect_request_message)
                        #     if close_tabs: driver.close()
                        #     driver.switch_to.window(linkedIn_tab) 
                        # def message_hr(hr_info_card):
                        #     if not hr_info_card: return False
                        #     hr_info_card.find_element(By.XPATH, ".//span[normalize-space()='Message']").click()
                        #     message_box = driver.find_element(By.XPATH, "//div[@aria-label='Write a message…']")
                        #     message_box.send_keys()
                        #     try_xp(driver, "//button[normalize-space()='Send']")        
                    except Exception as e:
                        print_lg(f'HR info was not given for "{title}" with Job ID: {job_id}!')
                        # print_lg(e)


                    # Calculation of date posted
                    try:
                        # try: time_posted_text = find_by_class(driver, "jobs-unified-top-card__posted-date", 2).text
                        # except: 
                        time_posted_text = jobs_top_card.find_element(By.XPATH, './/span[contains(normalize-space(), " ago")]').text
                        print("Time Posted: " + time_posted_text)
                        if time_posted_text.__contains__("Reposted"):
                            reposted = True
                            time_posted_text = time_posted_text.replace("Reposted", "")
                        date_listed = calculate_date_posted(time_posted_text.strip())
                    except Exception as e:
                        print_lg("Failed to calculate the date posted!",e)


                    description, experience_required, skip, reason, message = get_job_description()
                    if isinstance(experience_required, int):
                        events.emit("EXPERIENCE_CHECK", job_id=job_id, required=experience_required, candidate=current_experience)
                    else:
                        events.emit("EXPERIENCE_UNKNOWN", job_id=job_id, required=experience_required, decision="pass")
                    if skip:
                        print_lg(message)
                        events.emit("SKIPPED", job_id=job_id, reason=reason or "experience_gate")
                        failed_job(job_id, job_link, resume, date_listed, reason, message, "Skipped", screenshot_name)
                        rejected_jobs.add(job_id)
                        skip_count += 1
                        continue

                    
                    if use_AI and description != "Unknown":
                        try:
                            skills = extract_skills(aiClient, description)
                            print_lg(f"Extracted skills using {ai_provider} AI")
                        except Exception as e:
                            print_lg("Failed to extract skills:", e)
                            skills = "Error extracting skills"

                    uploaded = False
                    # Detect whether this is an Easy Apply job and open its modal (if any).
                    # Click the apply button; a brand-new browser tab means external application,
                    # while an Easy Apply modal means a job we can automate.
                    is_easy_apply = False
                    apply_button = try_xp(driver, ".//button[contains(@class,'jobs-apply-button')]", click=False)
                    if apply_button:
                        events.emit("APPLY_BUTTON_FOUND", job_id=job_id, title=title)
                    else:
                        events.emit("APPLY_BUTTON_NOT_FOUND", job_id=job_id, title=title)
                    if apply_button:
                        try:
                            tabs_open = len(driver.window_handles)
                            robust_click(apply_button, "Easy Apply button", resolver=lambda: try_xp(driver, ".//button[contains(@class,'jobs-apply-button')]", click=False))
                            events.emit("APPLY_BUTTON_CLICKED", job_id=job_id, title=title)
                            buffer(click_gap)
                            if len(driver.window_handles) > tabs_open:
                                # A new tab opened -> external apply. Close it and return to LinkedIn.
                                events.emit("NEW_TAB_OPENED", job_id=job_id, title=title, outcome="external")
                                driver.switch_to.window(driver.window_handles[-1])
                                if close_tabs and driver.current_window_handle != linkedIn_tab:
                                    driver.close()
                                driver.switch_to.window(linkedIn_tab)
                                print_lg("A new tab opened - external application, skipping.")
                            else:
                                try:
                                    WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CLASS_NAME, "jobs-easy-apply-modal")))
                                    is_easy_apply = True
                                    events.emit("EASY_APPLY_MODAL_DETECTED", job_id=job_id, title=title)
                                    print_lg("Easy Apply detected from the modal that opened.")
                                except Exception:
                                    events.emit("EASY_APPLY_MODAL_TIMEOUT", job_id=job_id, title=title)
                                    # No modal appeared; make sure nothing is left overlaying the page.
                                    try: actions.send_keys(Keys.ESCAPE).perform()
                                    except Exception: pass
                                    sleep(1)
                                    try:
                                        dismiss_buttons = driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Dismiss'], button[aria-label*='Close']")
                                        if dismiss_buttons and dismiss_buttons[0].is_displayed():
                                            dismiss_buttons[0].click()
                                    except Exception:
                                        pass
                        except Exception as e:
                            events.emit("FAILURE", job_id=job_id, title=title, stage="apply_click", error=str(e)[:300])
                    if not is_easy_apply:
                        # Check 2: an apply link carrying LinkedIn's in-app apply URL flag.
                        try:
                            in_app_apply = driver.find_element(By.XPATH, ".//a[contains(@href, 'openSDUIApplyFlow=true')]")
                            if in_app_apply:
                                events.emit("IN_APP_APPLY_LINK_FOUND", job_id=job_id, title=title)
                                robust_click(in_app_apply, "in-app apply link", resolver=lambda: driver.find_element(By.XPATH, ".//a[contains(@href, 'openSDUIApplyFlow=true')]"))
                                events.emit("IN_APP_APPLY_LINK_CLICKED", job_id=job_id, title=title)
                                buffer(click_gap)
                                if driver.find_elements(By.CLASS_NAME, "jobs-easy-apply-modal"):
                                    is_easy_apply = True
                                    events.emit("EASY_APPLY_MODAL_DETECTED", job_id=job_id, title=title, via="in_app_link")
                                    print_lg("Easy Apply detected from the in-app apply URL flag.")
                        except Exception:
                            pass
                    if is_easy_apply:
                        events.emit("EASY_APPLY_OPENED", job_id=job_id, title=title, company=company)
                        if is_dry_run():
                            dry_done += 1
                            dry_run.count("easy_apply")
                            print_lg("[DRY RUN] Easy Apply job detected. Rehearsing the modal - will NOT submit.")
                            try:
                                modal = find_by_class(driver, "jobs-easy-apply-modal")
                                rehearsed = answer_questions(modal, set(), work_location, job_description=description)
                                if rehearsed:
                                    print_lg("[DRY RUN] Would answer:", rehearsed)
                            except Exception as e:
                                print_lg("[DRY RUN] Easy Apply rehearsal skipped:", e)
                            discard_job()
                            continue
                        try: 
                            try:
                                errored = ""
                                modal: WebElement | None = find_by_class(driver, "jobs-easy-apply-modal")
                                wait_span_click(modal, "Next", 1)
                                # if description != "Unknown":
                                #     resume = create_custom_resume(description)
                                resume = "Previous resume"
                                next_button = True
                                questions_list = set()
                                next_counter = 0
                                while next_button:
                                    next_counter += 1
                                    if next_counter >= 15: 
                                        if pause_at_failed_question:
                                            screenshot(driver, job_id, "Needed manual intervention for failed question")
                                            pyautogui.alert("Couldn't answer one or more questions.\nPlease click \"Continue\" once done.\nDO NOT CLICK Back, Next or Review button in LinkedIn.\n\n\n\n\nYou can turn off \"Pause at failed question\" setting in config.py", "Help Needed", "Continue")
                                            next_counter = 1
                                            continue
                                        if questions_list: print_lg("Stuck for one or some of the following questions...", questions_list)
                                        screenshot_name = screenshot(driver, job_id, "Failed at questions")
                                        errored = "stuck"
                                        raise Exception("Seems like stuck in a continuous loop of next, probably because of new questions.")
                                    questions_list = answer_questions(modal, questions_list, work_location, job_description=description)
                                    if useNewResume and not uploaded: uploaded, resume = upload_resume(modal, default_resume_path)
                                    try: next_button = modal.find_element(By.XPATH, './/span[normalize-space(.)="Review"]') 
                                    except NoSuchElementException:  next_button = modal.find_element(By.XPATH, './/button[contains(span, "Next")]')
                                    events.emit("NEXT_CLICKED", job_id=job_id, title=title)
                                    try: next_button.click()
                                    except ElementClickInterceptedException: break    # Happens when it tries to click Next button in About Company photos section
                                    buffer(click_gap)

                            except Exception as e: errored = "nose"
                            finally:
                                if questions_list and errored != "stuck": 
                                    print_lg("Answered the following questions...", questions_list)
                                    print("\n\n" + "\n".join(str(question) for question in questions_list) + "\n\n")
                                events.emit("REVIEW_REACHED", job_id=job_id, title=title)
                                wait_span_click(driver, "Review", 1, scrollTop=True)
                                events.emit("REVIEW_CLICKED", job_id=job_id, title=title)
                                cur_pause_before_submit = pause_before_submit
                                if errored != "stuck" and cur_pause_before_submit:
                                    decision = pyautogui.confirm('1. Please verify your information.\n2. If you edited something, please return to this final screen.\n3. DO NOT CLICK "Submit Application".\n\n\n\n\nYou can turn off "Pause before submit" setting in config.py\nTo TEMPORARILY disable pausing, click "Disable Pause"', "Confirm your information",["Disable Pause", "Discard Application", "Submit Application"])
                                    if decision == "Discard Application": raise Exception("Job application discarded by user!")
                                    pause_before_submit = False if "Disable Pause" == decision else True
                                    # try_xp(modal, ".//span[normalize-space(.)='Review']")
                                if modal: follow_company(modal)
                                events.emit("SUBMIT_ATTEMPTED", job_id=job_id, title=title, job_link=job_link)
                                if wait_span_click(driver, "Submit application", 2, scrollTop=True): 
                                    date_applied = datetime.now()
                                    events.emit("SUBMIT_SUCCESS", job_id=job_id, title=title, job_link=job_link)
                                    if not wait_span_click(driver, "Done", 2): actions.send_keys(Keys.ESCAPE).perform()
                                elif errored != "stuck" and cur_pause_before_submit and "Yes" in pyautogui.confirm("You submitted the application, didn't you 😒?", "Failed to find Submit Application!", ["Yes", "No"]):
                                    date_applied = datetime.now()
                                    events.emit("SUBMIT_SUCCESS", job_id=job_id, title=title, job_link=job_link)
                                    wait_span_click(driver, "Done", 2)
                                else:
                                    print_lg("Since, Submit Application failed, discarding the job application...")
                                    events.emit("SUBMIT_NOT_FOUND", job_id=job_id, title=title)
                                    # if screenshot_name == "Not Available":  screenshot_name = screenshot(driver, job_id, "Failed to click Submit application")
                                    # else:   screenshot_name = [screenshot_name, screenshot(driver, job_id, "Failed to click Submit application")]
                                    if errored == "nose": raise Exception("Failed to click Submit application 😑")


                        except Exception as e:
                            print_lg("Failed to Easy apply!")
                            events.emit("FAILURE", job_id=job_id, title=title, stage="easy_apply", error=str(e)[:300])
                            # print_lg(e)
                            critical_error_log("Somewhere in Easy Apply process",e)
                            failed_job(job_id, job_link, resume, date_listed, "Problem in Easy Applying", e, application_link, screenshot_name)
                            failed_count += 1
                            discard_job()
                            continue
                    else:
                        if is_dry_run():
                            dry_done += 1
                            dry_run.count("external")
                            print_lg("[DRY RUN] External application detected - not opening external site in dry-run.")
                            continue
                        # Case 2: Apply externally
                        skip, application_link, tabs_count, external_submitted = external_apply(pagination_element, job_id, job_link, resume, date_listed, application_link, screenshot_name, ai_client=(aiClient if use_AI else None), job_description=(description if isinstance(description, str) else ""))
                        if external_submitted: date_applied = datetime.now()
                        if dailyEasyApplyLimitReached:
                            print_lg("\n###############  Daily application limit for Easy Apply is reached!  ###############\n")
                            return
                        if skip: continue

                    submitted_jobs(job_id, title, company, work_location, work_style, description, experience_required, skills, hr_name, hr_link, resume, reposted, date_listed, date_applied, job_link, application_link, questions_list, connect_request)
                    if uploaded:   useNewResume = False

                    # Count a real submission toward the Free plan daily usage.
                    if date_applied != "Pending":
                        used = record_application()
                        print_lg(f"LICENSE: {used}/{free_daily_limit} Free plan applications used today" if not is_paid() else f"LICENSE: Unlimited plan - {used} applications sent today")

                    print_lg(f'Successfully saved "{title} | {company}" job. Job ID: {job_id} info')
                    current_count += 1
                    if application_link == "Easy Applied": easy_applied_count += 1
                    else:   external_jobs_count += 1
                    applied_jobs.add(job_id)



                # Switching to next page
                if pagination_element == None:
                    print_lg("Couldn't find pagination element, probably at the end page of results!")
                    break
                try:
                    pagination_element.find_element(By.XPATH, f"//button[@aria-label='Page {current_page+1}']").click()
                    print_lg(f"\n>-> Now on Page {current_page+1} \n")
                except NoSuchElementException:
                    print_lg(f"\n>-> Didn't find Page {current_page+1}. Probably at the end page of results!\n")
                    break

            if is_dry_run() and dry_done >= dry_run.DRY_MAX_JOBS:
                print_lg(f"[DRY RUN] Reached rehearsal cap of {dry_run.DRY_MAX_JOBS}; stopping the application rehearsal.")
                break

        except (NoSuchWindowException, WebDriverException) as e:
            print_lg("The browser window was closed or the session became invalid. Stopping.", e)
            raise e  # let the outer handler deal with it
        except Exception as e:
            print_lg("Could not process this search location; moving on to the next one.", e)
            critical_error_log("In Applier", e)
            continue

        
# ===========================================================================
# Referral finder (find jobs where the user has LinkedIn connections)
# ---------------------------------------------------------------------------
# LinkedIn shows a "N connections work here" badge on job-search result cards.
# We collect those jobs so the user can draft a referral message to someone at
# that company. Connection NAMES are a LinkedIn Premium feature and are NOT
# requested here - only the company + count the free UI already exposes.
# ===========================================================================
REFERRAL_RESULTS_PATH = os.path.join(os.getcwd(), "referral_results.json")


def _parse_referral_card(job) -> dict | None:
    '''
    Best-effort parse of one job-search result card that carries a
    "N connections work here" badge. Returns {job_id, title, company,
    location, work_style, connection_count, link} or None if unparseable.
    '''
    try:
        job_id = job.get_dom_attribute("data-occludable-job-id") or ""
        if not job_id:
            return None
        text = job.text
    except Exception:
        return None
    match = re.search(r"(\d+)\s+connections?\s+work here", text, re.IGNORECASE)
    if not match:
        return None
    count = int(match.group(1))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    title = lines[0] if lines else "Unknown"
    company, location, work_style = "Unknown", "", ""
    try:
        subtitle = job.find_element(By.CLASS_NAME, "artdeco-entity-lockup__subtitle").text
        if " · " in subtitle:
            company = subtitle.split(" · ")[0].strip()
            location = subtitle.split(" · ", 1)[1].strip()
    except Exception:
        pass
    if company == "Unknown":
        # No subtitle lockup: company is usually the 3rd non-empty line.
        if len(lines) >= 3:
            company = lines[2]
    style_match = re.search(r"\((Remote|On-site|Hybrid)\)", location, re.IGNORECASE)
    if style_match:
        work_style = style_match.group(1)
        location = location[:style_match.start()].strip().rstrip(" ·")
    else:
        bare_style = re.match(r"^(Remote|On-site|Hybrid)$", location, re.IGNORECASE)
        if bare_style:
            work_style = bare_style.group(1)
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "work_style": work_style,
        "connection_count": count,
        "link": "https://www.linkedin.com/jobs/view/" + job_id,
    }


def find_referral_jobs(max_pages: int = 6) -> None:
    '''
    Search every configured term/location and record result cards that carry a
    "N connections work here" badge, writing them to referral_results.json so the
    control panel can display them. Runs in the already-open LinkedIn session.
    '''
    found: list[dict] = []
    seen: set[str] = set()
    locations = [s.strip() for s in search_location.split(",") if s.strip()] or [""]
    search_runs = [(term, loc) for term in search_terms for loc in locations]

    if not search_terms:
        print_lg("Referral finder: no search terms configured; nothing to do.")
        _write_referral_results(found)
        return

    print_lg("\n########  REFERRAL FINDER  ########")
    print_lg("Scanning your searches for jobs where you have LinkedIn connections...")
    print_lg("(Only counts are read - connection names are a LinkedIn Premium feature.)")
    events.emit("REFERRAL_SCAN_STARTED", terms=search_terms, locations=locations)

    for term, location in search_runs:
        url = f"https://www.linkedin.com/jobs/search/?keywords={quote(term)}"
        if location:
            url += f"&location={quote(location)}"
        try:
            driver.get(url)
            buffer(3)
        except Exception as e:
            print_lg(f"Referral finder: couldn't load search for '{term}'", e)
            continue

        # Apply LinkedIn's date/sort filters for a cleaner, consistent result set.
        try:
            apply_filters(location)
        except Exception as e:
            print_lg("Referral finder: filter stage failed; continuing anyway.", e)

        page = 0
        while page < max_pages:
            try:
                wait.until(EC.presence_of_all_elements_located((By.XPATH, "//li[@data-occludable-job-id]")))
            except Exception:
                break
            buffer(2)
            for job in driver.find_elements(By.XPATH, "//li[@data-occludable-job-id]"):
                entry = _parse_referral_card(job)
                if not entry:
                    continue
                if entry["job_id"] in seen:
                    continue
                seen.add(entry["job_id"])
                found.append(entry)
                print_lg(f"  {entry['connection_count']} connection(s) at {entry['company']}: {entry['title']} ({entry['link']})")
                events.emit("REFERRAL_CANDIDATE", job_id=entry.get("job_id"), company=entry.get("company"), title=entry.get("title"), connections=entry.get("connection_count"))

            # Advance to the next page of results.
            pagination_element, current_page = get_page_info()
            if pagination_element is None or current_page is None:
                break
            page += 1
            if page >= max_pages:
                break
            try:
                pagination_element.find_element(By.XPATH, f"//button[@aria-label='Page {current_page+1}']").click()
                buffer(2)
            except Exception:
                break

    found.sort(key=lambda e: e["connection_count"], reverse=True)
    print_lg(f"\nReferral finder complete: {len(found)} job(s) where you have connections.")
    _write_referral_results(found)


def _write_referral_results(results: list[dict]) -> None:
    '''Persist referral results to referral_results.json with a timestamp.'''
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(results),
        "results": results,
    }
    try:
        with open(REFERRAL_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print_lg(f"Referral results written to {REFERRAL_RESULTS_PATH}")
    except Exception as e:
        print_lg("Referral finder: could not write results file.", e)


def _load_referral_results() -> list[dict]:
    '''Load referral results from referral_results.json.'''
    if not os.path.isfile(REFERRAL_RESULTS_PATH):
        print_lg("No referral_results.json found. Run --referral first.")
        return []
    with open(REFERRAL_RESULTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results", [])


def _enrich_referral_hr_info(results: list[dict], max_jobs: int = 15) -> list[dict]:
    '''
    Visit each referral job's page to extract HR name and profile link
    from the hirer card. Updates the result dicts in-place.
    '''
    print_lg(f"\nEnriching {min(len(results), max_jobs)} referral jobs with HR info...")
    for i, job in enumerate(results[:max_jobs]):
        job_url = job.get("link", "")
        if not job_url:
            continue
        try:
            driver.get(job_url)
            buffer(3)
            hr_name = "Unknown"
            hr_link = ""
            try:
                hr_card = WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "hirer-card__hirer-information"))
                )
                hr_link = hr_card.find_element(By.TAG_NAME, "a").get_attribute("href")
                hr_name = hr_card.find_element(By.TAG_NAME, "span").text
            except Exception:
                pass
            job["hr_name"] = hr_name
            job["hr_link"] = hr_link
            status = f"HR: {hr_name}" if hr_name != "Unknown" else "No HR info found"
            print_lg(f"  [{i+1}] {job.get('company', '?')} — {status}")
        except Exception as e:
            print_lg(f"  [{i+1}] Failed to visit {job_url}: {e}")
            job["hr_name"] = "Unknown"
            job["hr_link"] = ""
        buffer(2)

    # Re-write results with HR info
    _write_referral_results(results)
    return results


def run(total_runs: int) -> int:
    if dailyEasyApplyLimitReached:
        return total_runs
    print_lg("\n########################################################################################################################\n")
    print_lg(f"Date and Time: {datetime.now()}")
    print_lg(f"Cycle number: {total_runs}")
    print_lg(f"Currently looking for jobs posted within '{date_posted}' and sorting them by '{sort_by}'")
    apply_to_jobs(search_terms)
    print_lg("########################################################################################################################\n")
    if not dailyEasyApplyLimitReached:
        if not is_paid() and applications_today() >= free_daily_limit:
            print_lg("\n###############  Free plan daily limit reached - application stopped until tomorrow.  ###############\n")
            return total_runs + 1
        print_lg("Sleeping for 10 min...")
        sleep(300)
        print_lg("Few more min... Gonna start with in next 5 min...")
        sleep(300)
    buffer(3)
    return total_runs + 1



chatGPT_tab = False
linkedIn_tab = False

def main() -> None:
    # Run-level event stream (see modules.events). Each process is a fresh run.
    events.reset_run_id()
    events.emit("RUN_STARTED", mode=sys.argv[1:])
    print_lg("Starting Auto Job Applier... Please consider sponsoring the project at https://github.com/sponsors/GodsScion")
    if is_dry_run():
        print_lg("[DRY RUN] Rehearsal mode: exercising real code paths. No application will be submitted and no referral message will be sent.")
    total_runs = 1
    try:
        global linkedIn_tab, tabs_count, useNewResume, aiClient
        alert_title = "Error Occurred. Closing Browser!"
        validate_config()

        # First-run guard (desktop parity with the web "/setup" onboarding): if
        # there is no saved config at all, running now would only launch the
        # browser with blank details. Point the user at the one-time setup instead
        # of letting the run limp along. Dry-run / smoke / review modes are exempt.
        if not _has_any_setup():
            mode_args = [a for a in sys.argv[1:] if a.startswith('-')]
            if not is_dry_run() and not set(mode_args).intersection(
                    {'--referral', '--send-referrals', '--send-personalized', '--smoke', '--setup'}):
                print("")
                print("*" * 70)
                print("  You haven't finished your one-time setup yet.")
                print("  The bot needs your resume and preferences before it runs.")
                print("")
                print("  On this computer, run the setup first:")
                print("    - Windows: double-click 'Setup App.bat'  (or run 'python setup_app.py --setup')")
                print("    - macOS/Linux: run './start.command' and the browser will guide you")
                print("")
                print("  Then start the bot again.")
                print("*" * 70)
                return

        # Licensing status banner
        if is_paid():
            print_lg("LICENSE: Unlimited plan (license key activated)")
        else:
            print_lg(f"LICENSE: Free plan - up to {free_daily_limit} applications per day ({applications_today()} used today)")
            print_lg(f"LICENSE: Referral scans - {referral_scans_today()}/{1} used today | Messages - {referral_messages_today()}/{3} used today")
        
        if not os.path.exists(default_resume_path):
            print_lg('Notice: Default resume "{}" is not present on disk. The bot will continue using your previously uploaded resume in LinkedIn.'.format(default_resume_path))
            useNewResume = False
        
        # Login to LinkedIn
        tabs_count = len(driver.window_handles)
        driver.get("https://www.linkedin.com/login")
        if not is_logged_in_LN(): login_LN()
        
        linkedIn_tab = driver.current_window_handle

        # One-click referral flow: scan AND send in the same authenticated session.
        combined = "--referral" in sys.argv and "--send-referrals" in sys.argv

        # Referral mode: find jobs where the user has connections, then stop
        # (unless --send-referrals is also set, in which case we continue to send
        # within the SAME authenticated session - the "one-click" referral flow).
        if "--referral" in sys.argv:
            print_lg("Referral mode detected.")
            if not can_scan_referral():
                show_referral_upsell("scan")
                return
            # Count the attempt BEFORE running so a crashed/killed scan still
            # consumes today's allowance (prevents endless re-runs).
            if not is_dry_run():
                record_referral_scan()
            try:
                find_referral_jobs()
            except Exception as e:
                critical_error_log("In Referral Finder", e)
            if not combined:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
                return

        # Send-referrals mode: resolve connection names and send messages via LinkedIn DM + Gmail.
        if "--send-referrals" in sys.argv:
            print_lg("Send-referrals mode detected.")
            if not can_send_referral():
                show_referral_upsell("message")
                return
            try:
                from modules.helpers import manual_login_retry

                # Session probe is module-level so it can be unit-tested. See
                # _real_session_ready(): it avoids a forced /feed/ navigation
                # (which triggers LinkedIn challenges and falsely reads as
                # "not logged in"), preferring the li_at cookie and the
                # current page's signed-in markers first.
                print_lg("Ensuring an authenticated LinkedIn session before sending referral messages...")
                if _real_session_ready(driver):
                    print_lg("Already signed in - reusing your LinkedIn session.")
                else:
                    print_lg("Not signed in yet. Attempting login...")
                    login_LN()
                    if not _real_session_ready(driver):
                        print_lg("Automated login did not produce a usable session. Please log in manually in the browser.")
                        manual_login_retry(lambda: _real_session_ready(driver), limit=180)
                print_lg("Authenticated LinkedIn session confirmed.")

                results = _load_referral_results()
                if results:
                    from modules.referral_messaging import send_referral_messages
                    send_referral_messages(driver, results)
            except Exception as e:
                critical_error_log("In Referral Messaging", e)
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
            return

        # Curated personalized-DM mode: message a hand-picked list of people
        # (referral_targets.json). Profile-scrapes each person and asks the AI
        # client (when configured) for a hyper-personalized message, falling
        # back to the programmatic template otherwise.
        if "--send-personalized" in sys.argv:
            print_lg("Send-personalized mode detected.")
            if not can_send_referral():
                show_referral_upsell("message")
                return
            try:
                from modules.helpers import manual_login_retry

                print_lg("Ensuring an authenticated LinkedIn session before sending personalized messages...")
                if _real_session_ready(driver):
                    print_lg("Already signed in - reusing your LinkedIn session.")
                else:
                    print_lg("Not signed in yet. Attempting login...")
                    login_LN()
                    if not _real_session_ready(driver):
                        print_lg("Automated login did not produce a usable session. Please log in manually in the browser.")
                        manual_login_retry(lambda: _real_session_ready(driver), limit=180)
                print_lg("Authenticated LinkedIn session confirmed.")

                from modules.ai.connections import create_ai_client
                ai_client = create_ai_client()
                from modules.referral_personalized import send_personalized_messages
                send_personalized_messages(driver, client=ai_client)
            except Exception as e:
                critical_error_log("In Personalized Referral Messaging", e)
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
            return

        # # Login to ChatGPT in a new tab for resume customization
        # if use_resume_generator:
        #     try:
        #         driver.switch_to.new_window('tab')
        #         driver.get("https://chat.openai.com/")
        #         if not is_logged_in_GPT(): login_GPT()
        #         open_resume_chat()
        #         global chatGPT_tab
        #         chatGPT_tab = driver.current_window_handle
        #     except Exception as e:
        #         print_lg("Opening OpenAI chatGPT tab failed!")
        if use_AI:
            aiClient = create_ai_client()

        # Start applying to jobs
        driver.switch_to.window(linkedIn_tab)
        total_runs = run(total_runs)
        while(run_non_stop):
            if cycle_date_posted:
                date_options = ["Any time", "Past month", "Past week", "Past 24 hours"]
                global date_posted
                date_posted = date_options[date_options.index(date_posted)+1 if date_options.index(date_posted)+1 > len(date_options) else -1] if stop_date_cycle_at_24hr else date_options[0 if date_options.index(date_posted)+1 >= len(date_options) else date_options.index(date_posted)+1]
            if alternate_sortby:
                global sort_by
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
                total_runs = run(total_runs)
                sort_by = "Most recent" if sort_by == "Most relevant" else "Most relevant"
            total_runs = run(total_runs)
            if dailyEasyApplyLimitReached:
                break
            if not is_paid() and applications_today() >= free_daily_limit:
                break
        

    except (NoSuchWindowException, WebDriverException) as e:
        print_lg("The browser window was closed or the session became invalid. Exiting.", e)
    except Exception as e:
        critical_error_log("In Applier Main", e)
        pyautogui.alert(e,alert_title)
    finally:
        if is_dry_run():
            print_lg(dry_run.summary())
        summary = "Total runs: {}\nJobs Easy Applied: {}\nExternal job links collected: {}\nTotal applied or collected: {}\nFailed jobs: {}\nIrrelevant jobs skipped: {}\n".format(total_runs,easy_applied_count,external_jobs_count,easy_applied_count + external_jobs_count,failed_count,skip_count)
        events.emit("RUN_COMPLETED", mode=sys.argv[1:], easy=easy_applied_count, external=external_jobs_count, failed=failed_count, skipped=skip_count)
        print_lg(summary)
        print_lg("\n\nTotal runs:                     {}".format(total_runs))
        print_lg("Jobs Easy Applied:              {}".format(easy_applied_count))
        print_lg("External job links collected:   {}".format(external_jobs_count))
        print_lg("                              ----------")
        print_lg("Total applied or collected:     {}".format(easy_applied_count + external_jobs_count))
        print_lg("\nFailed jobs:                    {}".format(failed_count))
        print_lg("Irrelevant jobs skipped:        {}\n".format(skip_count))
        if randomly_answered_questions: print_lg("\n\nQuestions randomly answered:\n  {}  \n\n".format(";\n".join(str(question) for question in randomly_answered_questions)))
        quotes = choice([
            "Never quit. You're one step closer than before. - Sai Vignesh Golla", 
            "All the best with your future interviews, you've got this. - Sai Vignesh Golla", 
            "Keep up with the progress. You got this. - Sai Vignesh Golla", 
            "If you're tired, learn to take rest but never give up. - Sai Vignesh Golla",
            "Success is not final, failure is not fatal, It is the courage to continue that counts. - Winston Churchill (Not a sponsor)",
            "Believe in yourself and all that you are. Know that there is something inside you that is greater than any obstacle. - Christian D. Larson (Not a sponsor)",
            "Every job is a self-portrait of the person who does it. Autograph your work with excellence. - Jessica Guidobono (Not a sponsor)",
            "The only way to do great work is to love what you do. If you haven't found it yet, keep looking. Don't settle. - Steve Jobs (Not a sponsor)",
            "Opportunities don't happen, you create them. - Chris Grosser (Not a sponsor)",
            "The road to success and the road to failure are almost exactly the same. The difference is perseverance. - Colin R. Davis (Not a sponsor)",
            "Obstacles are those frightful things you see when you take your eyes off your goal. - Henry Ford (Not a sponsor)",
            "The only limit to our realization of tomorrow will be our doubts of today. - Franklin D. Roosevelt (Not a sponsor)",
            ])
        sponsors = "Be the first to have your name here!"
        timeSaved = (easy_applied_count * 80) + (external_jobs_count * 20) + (skip_count * 10)
        timeSavedMsg = ""
        if timeSaved > 0:
            timeSaved += 60
            timeSavedMsg = f"In this run, you saved approx {round(timeSaved/60)} mins ({timeSaved} secs), please consider supporting the project."
        msg = f"{quotes}\n\n\n{timeSavedMsg}\nYou can also get your quote and name shown here, or prioritize your bug reports by supporting the project at:\n\nhttps://github.com/sponsors/GodsScion\n\n\nSummary:\n{summary}\n\n\nBest regards,\nSai Vignesh Golla\nhttps://www.linkedin.com/in/saivigneshgolla/\n\nTop Sponsors:\n{sponsors}"
        print_lg("Run finished: " + msg)
        print_lg(msg,"Closing the browser...")
        if tabs_count >= 10:
            msg = "NOTE: IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM!\n\nOr it's highly likely that application will just open browser and not do anything next time!" 
            pyautogui.alert(msg,"Info")
            print_lg("\n"+msg)
        if use_AI and aiClient:
            try:
                close_ai_client(aiClient)
                print_lg(f"Closed {ai_provider} AI client.")
            except Exception as e:
                print_lg("Failed to close AI client:", e)
        try:
            if driver:
                driver.quit()
        except WebDriverException as e:
            print_lg("Browser already closed.", e)
        except Exception as e: 
            critical_error_log("When quitting...", e)


if __name__ == "__main__":
    main()
