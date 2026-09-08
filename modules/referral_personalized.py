'''
Curated personalized referral messaging (--send-personalized).

You hand the tool a list of people you want to reach (referral_targets.json),
it scrapes each person's profile, drafts a hyper-personalized, human-sounding
LinkedIn message with AI (when configured), and sends it via the proven DM /
connect-with-note pipeline. When AI is not configured or the draft fails it
falls back to the programmatic template used by --send-referrals.

Everything sends through the same battle-tested machinery as the discovery
mode: _normalize_profile_url, _profile_action, _send_linkedin_message_or_connect,
the license/daily-message gate, event tracking and the message CSV log.
'''

import os
import json

from time import sleep
from random import randint
from urllib.parse import quote

from selenium.webdriver.common.by import By

from modules import dry_run
from modules import events
from modules.dry_run import is_dry_run
from modules.helpers import print_lg
from modules.license import (
    can_send_referral, record_referral_message,
    referral_sent_for_job, record_referral_job_sent, referral_jobs_sent_total,
)
from modules.referral_messaging import (
    _normalize_profile_url,
    _profile_action,
    _compose_message,
    _send_linkedin_message_or_connect,
    _log_message_result,
    _parse_people_cards,
    USER_DATA,
)
from config.settings import (
    send_via_linkedin,
    linkedin_dm_template,
    linkedin_connect_note,
    referral_targets_file,
    referral_ai_draft,
    referral_personalized_delay,
    referral_target_count,
)
from config.personals import first_name, last_name


_PERSON_KEY_ALIASES = {
    "name": ("name", "hr_name", "person", "employee_name"),
    "profile_url": ("profile_url", "url", "hr_link", "profile", "linkedin"),
    "job_url": ("job_url", "link", "job_link", "posting_url"),
    "job_id": ("job_id", "jobId"),
    "title": ("title", "job_title", "role"),
    "company": ("company", "company_name"),
    "note": ("note", "hint", "context", "personal_note"),
}


def _pick(d: dict, *aliases):
    for a in aliases:
        v = d.get(a)
        if v:
            return v
    return None


def _target_path():
    if os.path.isabs(referral_targets_file):
        return referral_targets_file
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), referral_targets_file)


def _load_resume_context(max_chars: int = 700) -> str:
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resume_context.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        return text[:max_chars] if text else ""
    except (OSError, UnicodeDecodeError):
        return ""


def load_targets(path: str = None) -> list[dict]:
    """Load the curated target list from a JSON file shaped like:

        {"targets": [
            {"name": "Martina Santoro",
             "profile_url": "https://www.linkedin.com/in/martina-santoro",
             "job_url": "https://www.linkedin.com/jobs/view/4444967350",
             "title": "Senior Product Manager",
             "company": "Product Heroes",
             "note": "optional hint for the AI"},
        ]}

    Names only (no URL) are allowed — they get resolved by people search.
    Returns a normalized list of dicts with keys
    name, profile_url, job_url, title, company, note.
    """
    path = path or _target_path()
    if not os.path.isfile(path):
        print_lg(f"No {os.path.basename(path)} found. Create it with the people you want to message.")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print_lg(f"Could not read {path}: {e}")
        return []

    raw = data.get("targets", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        print_lg(f"{path} must contain a \"targets\" list.")
        return []

    targets = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = (_pick(item, *(_PERSON_KEY_ALIASES["name"])) or "").strip()
        if not name:
            continue
        targets.append({
            "name": name,
            "profile_url": _normalize_profile_url(_pick(item, *(_PERSON_KEY_ALIASES["profile_url"])) or ""),
            "job_url": _pick(item, *(_PERSON_KEY_ALIASES["job_url"])) or "",
            "job_id": (_pick(item, *(_PERSON_KEY_ALIASES["job_id"])) or "").strip(),
            "title": _pick(item, *(_PERSON_KEY_ALIASES["title"])) or "the open role",
            "company": _pick(item, *(_PERSON_KEY_ALIASES["company"])) or "",
            "note": (_pick(item, *(_PERSON_KEY_ALIASES["note"])) or "").strip(),
        })
    return targets


def _resolve_profile_by_name(driver, name: str, company: str = "") -> str:
    """People-search a person by exact name (network=F to prefer connections)
    and return the first profile URL, or '' if nothing resolves."""
    try:
        keywords = f'"{name}"' + (f" {company}" if company else "")
        url = (
            "https://www.linkedin.com/search/results/people/"
            f"?keywords={quote(keywords)}&network=%5B%22F%22%5D&origin=FACETED_SEARCH"
        )
        driver.get(url)
        sleep(4)
        cards = driver.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
        conns = _parse_people_cards(cards)
        if conns:
            return conns[0]["profile_url"]
    except Exception as e:
        print_lg(f"Could not resolve profile for {name}: {e}")
    return ""


def _scrape_profile(driver, profile_url: str) -> dict:
    """Load a person's profile and pull the text an AI needs to write a
    genuine message: name, headline and the first chunk of the profile body."""
    profile = {"name": "", "headline": "", "text": ""}
    if not profile_url:
        return profile
    try:
        driver.get(_normalize_profile_url(profile_url))
        sleep(4)
        text = driver.execute_script("""
            const main = document.querySelector('#main-content, main') || document;
            return (main.innerText || document.body.innerText || '')
                .replace(/\\n{2,}/g, '\\n')
                .slice(0, 4000);
        """) or ""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            profile["name"] = lines[0]
            profile["headline"] = lines[1] if len(lines) > 1 else ""
        profile["text"] = text
    except Exception as e:
        print_lg(f"Profile scrape failed for {profile_url}: {e}")
    return profile


def _ai_draft_message(client, profile: dict, job: dict) -> str:
    """Ask the configured AI client to write a natural referral-request DM.
    Returns the message body, or '' if AI is unavailable / fails."""
    if not client or not profile.get("text"):
        return ""

    user_summary = _load_resume_context()
    your_name = f"{first_name} {last_name}".strip() or (USER_DATA.get("your_name") or "")
    your_role = (USER_DATA.get("your_role") or "").strip() or "a professional"
    your_company = (USER_DATA.get("your_company") or "").strip() or "my company"

    job_link = job.get("job_url") or job.get("link") or ""
    prompt = f"""You are helping {your_name}, {your_role} at {your_company}, write a short, natural LinkedIn message asking a FIRST-DEGREE connection for a referral to one specific job.

WRITE LIKE A REAL PERSON, NOT AN AI:
- No emojis, no "hope you're doing well", no weak openers, no corporate buzzwords.
- 80 to 130 words. Plain paragraphs, no bullet lists.
- Reference ONE or TWO genuine, specific things about the person from their profile below (real roles/projects/company). Never invent facts.
- Make ONE clear, low-pressure ask: would they be open to referring you for this exact role. Put the job link on its own line at the end.
- Sign off with your name: {your_name}

PERSON'S PROFILE (from their LinkedIn page):
{profile['text']}

JOB THEY ARE BEING ASKED ABOUT:
Title: {job.get('title', 'the open role')}
Company: {job.get('company', '')}
Link: {job_link}

EXTRA CONTEXT YOU MAY TIE IN (only if it lets you be more specific and truthful):
{user_summary or '(none available — rely on your own role/company above)'}

PERSONAL HINT FROM THE USER (optional, follow it if present):
{job.get('note') or '(none)'}

Now write ONLY the message, as plain text. No preface, no quotes around it."""

    try:
        response = client.model.invoke(prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        text = str(content or "").strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1].strip()
        return text[:1200]
    except Exception as e:
        print_lg(f"AI draft failed: {e}")
        return ""


def _compose_personalized(client, profile: dict, job: dict) -> str:
    """AI-personalized message when available and enabled, else programmatic."""
    if referral_ai_draft:
        draft = _ai_draft_message(client, profile, job)
        if draft:
            print_lg(f"[AI] Drafted personalized message ({len(draft)} chars)")
            return draft
        print_lg("[AI] No usable draft — falling back to programmatic template.")
    return _compose_message(linkedin_dm_template, job)


def send_personalized_messages(driver, targets: list[dict] = None, client=None) -> dict:
    """Send a curated list of personalized referral messages.

    - Resolves any target lacking a profile URL via people search.
    - Scrapes the profile, drafts a message (AI if available, else template).
    - Routes via the proven DM / connect-with-note pipeline.
    - Honors the license daily-message gate, event tracking and the CSV log.
    """
    stats = {"linkedin_sent": 0, "linkedin_failed": 0, "skipped": 0}
    dry = is_dry_run()
    if targets is None:
        targets = load_targets()
    targets = [t for t in targets if t]

    print_lg("=" * 60)
    print_lg("PERSONALIZED REFERRAL MESSAGING")
    print_lg(f"Targets: {len(targets)}   |  AI drafting: {'ON' if (client and referral_ai_draft) else 'OFF (template fallback)'}   |  Dry run: {dry}")
    print_lg("=" * 60)
    if not targets:
        print_lg("No targets to message.")
        return stats

    run_sent_keys = set()

    for i, target in enumerate(targets):
        name = target["name"]
        hr_link = target.get("profile_url") or ""
        job = {
            "timestamp": "",
            "job_id": target.get("job_id") or "",
            "title": target.get("title") or "the open role",
            "company": target.get("company") or "",
            "hr_name": name,
            "link": target.get("job_url") or "",
            "note": target.get("note") or "",
        }

        # One job = one referral. Key by job_id when present, else the person's
        # profile URL, so no job (or person) is messaged twice across runs.
        job_key = str(job["job_id"] or "").strip() or hr_link
        if job_key and (job_key in run_sent_keys or referral_sent_for_job(job_key)):
            print_lg(f"\n[{i + 1}/{len(targets)}] {name} — {job['title']} at {job['company']} (SKIPPED: referral already sent for this job/person)")
            stats["skipped"] += 1
            continue

        print_lg(f"\n[{i + 1}/{len(targets)}] {name} — {job['title']} at {job['company']}")
        if not hr_link:
            print_lg("  No profile URL given — resolving by name via people search...")
            hr_link = _resolve_profile_by_name(driver, name, job["company"])
            if not hr_link:
                print_lg("  Could not resolve a profile. Skipping this target.")
                stats["skipped"] += 1
                continue
            target["profile_url"] = hr_link

        profile = _scrape_profile(driver, hr_link)
        if not profile.get("text"):
            print_lg("  Profile scrape came back empty. Skipping this target.")
            stats["skipped"] += 1
            continue

        message = _compose_personalized(client, profile, job)
        connect_note = _compose_message(linkedin_connect_note, job)

        if dry:
            action = _profile_action(driver)
            print_lg(f"\n[DRY RUN] {'-' * 54}")
            print_lg(f"{name} — {job['title']} at {job['company']}")
            print_lg(f"Profile: {hr_link}")
            print_lg(f"Available action: {action or 'none'}")
            if action == "message":
                print_lg("Route: LinkedIn DM (already connected). Would send:")
                print_lg(message)
                dry_run.count("referral_dm")
            elif action == "connect":
                print_lg("Route: connection request with note. Would send:")
                print_lg(connect_note)
                dry_run.count("referral_connect")
            else:
                print_lg(f"Route: {action or 'no Message/Connect button'}. Would be skipped.")
                stats["skipped"] += 1
            print_lg(f"[DRY RUN] NOT SENDING ANYTHING. {'-' * 10}")
            continue

        if not send_via_linkedin:
            print_lg("  LinkedIn DM channel is disabled (send_via_linkedin = False). Skipping.")
            stats["skipped"] += 1
            continue

        # License gate: respect the daily message allowance.
        if not can_send_referral():
            from modules.license import referral_msg_remaining
            print_lg(f"LICENSE: Referral message daily limit reached ({referral_msg_remaining()} left). Stopping.")
            break

        events.emit("REFERRAL_SEND_ATTEMPTED", hr=name, company=job["company"], title=job["title"], job_id=job.get("job_id", ""))
        print_lg("\n--- LinkedIn DM / Connect ---")
        print_lg(f"Message:\n{message}\n")
        success = _send_linkedin_message_or_connect(driver, hr_link, message, connect_note)
        sent = (success[0] if isinstance(success, tuple) else success)
        if sent:
            stats["linkedin_sent"] += 1
            record_referral_message()
            record_referral_job_sent(job_key, job)
            if job_key:
                run_sent_keys.add(job_key)
            _log_message_result(
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "referral_message_log.csv"),
                job, "LinkedIn", True,
            )
            events.emit("REFERRAL_SEND_SUCCESS", channel="linkedin", hr=name, company=job["company"], job_id=job.get("job_id", ""))
        else:
            stats["linkedin_failed"] += 1
            reason = success[1] if isinstance(success, tuple) else ""
            _log_message_result(
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "referral_message_log.csv"),
                job, "LinkedIn", False, reason,
            )
            events.emit("REFERRAL_SEND_FAILED", channel="linkedin", hr=name, company=job["company"], reason=str(reason)[:200], job_id=job.get("job_id", ""))
        if sent and os.environ.get("AJA_STOP_AFTER_FIRST_SEND"):
            print_lg("Stopping after first successful send (AJA_STOP_AFTER_FIRST_SEND).")
            break
        if i < len(targets) - 1:
            delay = randint(int(referral_personalized_delay * 0.8), int(referral_personalized_delay * 1.2))
            print_lg(f"Waiting {delay}s before the next message...")
            sleep(delay)

    new_distinct = len(run_sent_keys)
    try:
        lifetime_total = referral_jobs_sent_total()
    except Exception:
        lifetime_total = new_distinct
    shortfall = max(0, referral_target_count - lifetime_total)

    print_lg("\n" + "=" * 60)
    print_lg("PERSONALIZED REFERRAL MESSAGING COMPLETE")
    print_lg(f"LinkedIn DMs sent: {stats['linkedin_sent']}")
    print_lg(f"LinkedIn DMs failed: {stats['linkedin_failed']}")
    print_lg(f"Skipped: {stats['skipped']}")
    print_lg(f"Distinct jobs messaged this run: {new_distinct}")
    print_lg(f"Distinct jobs messaged (all-time): {lifetime_total}")
    if shortfall:
        print_lg(f"Target: {referral_target_count} referrals - {shortfall} short. Add more targets to referral_targets.json and re-run to close the gap.")
    else:
        print_lg(f"Target: {referral_target_count} referrals - met. All {referral_target_count} referral slots reached.")
    print_lg("=" * 60)
    if dry:
        print_lg(dry_run.summary())
    return stats