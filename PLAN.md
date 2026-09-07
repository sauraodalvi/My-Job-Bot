# Plan: Add Dual-Channel Referral Messaging (LinkedIn DM + Gmail)

## Context
The referral finder identifies jobs where the user has LinkedIn connections but can't send messages. The user wants automated referral outreach via **both LinkedIn DM and Gmail**, using HAPPPY-style templates. Currently the bot only applies to jobs and scans for referrals — no messaging exists.

## Goal
Add automated referral messaging that:
1. Collects HR/recruiter info (name, profile URL, email if available) from job postings
2. Sends personalized referral requests via LinkedIn DM **and** Gmail
3. Uses HAPPPY-style templates with variable substitution
4. Runs as `--send-referrals` mode or integrated into referral flow
5. Controlled via config settings and the web control panel

## Architecture

### Dual-Channel Flow
```
referral scan → collect HR info (name + profile URL + email)
    ├── LinkedIn DM:  profile → click Message → shadow DOM → type → send
    └── Gmail:        compose URL (?to=EMAIL&su=SUBJECT&body=BODY&tf=cm) → send
log both results to CSV
```

### Template Variables (HAPPPY format)
| Variable | Source |
|---|---|
| `{{outreachEmployeeName}}` | HR name from hirer card |
| `{{jobTitle}}` | Job title from referral results |
| `{{companyName}}` | Company name from referral results |
| `{{jobLink}}` | LinkedIn job URL |
| `{{yourName}}` | From personals config |
| `{{yourRole}}` | From personals `work_role` config |
| `{{yourCompany}}` | From personals `work_company` config |
| `{{yourLinkedIn}}` | From questions `linkedIn` config |
| `{{yourPortfolio}}` | From questions `website` config |

### Two Separate Templates
- **LinkedIn DM template** — shorter, conversational (LinkedIn DMs have a casual norm)
- **Gmail template** — includes subject line, more formal, longer body

## Implementation Steps

### Step 1: Add config settings (`config/settings.py`)
Uncomment the "Upcoming features" section and add:
```python
# >>>>>>>>>>> REFERRAL MESSAGING <<<<<<<<<<<
send_referral_dms = False              # Master switch for auto-sending referral messages
send_via_linkedin = True               # Send via LinkedIn DM
send_via_gmail = True                  # Send via Gmail email

# LinkedIn DM template
linkedin_dm_template = """Hi {employee_name},

I'm {your_name}, {your_role} at {your_company}. I'm reaching out because the {job_title} role at {company_name} lines up closely with my experience.

Would you be open to referring me? Here's the job: {job_link}

Best regards,
{your_name}"""

# Gmail template (subject + body)
gmail_subject = "Applying for {job_title} at {company_name} – can you help with referral?"
gmail_body = """Hi {employee_name},

I'm {your_name}, currently a {your_role} at {your_company} with about 3 years of hands-on experience delivering customer-facing solutions. I'm reaching out because the {job_title} role at {company_name} lines up closely with the way I work: ship fast, learn even faster, and solve real user problems with pragmatic AI and automation.

What I bring: emerging talent with rapid learning potential, plus deep, practical expertise in CLI and Zapier. I've built internal CLIs that streamline developer workflows, automated complex cross-app processes with Zapier and Make, and used Grok and Claude to power robust agentic and retrieval-driven features. In a forward-deployed capacity, I translate ambiguous requirements into shipped solutions—exactly the kind of bias to action and systems thinking a strong {job_title} at {company_name} needs.

I'm particularly excited about {company_name} because of its bar for execution and learning culture. I thrive in environments where customer impact, thoughtful tooling, and reliable automation matter.

Would you be open to referring me? If helpful, you can skim my background here as well: {your_linkedin}

Here is the link to the job: {job_link}

Best regards,
{your_name}
{your_portfolio}"""

referral_dm_delay = 45                 # Seconds between messages (anti-detection)
referral_dm_max = 10                   # Max messages per run per channel
```

### Step 2: Add config schema (`config_schema.py`)
Add a new **"Referral Messaging"** section to `SCHEMA`:
- `send_referral_dms` (bool) — master switch
- `send_via_linkedin` (bool) — LinkedIn DM channel
- `send_via_gmail` (bool) — Gmail channel
- `linkedin_dm_template` (textarea) — LinkedIn message
- `gmail_subject` (text) — Gmail subject line
- `gmail_body` (textarea) — Gmail body
- `referral_dm_delay` (number) — delay between messages
- `referral_dm_max` (number) — max per run

### Step 3: Enhance referral finder HR extraction (`runAiBot.py`)
Modify `_parse_referral_card()` to also extract from the job card:
- `hr_name` — from `hirer-card__hirer-information` span text
- `hr_link` — from `hirer-card__hirer-information` anchor href

Updated data structure:
```python
{
    "job_id": "...", "title": "...", "company": "...",
    "connection_count": 5, "link": "...",
    "hr_name": "John Smith",           # NEW
    "hr_link": "https://linkedin.com/in/johnsmith"  # NEW
}
```

### Step 4: Create messaging module (`modules/referral_messaging.py`)
New file with dual-channel sending:

```python
def send_referral_messages(results, config) -> dict:
    """Main entry: send via LinkedIn DM and/or Gmail for each HR contact."""
    
def _compose_from_template(template: str, job: dict, user: dict) -> str:
    """Fill {variable} placeholders with job + user data."""

def _send_linkedin_dm(driver, hr_link: str, message: str) -> bool:
    """Navigate to profile → click Message → handle shadow DOM → type → send."""

def _send_gmail(driver, hr_email: str, subject: str, body: str) -> bool:
    """Open Gmail compose URL with pre-filled params → click Send."""

def _try_extract_email(driver, profile_url: str) -> str | None:
    """Visit profile → open Contact Info → regex-scan for email. Return None if not found."""

def _log_message_result(job: dict, channel: str, success: bool, error=None):
    """Append to referral_message_log.csv."""
```

### LinkedIn DM Technical Approach
1. `driver.get(hr_link)` — navigate to HR person's profile
2. `buffer(referral_dm_delay)` — randomized human-like delay
3. Click "Message" button: `//button[contains(@aria-label, 'Message')]`
4. **Shadow DOM piercing** (LinkedIn 2025+ moved compose overlay into `#interop-outlet` shadow root):
   ```python
   editor = driver.execute_script("""
       const host = document.querySelector('#interop-outlet');
       if (host && host.shadowRoot)
           return host.shadowRoot.querySelector('.msg-form__contenteditable');
       return document.querySelector('div.msg-form__contenteditable');
   """)
   ```
5. Type message: `editor.send_keys(Keys.BACKSPACE)` then `editor.send_keys(message)`
6. Click Send (also in shadow DOM):
   ```python
   send_btn = driver.execute_script("""
       const host = document.querySelector('#interop-outlet');
       if (host && host.shadowRoot)
           return host.shadowRoot.querySelector('.msg-form__send-button');
       return document.querySelector('button.msg-form__send-button');
   """)
   send_btn.click()
   ```
7. Wait for "Message sent" confirmation, return success/failure

### Gmail Technical Approach
1. Build compose URL with pre-filled params:
   ```python
   from urllib.parse import urlencode
   params = urlencode({'to': email, 'su': subject, 'body': body, 'tf': 'cm'})
   url = f"https://mail.google.com/mail/u/0/?{params}"
   ```
2. `driver.get(url)` — opens Gmail compose modal (requires logged-in session)
3. Wait for compose dialog: `driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"]')`
4. Verify pre-filled fields are populated
5. Click Send: `driver.find_element(By.CSS_SELECTOR, '[role="button"][aria-label^="Send"]')`
6. Wait for "Message sent" toast confirmation

### Email Extraction (`_try_extract_email`)
1. Navigate to HR profile URL
2. Click Contact Info link: `#top-card-text-details-contact-info` or `//a[contains(@href,'overlay/contact-info')]`
3. Wait for modal, extract text, regex-scan for email pattern
4. Also scan the About/Experience sections as fallback
5. Return email or `None` (most non-connections won't have visible emails)

### Step 5: Add `--send-referrals` CLI mode (`runAiBot.py`)
In `main()`:
```python
if "--send-referrals" in sys.argv:
    results = load_referral_results()
    send_referral_messages(results, config)
    # print summary, log to CSV
```
Also supports `--referral --send-referrals` for scan + send in one run (implemented: `_full_referral_command()` in `app.py`, `POST /api/referral/full`, "Run Referral Scan + Send (one-click)" button in the Referrals tab of the control panel; the scan runs first, then the send block reuses the SAME authenticated session — no relogin).

### Step 6: Add API endpoints (`app.py`)
```python
@app.route('/api/referral/send', methods=['POST'])
def start_referral_send():
    """Start the dual-channel DM sender as a subprocess."""

@app.route('/api/referral/send/status')
def referral_send_status():
    """Check if message sending is in progress."""
```

### Step 7: Update control panel UI (`templates/control_panel.html`)
Add to the Referrals tab:
- **"Send referral messages"** button (next to existing "Find jobs where I have connections")
- **Channel toggles**: LinkedIn DM on/off, Gmail on/off
- **Template editor**: Editable textareas for LinkedIn DM template and Gmail subject+body
- **Preview panel**: Shows composed message before sending
- **Dry-run toggle**: Preview without actually sending
- **Status log**: Shows sent/failed/skipped counts per channel
- **Message log table**: History of sent messages with timestamps

## Files to Modify
| File | Change |
|---|---|
| `config/settings.py` | Add 10 referral messaging settings (templates, toggles, delays) |
| `config_schema.py` | Add "Referral Messaging" section with 8 fields |
| `runAiBot.py` | Enhance referral finder HR extraction, add `--send-referrals` mode |
| `modules/referral_messaging.py` | **NEW** — dual-channel messaging (LinkedIn DM + Gmail) |
| `app.py` | Add `/api/referral/send` + `/api/referral/send/status` endpoints |
| `templates/control_panel.html` | Add messaging UI, template editor, channel toggles, status log |
| `user_config.json` | Gets new keys on next control panel save |

## Safety Measures
- **45-60s random delay** between messages (both channels) — anti-detection
- **Max 10 messages per channel per run** — avoid rate limits
- **Dry-run by default** — first run previews messages without sending
- **No headless mode** — DMs/email always run with visible browser
- **Gmail uses persistent Chrome profile** — never automate Google login
- **LinkedIn uses undetected-chromedriver** — already configured in the bot
- **Every message logged** to `referral_message_log.csv` with timestamp, recipient, channel, status
- **Gmail daily limit awareness**: free accounts cap at ~500/day; bot stays well under

## Verification
1. `python runAiBot.py --referral` → scan saves results with HR info
2. `python runAiBot.py --send-referrals` (dry-run) → previews messages for both channels
3. Enable `send_referral_dms` in config, run again → sends actual messages
4. Check `referral_message_log.csv` for results
5. Verify LinkedIn and Gmail accounts have no restrictions

## Known blockers (session / authentication)
- **DMs need a real LinkedIn session.** The guest profile (`safe_mode=true`) has no session:
  connection profiles render the "related people" fallback with **no Message button**, so all
  DMs fail with "No Message button"; Gmail also can't work (no email → "No email found").
- **No local Chrome profile holds a LinkedIn session.** Inspected all 3 profiles
  (`Default`, `Profile 1`, `Profile 2`) — only `Profile 2` had cookies, and only tracking
  cookies (`bcookie`, `li_sugr`, ...), no `li_at`/`JSESSIONID` session cookie. So there is
  currently no persisted login to reuse.
- **Automated guest login is blocked.** `login_LN()` filled no fields ("Couldn't find username
  field") yet `is_logged_in_LN()` falsely returned True (URL heuristic). The resulting session
  is NOT authenticated, so the Message button still never appears.
- **Real-profile attach fails.** undetected-chromedriver cannot attach to the live
  `%LOCALAPPDATA%\Google\Chrome\User Data` dir (`SessionNotCreatedException: cannot connect
  to chrome` even with Chrome closed). Copying a profile to a temp `user-data-dir` **does**
  work (with `version_main=151`), but the copies aren't logged into LinkedIn (no session cookies).
- **Workaround to unblock DMs:** use the guest profile (attaches reliably), then have the USER
  log into LinkedIn **manually in the visible browser** (LinkedIn requires manual interaction /
  captcha for real accounts anyway). Once the session is live, the bot resolves connections and
  sends DMs. `runAiBot.py` now calls `login_LN()` at the start of `--send-referrals`, but
  `is_logged_in_LN()` is unreliable, so manual confirmation is the safe gate.
- **Chrome version pinning:** installed Chrome is v151; undetected-chromedriver defaults to the
  latest driver (v152) and fails. Always pass `version_main=151` (the bot does this via
  `get_chrome_major_version()`).
