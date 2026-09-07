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
from random import randint, uniform
from urllib.parse import urlencode, quote

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

from modules.helpers import buffer, print_lg, sleep
from modules.license import can_send_referral, record_referral_message, referral_msg_remaining
from modules import dry_run
from modules.dry_run import is_dry_run
from config.settings import (
    send_via_linkedin, send_via_gmail,
    linkedin_dm_template, linkedin_connect_note, gmail_subject, gmail_body,
    referral_dm_delay, referral_dm_max,
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
# Connection resolver: find 1st-degree connections at a company via people search
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

def _resolve_connections_for_company(driver, company: str, max_pages: int = 2) -> list[dict]:
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

        for card in cards:
            try:
                card_text = card.text
                lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                if not lines:
                    continue

                # The primary person's name is the first non-empty line of the card.
                # Their name-only anchor (link[1]) is the shortest /in/ link whose
                # text is exactly the name. Mutual-connection links have longer/other text.
                primary_name_text = lines[0].replace(" \u2022 1st", "").strip()

                name_links = card.find_elements(By.CSS_SELECTOR, "a[href*='/in/']")
                if not name_links:
                    continue

                # Find the name-only link (shortest text that is just the name)
                name_link = None
                for ln in name_links:
                    t = ln.text.strip().replace("\u2022", "").replace("1st", "").replace("2nd", "").replace("3rd", "").strip()
                    if t == primary_name_text:
                        name_link = ln
                        break
                if name_link is None:
                    # Fallback: use the first /in/ link then
                    name_link = name_links[0]

                profile_url = name_link.get_attribute("href").split("?")[0]
                name_text = primary_name_text

                if not name_text or profile_url in seen_urls:
                    continue
                seen_urls.add(profile_url)

                # Extract headline from card text
                headline = ""
                try:
                    card_text = card.text
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                    # Find the name's index in lines
                    for idx, line in enumerate(lines):
                        if name_text in line and idx + 1 < len(lines):
                            # Next lines may be: degree badge (1st/2nd/3rd) then headline
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
                    "relevant": _company_relevant(headline, company),
                })
            except Exception:
                continue

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

    # Order company-matched connections first so the most likely valid recipient
    # for the job is messaged before any fallback candidates.
    relevant = [c for c in connections if c.get("relevant")]
    fallback = [c for c in connections if not c.get("relevant")]
    ordered = relevant + fallback
    print_lg(
        f"  Found {len(connections)} connection(s) at {company} "
        f"({len(relevant)} company-matched)"
    )
    return ordered


def resolve_all_connections(driver, referral_results: list[dict]) -> list[dict]:
    """
    For each unique company in referral results, resolve actual connection names
    via LinkedIn people search. Returns a flat list of enriched job dicts,
    one per (job, connection) pair with 'hr_name' and 'hr_link' filled in.
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
        connections = _resolve_connections_for_company(driver, company, max_pages=1)

        if not connections:
            # Still include the job with "Unknown" HR so it shows in results
            target = dict(sample_job)
            target["hr_name"] = "Unknown"
            target["hr_link"] = ""
            target["hr_headline"] = ""
            all_targets.append(target)
            continue

        for conn in connections[:2]:  # Max 2 connections per company to keep it manageable
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
    """Navigate to profile, click Message, handle shadow DOM, type + send.
    Returns (success: bool, reason: str).
    """
    if not hr_link:
        print_lg("No LinkedIn profile link for this contact. Skipping LinkedIn DM.")
        return False, "No profile link"

    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)
        print_lg(f"[DM] Loading profile: {hr_link}")

        # Click the "Message" button on the profile
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

        # Type the message
        editor.click()
        sleep(0.3)
        editor.send_keys(Keys.BACKSPACE)
        sleep(0.2)

        # Use JS for more reliable text insertion into contenteditable div
        driver.execute_script(
            "arguments[0].innerText = arguments[1];",
            editor, message
        )
        sleep(0.5)

        # Trigger input event so LinkedIn registers the text
        driver.execute_script("""
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        """, editor)
        sleep(1)

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

        # Check if button is disabled
        is_disabled = driver.execute_script(
            "return arguments[0].disabled || arguments[0].getAttribute('aria-disabled') === 'true';",
            send_btn
        )
        if is_disabled:
            print_lg("Send button is disabled — message may not have registered.")
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
        return driver.execute_script("""
            const sels = [
                ['connect',   'button[aria-label*="Connect"]'],
                ['message',   'button[aria-label*="Message"]'],
                ['pending',   'button[aria-label*="Pending"]'],
                ['following', 'button[aria-label*="Follow"]'],
            ];
            for (const [key, sel] of sels) {
                const el = document.querySelector(sel);
                if (el) {
                    const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                    // Ignore a "Following" count/lock variants that only mention Connect sideways
                    if (key === 'connect' && /follow|pending|requested|message/i.test(label)) continue;
                    return key;
                }
            }
            return '';
        """)
    except Exception:
        return ""


def _dry_probe_profile_action(driver, hr_link: str) -> str:
    """Read-only companion for dry-run: load a profile and detect which
    outreach action LinkedIn currently offers for it, without clicking
    anything and without sending."""
    if not hr_link:
        return ""
    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)
        action = _profile_action(driver)
        driver.get(original_url)
        return action
    except Exception:
        return ""


def _send_linkedin_connect_request(driver, hr_link: str, note: str) -> tuple[bool, str]:
    """Send a LinkedIn connection request with a personal note (no DM possible
    for non-connections on a free account). Assumes the profile is NOT already
    connected. Returns (success: bool, reason: str)."""
    if not hr_link:
        return False, "No profile link"

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

        # Find and click the Connect button
        btn = driver.execute_script("""
            const els = document.querySelectorAll('button[aria-label*="Connect"]');
            for (const el of els) {
                const label = (el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '');
                if (/follow|pending|requested|message/i.test(label)) continue;
                return el;
            }
            return null;
        """)
        if not btn:
            print_lg("[CONNECT] Could not find the Connect button.")
            driver.get(original_url)
            return False, "No Connect button"

        btn.click()
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

    try:
        original_url = driver.current_url
        driver.get(hr_link)
        sleep(randint(25, 45) * 0.1)

        action = _profile_action(driver)
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

    for i, job in enumerate(actionable):
        from datetime import datetime
        job["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        hr_name = job.get("hr_name", "there")
        title = job.get("title", "the role")
        company = job.get("company", "the company")
        print_lg(f"\n[{i+1}/{len(actionable)}] {hr_name} — {title} at {company}")

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
                _log_message_result(log_path, job, "LinkedIn", True)
            else:
                stats["linkedin_failed"] += 1
                reason = success[1] if isinstance(success, tuple) else ""
                _log_message_result(log_path, job, "LinkedIn", False, reason)

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
                else:
                    stats["gmail_failed"] += 1
                _log_message_result(log_path, job, "Gmail", success)
            else:
                print_lg("No email found for this contact. Skipping Gmail.")
                _log_message_result(log_path, job, "Gmail", False, "No email found")

            if gmail_count < referral_dm_max and i < len(actionable) - 1:
                delay = randint(int(referral_dm_delay * 0.8), int(referral_dm_delay * 1.2))
                print_lg(f"Waiting {delay}s before next message...")
                sleep(delay)

        # Stop if both channels hit their limits
        if linkedin_count >= referral_dm_max and gmail_count >= referral_dm_max:
            print_lg(f"\nReached max messages per channel ({referral_dm_max}). Stopping.")
            break

    print_lg(f"\n{'='*60}")
    print_lg(f"REFERRAL MESSAGING COMPLETE")
    print_lg(f"{'='*60}")
    print_lg(f"LinkedIn DMs sent: {stats['linkedin_sent']}")
    print_lg(f"LinkedIn DMs failed: {stats['linkedin_failed']}")
    print_lg(f"Gmails sent: {stats['gmail_sent']}")
    print_lg(f"Gmails failed: {stats['gmail_failed']}")
    print_lg(f"Skipped (no HR info): {stats['skipped']}")
    print_lg(f"Log saved to: {log_path}")
    print_lg(f"{'='*60}\n")

    if dry:
        print_lg(dry_run.summary())

    return stats
