'''
Dual-channel referral messaging: LinkedIn DM + Gmail.

Sends personalized referral request messages to HR contacts found during
the referral scan. Uses {variable} templates matching the HAPPPY format.
'''

import re
import os
import csv
import json

from time import sleep
from random import randint
from urllib.parse import urlencode, quote

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

from modules.helpers import buffer, print_lg, sleep
from modules.license import (
    can_send_referral, record_referral_message, referral_msg_remaining,
    referral_sent_for_job, record_referral_job_sent,
)
from modules import dry_run
from modules import events
from modules.dry_run import is_dry_run
from config.settings import (
    send_via_linkedin, send_via_gmail,
    linkedin_dm_template, linkedin_connect_note, gmail_subject, gmail_body,
    referral_dm_delay, referral_dm_max, referral_target_count,
)
from config.personals import (
    first_name, last_name, current_city,
)
from config.questions import (
    linkedIn, website, work_role, work_company,
)


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

USER_DATA = {
    "your_name": f"{first_name} {last_name}".strip(),
    "your_role": work_role,
    "your_company": work_company,
    "your_city": current_city,
    "your_linkedin": linkedIn,
    "your_portfolio": website,
}


# ---------------------------------------------------------------------------
# Connection resolver: find 1st-degree connections behind each job's
# "N connections work here" link, with people-search fallback.
# ---------------------------------------------------------------------------


def _company_relevant(headline: str, company: str) -> bool:
    """Best-effort check that a connection's headline actually mentions the
    target company. Keeps messaging from going to a 1st-degree connection who
    merely happened to appear in a company-keyword people search but does not
    actually work there.

    Tokenises on non alphanumerics and compares case-insensitively so that a
    headline like "Talent @ Acme Corp" matches company "Acme". An empty/unknown
    headline returns False (caller decides how to use that signal).
    """
    if not headline or not company:
        return False
    h = re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()
    c = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
    if not h or not c:
        return False
    return c in h or all(word in h for word in c.split())


_LOCALE_SEGMENTS = {
    "en", "es", "de", "fr", "it", "ja", "ko", "pt", "zh", "ar", "hi", "in",
    "nl", "pl", "ru", "tr", "th", "vi", "id", "ms", "fil", "sv", "no", "da",
    "fi", "el", "ro", "hu", "cs", "uk", "he", "fa", "bg", "sr", "sk", "hr",
}


def _normalize_profile_url(url):
    """Return a LinkedIn profile URL that renders the full profile.

    LinkedIn serves a degraded activity-feed view (no owner Message/Connect
    action row) for locale-prefixed profile URLs such as ``.../in/user/en/`` in
    some sessions, while the plain ``.../in/user/`` form renders the full
    profile. Strip the query string, any trailing locale segment, and make sure
    the result is an absolute ``www.linkedin.com`` URL.
    """
    if not url:
        return url
    url = url.split("?")[0].split("#")[0].rstrip("/")
    if "/in/" in url:
        parts = url.split("/")
        # https: / "" / www.linkedin.com / in / <username> [ / <locale> ]
        if (
            len(parts) == 6
            and len(parts[-1]) == 2
            and parts[-1].isalpha()
            and parts[-1].lower() in _LOCALE_SEGMENTS
        ):
            parts = parts[:-1]
            url = "/".join(parts)
    if not url.startswith("http"):
        url = "https://www.linkedin.com" + url
    return url


def _parse_people_cards(cards) -> list[dict]:
    """Parse LinkedIn people-search result cards into connection dicts.

    Returns a list of {name, profile_url, headline, degree}. 'degree' is the
    detected connection badge ("1st"/"2nd"/"3rd") parsed from the card text, or
    "unknown". Cards without a name-only /in/ link are skipped.
    """
    connections = []
    seen_urls = set()

    for card in cards:
        try:
            card_text = card.text
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            if not lines:
                continue

            degree = "unknown"
            for token in card_text.split():
                t = token.strip("\u2022")
                if t in ("1st", "2nd", "3rd"):
                    degree = t
                    break

            # The primary person's name is the first non-empty line of the card.
            # Their name-only anchor is the /in/ link whose text is exactly the
            # (badge-stripped) name; mutual-connection links have longer text.
            primary_name_text = lines[0].replace(" \u2022 1st", "").strip()

            name_links = card.find_elements(By.CSS_SELECTOR, "a[href*='/in/']")
            if not name_links:
                continue

            name_link = None
            for ln in name_links:
                t = ln.text.strip().replace("\u2022", "").replace("1st", "").replace("2nd", "").replace("3rd", "").strip()
                if t == primary_name_text:
                    name_link = ln
                    break
            if name_link is None:
                name_link = name_links[0]

            profile_url = _normalize_profile_url(name_link.get_attribute("href"))
            name_text = primary_name_text

            if not name_text or profile_url in seen_urls:
                continue
            seen_urls.add(profile_url)

            # Extract headline from card text (immediately after the degree badge)
            headline = ""
            try:
                for idx, line in enumerate(lines):
                    if name_text in line and idx + 1 < len(lines):
                        next_idx = idx + 1
                        while next_idx < len(lines) and (
                            lines[next_idx] in ("1st", "2nd", "3rd")
                            or lines[next_idx].replace("\u2022", "").strip() in ("1st", "2nd", "3rd")
                        ):
                            next_idx += 1
                        if next_idx < len(lines):
                            headline = lines[next_idx]
                        break
            except Exception:
                pass

            connections.append({
                "name": name_text,
                "profile_url": profile_url,
                "headline": headline,
                "degree": degree,
            })
        except Exception:
            continue

    return connections


def _extract_job_connections(driver, job_url: str) -> list[dict]:
    """
    Read the real 1st-degree connections behind a job page's 'N connections
    work here' link. LinkedIn builds that people-search URL server-side with the
    correct network filter, so every result is an actual connection of the
    logged-in account (no Premium needed, unlike reading the badge names
    directly). Returns [] when the job page has no such link.
    """
    if not job_url:
        return []

    try:
        driver.get(job_url)
        sleep(randint(25, 40) * 0.1)
    except Exception as e:
        print_lg(f"  Failed to load job page for connections: {e}")
        return []

    if "login" in driver.current_url or "authwall" in driver.current_url:
        return []

    # Give the badge ("N connections work here") up to 10s to render; it can lag
    # the rest of the page.
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//a[contains(., 'connection') and contains(., 'work here')]")
            )
        )
    except Exception:
        pass

    try:
        link = driver.find_element(
            By.XPATH,
            "//a[contains(., 'connection') and contains(., 'work here')]"
        )
        href = link.get_attribute("href")
    except Exception:
        print_lg("  No 'connections work here' link on job page.")
        return []

    if not href or "login" in href:
        return []

    print_lg(f"  Opening connections link: {href}")
    try:
        driver.get(href)
        sleep(randint(25, 40) * 0.1)
    except Exception as e:
        print_lg(f"  Failed to open connections link: {e}")
        return []

    if "login" in driver.current_url or "authwall" in driver.current_url:
        return []

    cards = driver.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, "li.reusable-search__result-container")

    connections = _parse_people_cards(cards)
    first = connections[0]["name"] if connections else "none"
    print_lg(f"  Extracted {len(connections)} connection(s) from job page ({first!r})")
    return connections


def _resolve_connections_for_company(driver, company: str, max_pages: int = 2, first_degree_only: bool = True) -> list[dict]:
    """
    Search LinkedIn people results filtered to YOUR 1st-degree connections.
    Returns a list of {name, profile_url, headline} dicts.
    Uses the free network filter (no Premium needed).
    """
    if not company:
        return []

    url = f"https://www.linkedin.com/search/results/people/?keywords={quote(company)}&network=%5B%22F%22%5D&origin=FACETED_SEARCH"
    try:
        driver.get(url)
        sleep(randint(25, 40) * 0.1)
    except Exception as e:
        print_lg(f"  Failed to load people search for '{company}': {e}")
        return []

    # Check for authwall
    if "login" in driver.current_url or "authwall" in driver.current_url:
        print_lg(f"  Authwall detected during people search for '{company}'.")
        return []

    connections = []
    seen_urls = set()

    for page in range(max_pages):
        sleep(2)
        # Current LinkedIn DOM uses role="listitem" for people search results
        cards = driver.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
        if not cards:
            # Fallback to older selectors
            cards = driver.find_elements(By.CSS_SELECTOR, "li.reusable-search__result-container")
        if not cards:
            break

        for conn in _parse_people_cards(cards):
            if conn["profile_url"] in seen_urls:
                continue
            seen_urls.add(conn["profile_url"])
            if first_degree_only and conn.get("degree") not in ("1st",):
                continue
            connections.append(conn)

        # Try next page
        if page < max_pages - 1:
            try:
                next_btn = driver.find_element(
                    By.CSS_SELECTOR, "button[aria-label='Next']"
                )
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
                sleep(0.5)
                next_btn.click()
                sleep(randint(15, 25) * 0.1)
            except Exception:
                break

    for conn in connections:
        conn["relevant"] = _company_relevant(conn.get("headline", ""), company)

    # Order company-matched connections first so the most likely valid recipient
    # for the job is messaged before any fallback candidates.
    ordered = [c for c in connections if c.get("relevant")] + [c for c in connections if not c.get("relevant")]
    print_lg(
        f"  Found {len(ordered)} first-degree connection(s) for {company} "
        f"({sum(1 for c in ordered if c.get('relevant'))} company-matched)"
    )
    return ordered


def resolve_all_connections(driver, referral_results: list[dict]) -> list[dict]:
    """
    Resolve the real 1st-degree connections behind each referral job's
    'N connections work here' link (LinkedIn builds that people-search URL with
    the correct network filter server-side, so every result is a genuine
    connection). Falls back to a company-keyword people search that keeps only
    verified 1st-degree cards when a job page has no such link.

    Returns a flat list of enriched job dicts, one per (job, connection) pair
    with 'hr_name' and 'hr_link' filled in. Only 1st-degree contacts are kept so
    every target offers a Message (or connect-with-note) route.
    """
    # Deduplicate companies
    company_map = {}
    for job in referral_results:
        company = job.get("company", "")
        if company and company not in company_map:
            company_map[company] = job

    all_targets = []

    for company, sample_job in company_map.items():
        print_lg(f"\nResolving connections at {company}...")
        connections = _extract_job_connections(driver, sample_job.get("link", ""))

        if not connections:
            print_lg(f"  Falling back to people search for {company}...")
            connections = _resolve_connections_for_company(driver, company, max_pages=1)

        if not connections:
            # Still include the job with "Unknown" HR so it shows in results
            target = dict(sample_job)
            target["hr_name"] = "Unknown"
            target["hr_link"] = ""
            target["hr_headline"] = ""
            all_targets.append(target)
            continue

        for conn in connections[:3]:  # Max 3 connections per company to keep it manageable
            target = dict(sample_job)
            target["hr_name"] = conn["name"]
            target["hr_link"] = conn["profile_url"]
            target["hr_headline"] = conn.get("headline", "")
            target["hr_relevant"] = bool(conn.get("relevant"))
            all_targets.append(target)

        buffer(randint(3, 6))

    return all_targets


def _compose_message(template: str, job: dict) -> str:
    """Fill {variable} placeholders in a template with job + user data."""
    variables = {
        "employee_name": job.get("hr_name", "there"),
        "job_title": job.get("title", "the role"),
        "company_name": job.get("company", "your company"),
        "job_link": job.get("link", ""),
    }
    variables.update(USER_DATA)
    try:
        return template.format(**variables)
    except KeyError as e:
        print_lg(f"Template variable {e} not recognized. Using template as-is.")
        return template


def _try_extract_email(driver, profile_url: str) -> str | None:
    """Visit a LinkedIn profile and try to extract an email from Contact Info."""
    if not profile_url:
        return None
    profile_url = _normalize_profile_url(profile_url)
    try:
        original_url = driver.current_url
        driver.get(profile_url)
        sleep(randint(20, 40) * 0.1)

        # Click "Contact info" link
        try:
            contact_link = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#top-card-text-details-contact-info"))
            )
            contact_link.click()
            sleep(1.5)
        except Exception:
            try:
                contact_link = driver.find_element(
                    By.XPATH, "//a[contains(@href, 'overlay/contact-info')]"
                )
                contact_link.click()
                sleep(1.5)
            except Exception:
                # No contact info link — try About section as fallback
                return _extract_email_from_about(driver, profile_url, original_url)

        # Scan the contact info modal for emails
        try:
            modal = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.artdeco-modal"))
            )
            text = modal.text
            emails = set(EMAIL_RE.findall(text))
            # Filter out LinkedIn's own emails
            emails = {e for e in emails if "linkedin" not in e.lower()}
            if emails:
                email = next(iter(emails))
                print_lg(f"Found email: {email}")
                # Close modal
                try:
                    close_btn = modal.find_element(By.CSS_SELECTOR, "button[aria-label='Dismiss']")
                    close_btn.click()
                    sleep(0.5)
                except Exception:
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    sleep(0.5)
                driver.get(original_url)
                return email
        except Exception:
            pass

        # Close modal if still open
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            sleep(0.5)
        except Exception:
            pass

        # Try About section as fallback
        email = _extract_email_from_about(driver, profile_url, original_url)
        if email:
            return email

        driver.get(original_url)
        return None
    except Exception as e:
        print_lg(f"Email extraction failed: {e}")
        try:
            driver.get(original_url)
        except Exception:
            pass
        return None


def _extract_email_from_about(driver, profile_url: str, original_url: str) -> str | None:
    """Try to find an email in the About section of a LinkedIn profile."""
    try:
        # Scroll to About section and expand it
        about_section = driver.find_element(By.ID, "about")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", about_section)
        sleep(1)
        # Try to click "see more" to expand
        try:
            see_more = about_section.find_element(
                By.XPATH, ".//button[contains(@aria-label, 'more')]"
            )
            see_more.click()
            sleep(1)
        except Exception:
            pass
        text = about_section.text
        emails = set(EMAIL_RE.findall(text))
        emails = {e for e in emails if "linkedin" not in e.lower()}
        if emails:
            email = next(iter(emails))
            print_lg(f"Found email in About section: {email}")
            driver.get(original_url)
            return email
    except Exception:
        pass
    return None


def _send_linkedin_dm(driver, hr_link: str, message: str) -> tuple[bool, str]:
    """Navigate to profile, open the messaging compose for the owner, handle
    shadow DOM, type + send. Returns (success: bool, reason: str).
    """
    if not hr_link:
        print_lg("No LinkedIn profile link for this contact. Skipping LinkedIn DM.")
        return False, "No profile link"

    hr_link = _normalize_profile_url(hr_link)

    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)
        print_lg(f"[DM] Loading profile: {hr_link}")

        # Preferred route (2025+ UI): the owner action row exposes "Message" as an
        # anchor to /messaging/compose/?profileUrn=...&recipient=... — a native
        # composer. Navigate straight to it.
        compose_url = driver.execute_script("""
            const main = document.querySelector('#main-content, main') || document;
            for (const el of main.querySelectorAll('a[href*="/messaging/compose/"]')) {
                if ((el.textContent || '').trim() === 'Message') {
                    const href = el.getAttribute('href');
                    if (href) return 'https://www.linkedin.com' + href;
                }
            }
            return '';
        """)
        if compose_url:
            print_lg(f"[DM] Using native compose URL")
            driver.get(compose_url)
            sleep(randint(25, 40) * 0.1)
        else:
            # Older UI fallback: click the "Message" button -> overlay composer.
            try:
                msg_btn = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(@aria-label, 'Message')]")
                    )
                )
                msg_btn.click()
                sleep(2)
                print_lg("[DM] Clicked Message button")
            except Exception:
                print_lg("Could not find or click the Message button on this profile.")
                driver.get(original_url)
                return False, "No Message button"

        # Find the message editor — try shadow DOM first (LinkedIn 2025+), then light DOM
        editor = driver.execute_script("""
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                return host.shadowRoot.querySelector('.msg-form__contenteditable')
                    || host.shadowRoot.querySelector('[role="textbox"]');
            }
            return document.querySelector('div.msg-form__contenteditable')
                || document.querySelector('div[role="textbox"]');
        """)

        if not editor:
            print_lg("Could not find the message editor (shadow DOM or light DOM).")
            driver.get(original_url)
            return False, "No message editor found"

        # Type the message. Prefer real keystrokes (trusted input events) so
        # LinkedIn's React editor registers the draft; fall back to JS injection
        # only if the keys did not land.
        editor.click()
        sleep(0.3)
        editor.send_keys(Keys.BACKSPACE)
        sleep(0.2)
        editor.send_keys(message)
        sleep(1)
        typed = driver.execute_script(
            "return (arguments[0].innerText || '').length;", editor
        )
        print_lg(f"[DM] Draft length after keystrokes: {typed}")
        if not typed:
            driver.execute_script(
                "arguments[0].innerText = arguments[1];", editor, message
            )
            driver.execute_script("""
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, editor)
            sleep(1)
            print_lg("[DM] Injected draft via JS fallback")

        # Find and click the Send button — also try shadow DOM first
        send_btn = driver.execute_script("""
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                return host.shadowRoot.querySelector('.msg-form__send-button')
                    || host.shadowRoot.querySelector('button[aria-label="Send"]');
            }
            return document.querySelector('button.msg-form__send-button')
                || document.querySelector('[role="button"][aria-label^="Send"]');
        """)

        if not send_btn:
            print_lg("Could not find the Send button.")
            driver.get(original_url)
            return False, "No Send button"

        # Check if button is disabled — wait briefly for it to enable, since
        # LinkedIn registers the typed text asynchronously after the input event.
        for _ in range(8):
            is_disabled = driver.execute_script(
                "return arguments[0].disabled || arguments[0].getAttribute('aria-disabled') === 'true';",
                send_btn
            )
            if not is_disabled:
                break
            sleep(1)
        if is_disabled:
            print_lg("Send button stayed disabled — message may not have registered.")
            driver.get(original_url)
            return False, "Send button disabled"

        send_btn.click()
        sleep(2)

        # Try to detect "Message sent" confirmation
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(), 'Message sent') or contains(text(), 'sent')]")
                )
            )
            print_lg("LinkedIn DM sent successfully!")
        except Exception:
            print_lg("Message sent (no confirmation toast detected).")

        driver.get(original_url)
        return True, ""

    except Exception as e:
        print_lg(f"LinkedIn DM failed: {e}")
        try:
            driver.get(original_url)
        except Exception:
            pass
        return False, str(e)


# ---------------------------------------------------------------------------
# LinkedIn outreach routing: DM if already connected, else connect-with-note
# ---------------------------------------------------------------------------


def _profile_action(driver) -> str:
    """Detect which primary action button is on a loaded LinkedIn profile.
    Returns 'connect' (not connected yet / connect is offered), 'message'
    (already a 1st-degree connection), 'pending' (request already sent),
    'following' (only a Follow button), or '' (none detected)."""
    try:
        # Wait for the profile to actually render before probing the button row.
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "main, .pv-top-card, section.scaffold-layout"))
            )
        except Exception:
            pass
        sleep(1)

        result = driver.execute_script("""
            // Prefer the profile's own action row: scope to the main column so a
            // sidebar "Follow <stranger>" / "Message <stranger>" element is never
            // mistaken for the owner's action. Fall back to the whole document
            // when main contains no interactable actions.
            const main = document.querySelector('#main-content, main') || document;
            const container = (main.querySelectorAll('button, a[href*="/messaging/compose/"]').length > 0) ? main : document;
            // Owner "Message" action (2025+ UI): an anchor to /messaging/compose/
            // whose visible label is exactly "Message" — sidebar ones read
            // "Message <full name>".
            for (const el of container.querySelectorAll('a[href*="/messaging/compose/"]')) {
                if ((el.textContent || '').trim() === 'Message') return 'message';
            }
            for (const el of container.querySelectorAll('button[aria-label*="Message"]')) {
                const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                if (/Message/i.test(label)) return 'message';
            }
            for (const el of container.querySelectorAll('button[aria-label*="Connect"]')) {
                const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                if (/follow|pending|requested|message|invite/i.test(label)) continue;
                return 'connect';
            }
            for (const el of container.querySelectorAll('button[aria-label*="Pending"]')) {
                const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                if (/message|connect/i.test(label)) continue;
                return 'pending';
            }
            for (const el of container.querySelectorAll('button[aria-label*="Follow"]')) {
                const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                if (/Message/i.test(label)) continue;
                return 'following';
            }
            return '';
        """)
        if result in ("message", "connect", "pending"):
            return result

        # Some profiles hide "Connect" behind the More dropdown (button with
        # aria-label "More" / "More actions"). Open it and scan the menu while
        # it is visible. Close it again afterwards so the page is left tidy.
        found = driver.execute_script("""
            const open = () => {
                const btn = document.querySelector('button[aria-label*="More"]:not([aria-label*="following"])');
                if (btn) { btn.click(); return true; }
                return false;
            };
            if (!open()) return '';
            return 'opened';
        """)
        if found:
            sleep(1.5)
            menu_result = driver.execute_script("""
                const btns = [...document.querySelectorAll('div[role="menu"] button, li[role="presentation"] button, div[aria-label*="menu"] button, button')];
                const text = (n) => (n.getAttribute('aria-label') || '') + ' ' + (n.textContent || '');
                const has = (re) => btns.some(n => re.test(text(n)));
                if (has(/message/i)) return 'message';
                if (has(/^\\s*connect\\s*$/i) || has(/connect with/i)) return 'connect';
                if (has(/pending/i)) return 'pending';
                if (has(/follow/i) && !has(/following/i)) return 'following';
                return '';
            """)
            if menu_result:
                return menu_result
            # Close the dropdown so a lingering menu never intercepts later clicks
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            return result or ""
        return result or ""

    except Exception:
        return ""


def _dry_probe_profile_action(driver, hr_link: str) -> str:
    """Read-only companion for dry-run: load a profile and detect which
    outreach action LinkedIn currently offers for it, without clicking
    anything and without sending."""
    if not hr_link:
        return ""
    hr_link = _normalize_profile_url(hr_link)
    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)
        action = _profile_action(driver)
        driver.get(original_url)
        return action
    except Exception:
        return ""


def _click_connect(driver) -> bool:
    """Click a profile's Connect button — either the direct top button or the
    'Connect' item inside the More dropdown (used when LinkedIn only exposes
    Connect under the actions menu). Returns True if a Connect click landed."""
    direct = driver.execute_script("""
        const els = document.querySelectorAll('button[aria-label*="Connect"]');
        for (const el of els) {
            const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
            if (/follow|pending|requested|message|invite/i.test(label)) continue;
            el.click(); return true;
        }
        return false;
    """)
    if direct:
        return True

    # No top-level Connect: open the More dropdown and click its Connect item.
    opened = driver.execute_script("""
        const btn = document.querySelector('button[aria-label*="More"]:not([aria-label*="following"])');
        if (btn) { btn.click(); return true; }
        return false;
    """)
    if not opened:
        return False
    sleep(1.5)
    clicked = driver.execute_script("""
        if (window.__ajaMoreOpened) return false;
        const btns = [...document.querySelectorAll('div[role="menu"] button, button')];
        for (const el of btns) {
            const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
            if (/^\\s*connect\\s*$/i.test(label) || /connect with/i.test(label)) {
                el.click(); return true;
            }
        }
        return false;
    """)
    if clicked:
        return True
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass
    return False


def _send_linkedin_connect_request(driver, hr_link: str, note: str) -> tuple[bool, str]:
    """Send a LinkedIn connection request with a personal note (no DM possible
    for non-connections on a free account). Assumes the profile is NOT already
    connected. Returns (success: bool, reason: str)."""
    if not hr_link:
        return False, "No profile link"

    hr_link = _normalize_profile_url(hr_link)

    # LinkedIn personal notes are capped at 300 characters.
    note = (note or "").strip()[:300]

    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)
        print_lg(f"[CONNECT] Loading profile: {hr_link}")

        # Re-check the action so we don't connect to an already-connected person
        action = _profile_action(driver)
        if action != "connect":
            reason = {
                "message": "Already connected (Message offered)",
                "pending": "Connection request already pending",
                "following": "Only Follow offered (cannot connect)",
            }.get(action, "No Connect button")
            print_lg(f"[CONNECT] {reason}")
            driver.get(original_url)
            return False, reason

        # Find and click the Connect button (direct or via the More dropdown)
        if not _click_connect(driver):
            print_lg("[CONNECT] Could not find the Connect button.")
            driver.get(original_url)
            return False, "No Connect button"

        sleep(2)
        print_lg("[CONNECT] Clicked Connect (dialog opened)")

        # Open the "Add a note" panel inside the connect dialog
        driver.execute_script("""
            const dialog = document.querySelector('[role="dialog"]');
            const root = dialog || document;
            const els = [...root.querySelectorAll('button, span, a')];
            const el = els.find(n => /Add a note/i.test(n.textContent || ''));
            if (el) el.click();
            return !!el;
        """)
        sleep(1)

        # Find the note editor: textarea (preferred) or contenteditable within the dialog
        editor = driver.execute_script("""
            const dialog = document.querySelector('[role="dialog"]');
            const root = dialog || document;
            const textareas = [...root.querySelectorAll('textarea')];
            const ct = [...root.querySelectorAll('[contenteditable="true"]')];
            return textareas[0] || ct[0] || null;
        """)
        if not editor:
            print_lg("[CONNECT] Could not find the note field. Sending without a note.")
        else:
            try:
                editor.click()
                sleep(0.3)
                driver.execute_script("arguments[0].innerText = arguments[1];", editor, note)
                driver.execute_script("""
                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                """, editor)
                sleep(0.5)
                print_lg("[CONNECT] Note filled.")
            except Exception:
                print_lg("[CONNECT] Failed to fill note; will send without note.")

        # Click the send button on the connect dialog (Send / Send without a note)
        sent = driver.execute_script("""
            const dialog = document.querySelector('[role="dialog"]');
            const root = dialog || document;
            const els = [...root.querySelectorAll('button')];
            const el = els.find(n => /Send/i.test(n.textContent || '') && !n.disabled);
            if (el) { el.click(); return true; }
            return false;
        """)
        sleep(2)

        if not sent:
            print_lg("[CONNECT] Could not find the Send button in the dialog.")
            driver.get(original_url)
            return False, "No Send button"

        print_lg("LinkedIn connection request sent successfully!")
        driver.get(original_url)
        return True, ""

    except Exception as e:
        print_lg(f"LinkedIn connect request failed: {e}")
        try:
            driver.get(original_url)
        except Exception:
            pass
        return False, str(e)


def _send_linkedin_message_or_connect(driver, hr_link: str, message: str, note: str) -> tuple[bool, str]:
    """Route LinkedIn outreach to the right action:
    - already a connection -> send a DM
    - not connected -> send a connection request with a note
    Returns (success: bool, reason: str)."""
    if not hr_link:
        return False, "No profile link"

    hr_link = _normalize_profile_url(hr_link)

    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)

        action = _profile_action(driver)
        if action not in ("message", "connect", "pending"):
            # LinkedIn can serve the locale-prefixed (/en/) profile in a
            # degraded activity-feed form that hides the owner action row.
            # Fall back to the plain profile URL once before giving up.
            plain = _normalize_profile_url(hr_link)
            if plain != hr_link:
                print_lg(f"[ROUTE] Retrying on plain profile URL: {plain}")
                driver.get(plain)
                sleep(randint(20, 35) * 0.1)
                action = _profile_action(driver)
                if action in ("message", "connect", "pending"):
                    hr_link = plain
        if action == "message":
            driver.get(original_url)
            print_lg("[ROUTE] Already connected — sending DM.")
            return _send_linkedin_dm(driver, hr_link, message)
        if action == "connect":
            driver.get(original_url)
            print_lg("[ROUTE] Not connected — sending connection request with note.")
            return _send_linkedin_connect_request(driver, hr_link, note)
        reason = {
            "pending": "Connection request already pending",
            "following": "Only Follow offered (cannot connect)",
        }.get(action, "No Message or Connect button")
        print_lg(f"[ROUTE] {reason}")
        driver.get(original_url)
        return False, reason

    except Exception as e:
        print_lg(f"LinkedIn outreach failed: {e}")
        try:
            driver.get(original_url)
        except Exception:
            pass
        return False, str(e)


def _send_gmail(driver, hr_email: str, subject: str, body: str) -> bool:
    """Open Gmail compose URL with pre-filled params, then click Send."""
    if not hr_email:
        print_lg("No email address for this contact. Skipping Gmail.")
        return False

    try:
        params = urlencode({"to": hr_email, "su": subject, "body": body, "tf": "cm"})
        url = f"https://mail.google.com/mail/u/0/?{params}"
        driver.get(url)
        sleep(randint(30, 50) * 0.1)

        # Wait for the compose dialog to appear
        try:
            dialog = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div[role='dialog']")
                )
            )
        except Exception:
            print_lg("Gmail compose dialog did not appear. Are you logged into Gmail?")
            return False

        sleep(1)

        # Find and click the Send button in the compose dialog
        try:
            send_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[role='dialog'] [role='button'][aria-label*='Send']")
                )
            )
            send_btn.click()
            sleep(3)
            print_lg(f"Gmail sent to {hr_email}!")
            return True
        except Exception:
            print_lg("Could not find or click the Gmail Send button.")
            return False

    except Exception as e:
        print_lg(f"Gmail send failed: {e}")
        return False


def _log_message_result(csv_path: str, job: dict, channel: str, success: bool, error: str = ""):
    """Append a row to the referral message log CSV."""
    file_exists = os.path.isfile(csv_path)
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "Timestamp", "Job ID", "Title", "Company", "HR Name",
                    "Channel", "Status", "Error", "Job Link"
                ])
            writer.writerow([
                job.get("timestamp", ""),
                job.get("job_id", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("hr_name", ""),
                channel,
                "Sent" if success else "Failed",
                error,
                job.get("link", ""),
            ])
    except Exception as e:
        print_lg(f"Failed to write log: {e}")


def _load_referral_results() -> list[dict]:
    """Load referral_results.json and return the results list."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "referral_results.json")
    if not os.path.isfile(path):
        print_lg("No referral_results.json found. Run --referral first.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results", [])


def send_referral_messages(driver, results: list[dict] = None) -> dict:
    """
    Main entry point: send referral messages via LinkedIn DM and/or Gmail.

    Resolves actual connection names at each company via LinkedIn people search,
    then sends messages to those connections.

    Args:
        driver: Selenium WebDriver instance
        results: List of referral result dicts (loaded from JSON if None)

    Returns:
        dict with counts: {"linkedin_sent", "linkedin_failed", "gmail_sent", "gmail_failed", "skipped"}
    """
    if results is None:
        results = _load_referral_results()

    if not results:
        print_lg("No referral results to message.")
        return {"linkedin_sent": 0, "linkedin_failed": 0, "gmail_sent": 0, "gmail_failed": 0, "skipped": 0}

    if not can_send_referral():
        remaining = referral_msg_remaining()
        print_lg(f"LICENSE: Referral message daily limit reached ({remaining} remaining). Upgrade for unlimited messages.")
        return {"linkedin_sent": 0, "linkedin_failed": 0, "gmail_sent": 0, "gmail_failed": 0, "skipped": len(results), "limited": True}

    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "referral_message_log.csv")
    stats = {"linkedin_sent": 0, "linkedin_failed": 0, "gmail_sent": 0, "gmail_failed": 0, "skipped": 0}
    dry = is_dry_run()

    def _stop_after_first_send():
        """Halts the loop at the first successful message when
        AJA_STOP_AFTER_FIRST_SEND is set (live runs stop at one confirmed send)."""
        return bool(os.environ.get("AJA_STOP_AFTER_FIRST_SEND")) and (stats["linkedin_sent"] + stats["gmail_sent"]) >= 1
    if dry:
        print_lg("\n[DRY RUN] Referral messaging rehearsal - connections will be resolved but NO messages will be sent.")

    # Resolve actual connection names at each company via people search
    print_lg(f"\n{'='*60}")
    print_lg("RESOLVING CONNECTIONS AT EACH COMPANY")
    print_lg(f"{'='*60}")
    actionable = resolve_all_connections(driver, results)

    if not actionable:
        print_lg("No connections found to message.")
        return stats

    # Filter to entries with a known name (not "Unknown")
    actionable = [r for r in actionable if r.get("hr_name") and r["hr_name"] != "Unknown"]
    # "Skipped" = referral jobs that ended up with no actionable contact. Because
    # resolve_all_connections may return more than one contact per job (up to 2 per
    # company), count distinct source job_ids rather than raw entries so this never
    # goes negative.
    actionable_job_ids = {r.get("job_id") for r in actionable if r.get("job_id")}
    result_job_ids = {r.get("job_id") for r in results if r.get("job_id")}
    skipped = max(0, len(result_job_ids) - len(actionable_job_ids))
    stats["skipped"] = skipped

    if not actionable:
        print_lg("No connection names found. Skipping messaging.")
        return stats

    print_lg(f"\n{'='*60}")
    print_lg(f"REFERRAL MESSAGING")
    print_lg(f"{'='*60}")
    print_lg(f"Total referral jobs: {len(results)}")
    print_lg(f"Connections found to message: {len(actionable)}")
    print_lg(f"LinkedIn DM: {'ON' if send_via_linkedin else 'OFF'}")
    print_lg(f"Gmail: {'ON' if send_via_gmail else 'OFF'}")
    print_lg(f"Delay between messages: {referral_dm_delay}s")
    print_lg(f"Max per channel: {referral_dm_max}")
    print_lg(f"{'='*60}\n")

    linkedin_count = 0
    gmail_count = 0

    # "One job = one referral": a single job may resolve to several HR contacts,
    # but we only ever send ONE referral per job posting. This set tracks jobs
    # that already have a confirmed referral so a duplicate contact for the same
    # job in this run is skipped.
    run_sent_job_ids = set()

    for i, job in enumerate(actionable):
        from datetime import datetime
        job["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        hr_name = job.get("hr_name", "there")
        title = job.get("title", "the role")
        company = job.get("company", "the company")
        job_id = job.get("job_id", "")

        # One job, one referral: skip this posting if it was already messaged in
        # a previous run (persisted) or earlier in this run.
        job_key = str(job_id or "").strip()
        if not job_key:
            # No job id (rare) — fall back to the HR profile URL.
            job_key = str(job.get("hr_link") or "").strip()
        if job_key and (job_key in run_sent_job_ids or referral_sent_for_job(job_key)):
            print_lg(f"\n[{i+1}/{len(actionable)}] {hr_name} — {title} at {company} (SKIPPED: referral already sent for this job)")
            stats["skipped"] += 1
            events.emit("REFERRAL_SKIPPED_JOB_ALREADY_SENT", job_id=job_id, hr=hr_name, company=company, title=title)
            continue

        print_lg(f"\n[{i+1}/{len(actionable)}] {hr_name} — {title} at {company}")
        events.emit("REFERRAL_SEND_ATTEMPTED", hr=hr_name, company=company, title=title, job_id=job_id)

        if dry:
            message = _compose_message(linkedin_dm_template, job)
            connect_note = _compose_message(linkedin_connect_note, job)
            subject = _compose_message(gmail_subject, job)
            body = _compose_message(gmail_body, job)
            action = _dry_probe_profile_action(driver, job.get("hr_link", ""))
            print_lg(f"\n[DRY RUN] {'-'*54}")
            print_lg(f"{hr_name} — {title} at {company}")
            print_lg(f"Profile: {job.get('hr_link','')}")
            print_lg(f"Available action: {action or 'none'}")
            if action == "message":
                print_lg("Route: LinkedIn DM (already connected). Would send:")
                print_lg(message)
                dry_run.count("referral_dm")
            elif action == "connect":
                print_lg("Route: connection request with personal note. Would send:")
                print_lg(connect_note)
                dry_run.count("referral_connect")
            else:
                print_lg(f"Route: {action or 'no Message/Connect button'} - LinkedIn not possible. Would fall back to Gmail.")
                email = _try_extract_email(driver, job.get("hr_link", ""))
                if email:
                    print_lg(f"Gmail -> {email}")
                    print_lg(f"Subject: {subject}")
                    print_lg(f"Body:\n{body}")
                    dry_run.count("referral_gmail")
                else:
                    print_lg("No email found; would be skipped.")
            print_lg(f"[DRY RUN] NOT SENDING ANYTHING. {'-'*10}")
            continue

        # Try LinkedIn DM
        dm_sent = False
        if send_via_linkedin and linkedin_count < referral_dm_max:
            # License gate: stop once today's daily message allowance is used up.
            if not can_send_referral():
                remaining = referral_msg_remaining()
                print_lg(f"LICENSE: Referral message daily limit reached ({remaining} left). Stopping. Upgrade for unlimited messages.")
                _log_message_result(log_path, job, "LinkedIn", False, "Daily message limit reached")
                break
            message = _compose_message(linkedin_dm_template, job)
            connect_note = _compose_message(linkedin_connect_note, job)
            print_lg(f"\n--- LinkedIn DM / Connect ---")
            print_lg(f"Message:\n{message}\n")
            success = _send_linkedin_message_or_connect(
                driver, job.get("hr_link", ""), message, connect_note
            )
            dm_sent = (success[0] if isinstance(success, tuple) else success)
            if dm_sent:
                stats["linkedin_sent"] += 1
                linkedin_count += 1
                record_referral_message()
                record_referral_job_sent(job_key, job)
                if job_key:
                    run_sent_job_ids.add(job_key)
                _log_message_result(log_path, job, "LinkedIn", True)
                events.emit("REFERRAL_SEND_SUCCESS", channel="linkedin", hr=hr_name, company=company, job_id=job.get("job_id", ""))
                if _stop_after_first_send():
                    print_lg("Stopping after first successful send (AJA_STOP_AFTER_FIRST_SEND).")
                    break
            else:
                stats["linkedin_failed"] += 1
                reason = success[1] if isinstance(success, tuple) else ""
                _log_message_result(log_path, job, "LinkedIn", False, reason)
                events.emit("REFERRAL_SEND_FAILED", channel="linkedin", hr=hr_name, company=company, reason=str(reason)[:200], job_id=job.get("job_id", ""))

            if linkedin_count < referral_dm_max and i < len(actionable) - 1:
                delay = randint(int(referral_dm_delay * 0.8), int(referral_dm_delay * 1.2))
                print_lg(f"Waiting {delay}s before next message...")
                sleep(delay)

        # Try Gmail (fallback to email delivery for this contact if the LinkedIn
        # DM failed OR if LinkedIn DM is disabled). This guarantees every valid
        # person still gets a message via Gmail even when they are not a
        # messageable connection on LinkedIn.
        if send_via_gmail and gmail_count < referral_dm_max and not dm_sent:
            # License gate: stop once today's daily message allowance is used up.
            if not can_send_referral():
                remaining = referral_msg_remaining()
                print_lg(f"LICENSE: Referral message daily limit reached ({remaining} left). Stopping. Upgrade for unlimited messages.")
                _log_message_result(log_path, job, "Gmail", False, "Daily message limit reached")
                break
            # Try to extract email from the HR's profile
            email = _try_extract_email(driver, job.get("hr_link", ""))
            if email:
                subject = _compose_message(gmail_subject, job)
                body = _compose_message(gmail_body, job)
                print_lg(f"\n--- Gmail ---")
                print_lg(f"To: {email}")
                print_lg(f"Subject: {subject}\n")
                success = _send_gmail(driver, email, subject, body)
                if success:
                    stats["gmail_sent"] += 1
                    gmail_count += 1
                    record_referral_message()
                    record_referral_job_sent(job_key, job)
                    if job_key:
                        run_sent_job_ids.add(job_key)
                    events.emit("REFERRAL_SEND_SUCCESS", channel="gmail", hr=hr_name, company=company, email=email, job_id=job.get("job_id", ""))
                    if _stop_after_first_send():
                        print_lg("Stopping after first successful send (AJA_STOP_AFTER_FIRST_SEND).")
                        break
                else:
                    stats["gmail_failed"] += 1
                    events.emit("REFERRAL_SEND_FAILED", channel="gmail", hr=hr_name, company=company, reason="gmail-send-failed", job_id=job.get("job_id", ""))
                _log_message_result(log_path, job, "Gmail", success)
            else:
                print_lg("No email found for this contact. Skipping Gmail.")
                _log_message_result(log_path, job, "Gmail", False, "No email found")
                events.emit("REFERRAL_SEND_FAILED", channel="gmail", hr=hr_name, company=company, reason="no-email-found", job_id=job.get("job_id", ""))

            if gmail_count < referral_dm_max and i < len(actionable) - 1:
                delay = randint(int(referral_dm_delay * 0.8), int(referral_dm_delay * 1.2))
                print_lg(f"Waiting {delay}s before next message...")
                sleep(delay)

        # Stop if both channels hit their limits
        if linkedin_count >= referral_dm_max and gmail_count >= referral_dm_max:
            print_lg(f"\nReached max messages per channel ({referral_dm_max}). Stopping.")
            break

    # "At least N referrals" reporting. Referrals are counted by distinct job
    # (one job = one referral). We report this run's new distinct jobs messaged,
    # the running total across all runs (from the persisted log), and any
    # shortfall against the target so you know to re-run / add targets.
    new_distinct = len(run_sent_job_ids)
    try:
        from modules.license import referral_jobs_sent_total
        lifetime_total = referral_jobs_sent_total()
    except Exception:
        lifetime_total = new_distinct
    shortfall = max(0, referral_target_count - lifetime_total)

    print_lg(f"\n{'='*60}")
    print_lg(f"REFERRAL MESSAGING COMPLETE")
    print_lg(f"{'='*60}")
    print_lg(f"LinkedIn DMs sent: {stats['linkedin_sent']}")
    print_lg(f"LinkedIn DMs failed: {stats['linkedin_failed']}")
    print_lg(f"Gmails sent: {stats['gmail_sent']}")
    print_lg(f"Gmails failed: {stats['gmail_failed']}")
    print_lg(f"Skipped (no HR info): {stats['skipped']}")
    print_lg(f"Distinct jobs messaged this run: {new_distinct}")
    print_lg(f"Distinct jobs messaged (all-time): {lifetime_total}")
    if shortfall:
        print_lg(f"Target: {referral_target_count} referrals - {shortfall} short. Re-run the referral send (or add more targets) to close the gap.")
    else:
        print_lg(f"Target: {referral_target_count} referrals - met. All {referral_target_count} referral slots reached.")
    print_lg(f"Log saved to: {log_path}")
    print_lg(f"{'='*60}\n")

    if dry:
        print_lg(dry_run.summary())

    return stats
