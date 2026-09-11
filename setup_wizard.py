import sys
import os
import json
import subprocess
import datetime
import tempfile

import tkinter as tk
from tkinter import filedialog, messagebox

import setup_flow

ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
CONFIG_PATH = setup_flow.USER_CONFIG_PATH
START_BAT = os.path.join(ROOT, "start_bot.bat")
APP_EXE = os.path.join(ROOT, "AutoJobApplier.exe")


def run_target() -> str:
    return APP_EXE if os.path.exists(APP_EXE) else START_BAT
GEMINI_KEY_URL = "https://aistudio.google.com/apikey"
GEMINI_VIDEO_URL = "https://www.youtube.com/results?search_query=how+to+get+gemini+api+key+aistudio"

GEMINI_MODEL = "gemini-2.5-flash"

APPLY_AT_LOGON_TASK = "AutoJobApplier_AtLogon"
APPLY_DAILY_TASK = "AutoJobApplier_Daily"


def load_existing_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_config(
    username, password, gemini_key,
    current_city, years_of_experience,
    resume_path, website, linkedin_url,
    search_terms, locations, current_experience, job_types,
    existing=None,
    first_name="", last_name="", license_key="",
):
    existing = existing or {}
    existing = json.loads(json.dumps(existing))

    secrets = dict(existing.get("secrets", {}))
    secrets.update({
        "username": (username or "").strip(),
        "password": password or secrets.get("password", ""),
        "gumroad_license_key": (license_key or "").strip(),
    })

    gemini_key = (gemini_key or "").strip()
    if gemini_key:
        secrets.update({
            "use_AI": True,
            "ai_provider": "gemini",
            "llm_model": GEMINI_MODEL,
            "llm_api_key": gemini_key,
            "gemini_api_key": gemini_key,
        })
    elif secrets.get("use_AI"):
        # An AI provider is already configured (OpenRouter / OpenAI / DeepSeek).
        # Leave it untouched - a blank Gemini key means "don't change my AI".
        pass
    else:
        secrets.update({
            "use_AI": False,
            "ai_provider": "gemini",
            "llm_model": GEMINI_MODEL,
            "llm_api_key": "",
        })

    personals = dict(existing.get("personals", {}))
    personals["current_city"] = (current_city or "").strip()
    if (first_name or "").strip():
        personals["first_name"] = (first_name or "").strip()
    else:
        personals.setdefault("first_name", "")
    if "middle_name" not in personals:
        personals["middle_name"] = ""
    if (last_name or "").strip():
        personals["last_name"] = (last_name or "").strip()
    else:
        personals.setdefault("last_name", "")

    questions = dict(existing.get("questions", {}))
    questions.update({
        "years_of_experience": (years_of_experience or "").strip(),
        "default_resume_path": (resume_path or "").strip(),
        "website": (website or "").strip(),
        "linkedIn": (linkedin_url or "").strip(),
    })

    terms = [t.strip() for t in (search_terms or "").splitlines() if t.strip()]
    locs = [l.strip() for l in (locations or "").splitlines() if l.strip()]

    search = dict(existing.get("search", {}))
    search.update({
        "search_terms": terms,
        "search_location": ", ".join(locs),
        "current_experience": _safe_current_experience(current_experience, search.get("current_experience", 4)),
    })
    if job_types:
        search["job_type"] = [j.strip() for j in job_types.split(",") if j.strip()]

    return {
        "secrets": secrets,
        "personals": personals,
        "questions": questions,
        "search": search,
    }


def _safe_current_experience(raw, default):
    '''Parse the experience-years box without crashing on a typo like "12.34.56".'''
    try:
        default = int(float(default))
    except (TypeError, ValueError):
        default = 4
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        return default
    return int(value) if value >= 0 else default


def write_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_PATH, 0o600)
    return CONFIG_PATH


def create_shortcut(name, target, workdir):
    desktop = get_desktop_path()
    if not desktop:
        return None
    lnk = os.path.join(desktop, name + ".lnk")
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%r);"
        "$s.TargetPath=%r;$s.WorkingDirectory=%r;$s.IconLocation=%r;$s.Save()"
        % (lnk, target, workdir, sys.executable + ",0")
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
    return lnk


def get_desktop_path():
    ps = "[Environment]::GetFolderPath('Desktop')"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True)
    line = r.stdout.strip().splitlines()
    return line[0] if line else None


def register_task(name, command, trigger):
    tr = "cmd /c \"\"%s\"" % command.replace("&", "^&")
    args = [
        "schtasks", "/Create", "/F",
        "/TN", name,
        "/TR", tr,
        "/SC", trigger["type"],
    ]
    if trigger.get("start"):
        args += ["/ST", trigger["start"]]
    if trigger.get("logon"):
        args += ["/RL", "LIMITED"]
    return subprocess.run(args, capture_output=True, text=True)


def chrome_installed():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    return any(os.path.exists(p) for p in candidates)


def flow_page_ids():
    '''The ids of the primary (quick) flow pages, straight from the shared declaration.'''
    return ["welcome"] + [s["id"] for s in setup_flow.STEPS] + ["review", "allset"]


class Wizard:
    def __init__(self, root, initial_step=0):
        self.initial_step = initial_step
        self.root = root
        self.existing = load_existing_config()
        self.secrets = self.existing.get("secrets", {})
        self.personals = self.existing.get("personals", {})
        self.questions = self.existing.get("questions", {})
        self.search = self.existing.get("search", {})
        self.prefill = setup_flow.prefill()

        self.var_username = tk.StringVar(value=self.secrets.get("username", ""))
        self.var_password = tk.StringVar(value=self.secrets.get("password", ""))
        self.var_gemini = tk.StringVar(value=self.secrets.get("llm_api_key", ""))
        self.var_first = tk.StringVar(value=self.personals.get("first_name", ""))
        self.var_last = tk.StringVar(value=self.personals.get("last_name", ""))
        self.var_city = tk.StringVar(value=self.personals.get("current_city", ""))
        self.var_years = tk.StringVar(value=self.questions.get("years_of_experience", ""))
        self.var_resume = tk.StringVar(value=self.prefill["resume"].get("resume_path", ""))
        self.var_website = tk.StringVar(value=self.questions.get("website", ""))
        self.var_linkedin = tk.StringVar(value=self.questions.get("linkedIn", ""))
        self.var_terms = tk.StringVar(value="\n".join(self.search.get("search_terms", [])))
        self.var_locations = tk.StringVar(value="\n".join(self.search.get("search_location", "").split(", ")) if self.search.get("search_location") else "")
        self.var_experience = tk.StringVar(value=str(self.search.get("current_experience", 4)))
        self.var_jobtype = tk.StringVar(value=", ".join(self.search.get("job_type", ["Full-time"])))
        self.var_license = tk.StringVar(value=self.secrets.get("gumroad_license_key", ""))
        self.var_logon = tk.BooleanVar(value=True)
        self.var_daily = tk.BooleanVar(value=True)
        self.var_time = tk.StringVar(value="09:00")
        self.var_shortcut = tk.BooleanVar(value=True)
        self.var_wants = tk.StringVar(value=self.prefill["wants"].get("sentence", ""))
        self.var_ask = tk.BooleanVar(value=self.prefill["policy"].get("ask_before_sending", True))

        self.terms_widget = None
        self.locs_widget = None
        self.in_advanced = False
        self.last_quick = 0
        self.pages = []
        self.current = 0
        self.report = []

        self.build_welcome()
        for s in setup_flow.STEPS:
            self.build_step_page(s)
        self.build_review()
        self.build_allset()

        # Advanced (legacy) pages - reachable behind the "Advanced" toggle.
        self.build_account()
        self.build_ai()
        self.build_jobs()
        self.build_resume()
        self.build_unlock()
        self.build_schedule()

        for page in self.pages:
            page.grid_forget()
        self.show_page(self._map_initial(initial_step))

    # ------------------------------------------------------------------
    # Page registry / navigation
    # ------------------------------------------------------------------
    def add_page(self, page):
        self.pages.append(page)

    @property
    def quick_last(self):
        # Primary flow = welcome..allset (no advanced pages).
        return len(flow_page_ids()) - 1

    # Advanced pages (behind the "Advanced" toggle), in build order.
    advanced_ids = ["account", "ai", "jobs", "resume", "unlock", "schedule"]

    def _map_initial(self, initial):
        '''Resolve the page to open on startup. Accepts a page id string
        ("welcome", "unlock", ...) or the legacy 7-page wizard index
        (1-6 = the advanced pages, 7 = All set).'''
        if isinstance(initial, str):
            quick_ids = flow_page_ids()
            if initial in quick_ids:
                return quick_ids.index(initial)
            if initial in self.advanced_ids:
                self.in_advanced = True
                return self.quick_last + 1 + self.advanced_ids.index(initial)
            return 0
        if initial == 0:
            return 0
        if 1 <= initial <= 6:
            self.in_advanced = True
            return self.quick_last + 1 + (initial - 1)
        if initial == 7:
            return self.quick_last
        return 0

    def show_page(self, idx):
        for p in self.pages:
            p.grid_forget()
        page = self.pages[idx]
        page.grid(row=0, column=0, sticky="nsew")
        self.current = idx
        self.in_advanced = idx > self.quick_last
        if not self.in_advanced:
            self.last_quick = idx
        self.update_nav()

    def update_nav(self):
        pass

    def quick_pages(self):
        return self.pages[: self.quick_last + 1]

    def advanced_pages(self):
        return self.pages[self.quick_last + 1:]

    # ----- page: welcome -----
    def build_welcome(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text=setup_flow.FLOW_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(f, text=setup_flow.WELCOME_SENTENCE, font=("Segoe UI", 10), wraplength=700, justify="left").pack(anchor="w", pady=(2, 14))

        tk.Label(f, text="What this does", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        for line in setup_flow.WELCOME_NOTES:
            tk.Label(f, text="- " + line, font=("Segoe UI", 10), justify="left").pack(anchor="w", padx=6)

        tk.Label(f, text="", font=("Segoe UI", 6)).pack()
        chrome = "Google Chrome: INSTALLED" if chrome_installed() else "Google Chrome: NOT DETECTED"
        color = "#1a7f37" if chrome_installed() else "#d1242f"
        tk.Label(f, text=chrome, font=("Segoe UI", 10, "bold"), fg=color).pack(anchor="w")

        tk.Label(f, text="Everything you enter is stored ONLY on this PC in user_config.json.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(12, 4))
        tk.Label(f, text="Never share that file. Use at your own risk against LinkedIn guidelines.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w")

    # ----- primary flow step pages (from the shared declaration) -----
    def build_step_page(self, step_def):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text=step_def["title"], font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text=step_def["why"], font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        for field_def in step_def["fields"]:
            label = field_def["label"]
            if field_def.get("required"):
                label = label + "  *"
            tk.Label(f, text=label, font=("Segoe UI", 9, "bold"),
                     fg="#d1242f" if field_def.get("required") else "#333").pack(anchor="w", pady=(10, 2))
            widget = self._build_field(step_def, f, field_def)
            if widget is not None:
                setattr(self, "_var_%s_%s" % (step_def["id"], field_def["key"]), widget)
            if field_def.get("help"):
                tk.Label(f, text=field_def["help"], font=("Segoe UI", 9), fg="#666", wraplength=700, justify="left").pack(anchor="w", pady=(0, 2))

        if step_def["id"] == "resume":
            self.build_resume_detect_ui(f)
        elif step_def["id"] == "wants":
            self.build_wants_parse_ui(f)

    def build_resume_detect_ui(self, parent):
        '''The trust moment: "Detect profile" shows what the tool read from the
        chosen resume, live on the resume step.'''
        self._resume_detect_text = tk.StringVar(
            value="Pick a resume file and click Detect to see what I read from it.")
        self._resume_detect_ok = False
        row = tk.Frame(parent)
        row.pack(anchor="w", pady=(6, 0))
        tk.Button(row, text="Detect profile", font=("Segoe UI", 9),
                  command=self.refresh_resume_detect).pack(side="left")
        self._resume_detect_label = tk.Label(row, textvariable=self._resume_detect_text,
                                             font=("Segoe UI", 10), fg="#666",
                                             wraplength=620, justify="left")
        self._resume_detect_label.pack(side="left", padx=(10, 0))

    def refresh_resume_detect(self):
        path = self._var_resume_resume_path.get()
        text, ok = setup_flow.describe_resume_path(path)
        self._resume_detect_text.set(text or "Pick a resume file and click Detect to see what I read from it.")
        self._resume_detect_ok = ok
        self._resume_detect_label.configure(fg="#1a7f37" if ok else "#a16207")

    def build_wants_parse_ui(self, parent):
        '''Inline one-question tooling for the wants step: the Saved Search is
        parsed from the sentence; if AI is off or the input is unclear, the
        missing pieces are asked ONE at a time in plain words.'''
        self._wants_state = None
        self._wants_parsed = None
        self._wants_sentence_answered = None

        self._wants_parse_box = tk.Frame(parent)
        self._wants_parse_box.pack(fill="x", pady=(14, 0))
        self._wants_parse_label = tk.Label(
            self._wants_parse_box,
            text="I'll figure out job titles, locations, pay and recency from this sentence.",
            font=("Segoe UI", 10), fg="#666", wraplength=700, justify="left")
        self._wants_parse_label.pack(anchor="w")

        self._wants_reply_row = tk.Frame(self._wants_parse_box)
        self._wants_reply_var = tk.StringVar()
        tk.Entry(self._wants_reply_row, textvariable=self._wants_reply_var,
                 font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        tk.Button(self._wants_reply_row, text="Answer", font=("Segoe UI", 10),
                  command=self._wants_reply).pack(side="left", padx=(8, 0))

    def _wants_reply(self):
        self.refresh_wants_parse()

    def refresh_wants_parse(self):
        '''Parse the wants sentence for display on the review screen and drive
        the one-at-a-time guidance when a piece is missing.'''
        from modules.search_parse import next_state as parse_sentence
        widget = getattr(self, "_var_wants_sentence", None)
        sentence = (widget.get("1.0", "end").strip() if widget is not None
                    else self.var_wants.get() or "")
        if not sentence:
            self._wants_state = None
            self._wants_parsed = None
            self._wants_sentence_answered = None
            self._wants_confirmation = None
            self._wants_parse_label.configure(
                text="I'll figure out job titles, locations, pay and recency from this sentence.",
                fg="#666")
            self._wants_reply_row.pack_forget()
            return
        self._wants_sentence_answered = sentence
        if self._wants_state is not None:
            # Complete the active one-question conversation with the reply.
            out = parse_sentence(sentence, reply=self._wants_reply_var.get(), state=self._wants_state)
        elif self._wants_parsed and self._wants_confirmation:
            # Same sentence already parsed - just restate the confirmation.
            self._wants_parse_label.configure(
                text="I understood: " + self._wants_confirmation, fg="#1a7f37")
            self._wants_reply_row.pack_forget()
            return
        else:
            out = parse_sentence(sentence)
        self._apply_wants_outcome(out)

    def _apply_wants_outcome(self, out):
        if out.get("status") == "answered":
            self._wants_parsed = out.get("wants_answers", {}).get("parsed")
            self._wants_confirmation = out.get("confirmation", "")
            self._wants_state = None
            self._wants_reply_row.pack_forget()
            self._wants_parse_label.configure(
                text="I understood: " + self._wants_confirmation,
                fg="#1a7f37")
        else:
            self._wants_state = out.get("guided_state")
            self._wants_parse_label.configure(
                text="One quick question: " + out.get("question", ""),
                fg="#a16207")
            self._wants_reply_var.set("")
            self._wants_reply_row.pack(fill="x", pady=(8, 0))

    def _build_field(self, step_def, parent, field_def):
        ftype = field_def["type"]
        key = field_def["key"]
        saved = (self.prefill.get(step_def["id"]) or {}).get(key, "")
        if ftype in ("text", "password"):
            var = tk.StringVar(value=saved)
            if field_def.get("pick"):
                row = tk.Frame(parent)
                row.pack(fill="x")
                tk.Entry(row, textvariable=var, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
                tk.Button(row, text="Browse...", font=("Segoe UI", 10), command=lambda: self.pick_resume(var)).pack(side="left", padx=(8, 0))
                return var
            tk.Entry(parent, textvariable=var, font=("Segoe UI", 10),
                     show="*" if ftype == "password" else None).pack(fill="x")
            return var
        if ftype == "textarea":
            box = tk.Text(parent, font=("Segoe UI", 10), height=5)
            box.pack(fill="x")
            box.insert("1.0", saved)
            return box
        if ftype == "yesno":
            default = field_def.get("default", True)
            yes_text = field_def.get("yes_label", "Yes")
            no_text = field_def.get("no_label", "No")
            var = tk.BooleanVar(value=default if saved == "" else bool(saved))
            row = tk.Frame(parent)
            row.pack(anchor="w")
            tk.Radiobutton(row, text=yes_text, variable=var, value=True, font=("Segoe UI", 10)).pack(side="left")
            tk.Radiobutton(row, text=no_text, variable=var, value=False, font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
            return var
        return None

    def pick_resume(self, var):
        path = filedialog.askopenfilename(
            title="Choose your resume",
            filetypes=[("Resumes", "*.pdf *.doc *.docx"), ("PDF", "*.pdf"), ("Word", "*.doc *.docx")],
        )
        if path:
            var.set(path)
            self.refresh_resume_detect()

    def _step_answers(self, step_def):
        answers = {}
        for field_def in step_def["fields"]:
            widget = getattr(self, "_var_%s_%s" % (step_def["id"], field_def["key"]), None)
            if widget is None:
                continue
            ftype = field_def["type"]
            if ftype == "textarea":
                answers[field_def["key"]] = widget.get("1.0", "end").strip()
            elif ftype in ("text", "password", "yesno"):
                answers[field_def["key"]] = widget.get()
        if step_def["id"] == "wants" and self._wants_parsed:
            answers["parsed"] = self._wants_parsed
        return answers

    def collect_answers(self):
        '''All flow answers for setup_flow (what the flow owns).'''
        answers = {}
        for s in setup_flow.STEPS:
            answers[s["id"]] = self._step_answers(s)
        return answers

    # ----- page: review / summary -----
    def build_review(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Here's everything you told me", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="Please have a quick look before we save.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.summary_var = tk.StringVar()
        tk.Label(f, textvariable=self.summary_var, font=("Segoe UI", 10), fg="#1a7f37",
                 justify="left", wraplength=700, anchor="w").pack(anchor="w", pady=(4, 10))

        tk.Button(f, text="Finish", font=("Segoe UI", 11, "bold"), command=self.finish).pack(anchor="w")

    def _refresh_summary(self):
        # Make sure the wants sentence has been parsed (redirecting to the wants
        # step to answer the one pending plain-word question if needed) before
        # showing the plain-word summary.
        self.refresh_wants_parse()
        if self._wants_state is not None:
            self.show_page(flow_page_ids().index("wants"))
            return
        self.summary_var.set("\n".join(setup_flow.summary_lines(self.collect_answers())))

    # ----- page: all set / how to use -----
    def build_allset(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="You're all set!", font=("Segoe UI", 18, "bold"), fg="#1a7f37").pack(anchor="w")
        tk.Label(f, text="Setup is complete. Here is how to use the bot.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 14))

        tk.Label(f, text="How to use", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        for i, line in enumerate([
            "Double-click the 'Auto Job Applier' icon on your Desktop (or open AutoJobApplier.exe in this folder).",
            "The bot opens Google Chrome and logs into your LinkedIn account automatically.",
            "It searches the kind of job you described, opens every Easy Apply form it finds, and fills the answers.",
            "Before it sends anything, it pauses so you can review (as you chose).",
            "Each application is saved in the 'all excels' folder, so you can review what it did later.",
            "To stop the bot at any time, just close the window.",
        ], start=1):
            tk.Label(f, text="%d. %s" % (i, line), font=("Segoe UI", 10), justify="left", wraplength=700).pack(anchor="w", pady=1)

        tk.Label(f, text="Good to know", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(14, 6))
        for line in [
            "Keep your PC on, awake, and connected to the internet during a run.",
            "Don't touch or close the Chrome window while it is applying.",
            "Your details stay only on this PC (user_config.json). Never share that file.",
        ]:
            tk.Label(f, text="- " + line, font=("Segoe UI", 10), fg="#666", justify="left", wraplength=700).pack(anchor="w", pady=1)

        tk.Label(f, text="What happens next", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(14, 6))
        for line in setup_flow.allset_lines(self.collect_answers()):
            tk.Label(f, text="- " + line, font=("Segoe UI", 10), fg="#1a7f37", justify="left", wraplength=700).pack(anchor="w", pady=1)

        if getattr(self, "report", None):
            tk.Label(f, text="", font=("Segoe UI", 6)).pack()
            tk.Label(f, text="Created for you:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            for line in self.report:
                tk.Label(f, text="- " + line, font=("Segoe UI", 10)).pack(anchor="w", pady=1)

        tk.Label(f, text="", font=("Segoe UI", 8)).pack()
        tk.Button(f, text="Done", font=("Segoe UI", 11, "bold"),
                  command=self.root.destroy).pack(anchor="w")

    # ----- advanced: account -----
    def build_account(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="LinkedIn account", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="The bot logs in as you and applies on your behalf.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.make_row(f, "Email", self.var_username, show=None, required=True)
        self.make_row(f, "Password", self.var_password, show="*", required=True)
        tk.Label(f, text="* required", font=("Segoe UI", 9), fg="#d1242f").pack(anchor="w")
        tk.Label(f, text="Tip: use a dedicated profile and don't share these credentials.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(8, 0))

    # ----- advanced: AI -----
    def build_ai(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Gemini AI key (optional, advanced)", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="Recommended: it lets the bot write answers to application questions automatically.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))
        tk.Label(f, text="Not sure yet? Leave it blank - the bot still works using the",
                 font=("Segoe UI", 10), fg="#666").pack(anchor="w")
        tk.Label(f, text="details you entered in this setup, and you can add the key here later.",
                 font=("Segoe UI", 10), fg="#666").pack(anchor="w", pady=(0, 12))

        self.make_row(f, "Gemini API key (optional)", self.var_gemini, show="*")

        btns = tk.Frame(f)
        btns.pack(anchor="w", pady=(10, 0))
        tk.Button(btns, text="Get a free key (opens page)", font=("Segoe UI", 10),
                  command=lambda: self.open_url(GEMINI_KEY_URL)).pack(side="left")
        tk.Button(btns, text="Watch how-to video", font=("Segoe UI", 10),
                  command=lambda: self.open_url(GEMINI_VIDEO_URL)).pack(side="left", padx=(8, 0))

        tk.Label(f, text="1. Open the page/video and click 'Create API key' using any Google account.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(12, 0))
        tk.Label(f, text="2. Copy the key (starts with 'AIza...') and paste it above.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w")

    # ----- advanced: jobs -----
    def build_jobs(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Jobs you want (advanced)", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="One title per line, and one location per line.  * = required",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        grid = tk.Frame(f)
        grid.pack(fill="both", expand=True)

        tk.Label(grid, text="Job titles *", font=("Segoe UI", 10, "bold"), fg="#d1242f").grid(row=0, column=0, sticky="w")
        tk.Label(grid, text="Locations *", font=("Segoe UI", 10, "bold"), fg="#d1242f").grid(row=0, column=1, sticky="w", padx=(16, 0))

        terms = tk.Text(grid, font=("Segoe UI", 10), height=6, width=34)
        terms.grid(row=1, column=0, sticky="nsew")
        terms.insert("1.0", self.var_terms.get())
        self.terms_widget = terms

        locs = tk.Text(grid, font=("Segoe UI", 10), height=6, width=34)
        locs.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        locs.insert("1.0", self.var_locations.get())
        self.locs_widget = locs

        tk.Label(f, text="Examples: Product Manager / Data Analyst.  Locations: Pune / Remote / Singapore / European Union / Japan / Indonesia.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(10, 0))

        grid2 = tk.Frame(f)
        grid2.pack(anchor="w", pady=(14, 0))
        tk.Label(grid2, text="Your city", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(grid2, textvariable=self.var_city, width=18, font=("Segoe UI", 10), show=None).pack(side="left", padx=(6, 16))
        tk.Label(grid2, text="Years of experience", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(grid2, textvariable=self.var_years, width=6, font=("Segoe UI", 10)).pack(side="left", padx=(6, 16))
        tk.Label(grid2, text="Job type", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(grid2, textvariable=self.var_jobtype, width=16, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))

    # ----- advanced: resume details -----
    def build_resume(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Resume details (advanced)", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="Your name is used to fill answers and your signature on applications.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.make_row(f, "First name", self.var_first, show=None, required=True)
        self.make_row(f, "Last name", self.var_last, show=None, required=True)

        tk.Label(f, text="Optional profile links", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 6))
        self.make_row(f, "LinkedIn profile URL", self.var_linkedin, show=None)
        self.make_row(f, "Website / portfolio", self.var_website, show=None)

        tk.Label(f, text="Only pasted when an application form asks for it.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(10, 0))

    # ----- advanced: unlock / license -----
    def build_unlock(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Unlock (optional, advanced)", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text=(
            "Free plan: up to 10 applications per day.\n"
            "Bought the product? Paste your license key to remove the limit."
        ), font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.unlock_status = tk.StringVar(value=self._license_status_text())
        tk.Label(f, textvariable=self.unlock_status, font=("Segoe UI", 10, "bold"),
                 fg="#1a7f37").pack(anchor="w", pady=(0, 8))

        row = tk.Frame(f)
        row.pack(fill="x")
        tk.Label(row, text="License key", width=20, anchor="w", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(row, textvariable=self.var_license, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)

        tk.Button(f, text="Activate", font=("Segoe UI", 10), command=self.activate_license).pack(anchor="w", pady=(12, 4))
        tk.Label(f, text="Where to find it: open your Gumroad receipt email - the key is above the product name.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(8, 0))
        tk.Label(f, text="No key yet? Just leave it blank - you can start on the Free plan anytime.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(4, 0))

    def _license_status_text(self):
        from modules.license import free_daily_limit
        if setup_flow.has_license():
            return "Status: Unlimited unlocked"
        return "Status: Free plan - up to %d applications per day" % free_daily_limit

    def activate_license(self):
        from modules.license import activate_license as verify
        ok, message = verify(self.var_license.get())
        if ok:
            self.unlock_status.set("Status: Unlimited unlocked")
        else:
            self.unlock_status.set("Status: " + message)
        messagebox.showinfo("License", message)

    # ----- advanced: schedule + finish -----
    def build_schedule(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="When should it run? (advanced)", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="The job application run takes a while. It runs whenever your PC is switched on.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        tk.Checkbutton(f, text="Apply as soon as I turn on / log into my PC",
                        variable=self.var_logon, font=("Segoe UI", 10)).pack(anchor="w", pady=3)
        daily = tk.Frame(f)
        daily.pack(anchor="w", pady=3)
        tk.Checkbutton(daily, text="Also apply once daily at ",
                        variable=self.var_daily, font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(daily, textvariable=self.var_time, width=6, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))
        tk.Label(daily, text="  (24h format, e.g. 09:00)", font=("Segoe UI", 9), fg="#666").pack(side="left")

        tk.Checkbutton(f, text="Create a desktop shortcut so I can run it anytime",
                        variable=self.var_shortcut, font=("Segoe UI", 10)).pack(anchor="w", pady=3)

        tk.Label(f, text="Saved by the primary flow. These advanced options are optional.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(12, 0))

    # ----- utils -----
    def make_row(self, parent, label, var, show, required=False):
        r = tk.Frame(parent)
        r.pack(anchor="w", fill="x", pady=4)
        if required:
            tk.Label(r, text="*", font=("Segoe UI", 12, "bold"), fg="#d1242f").pack(side="left")
        tk.Label(r, text=label, width=20, anchor="w", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(r, textvariable=var, font=("Segoe UI", 10), show=show).pack(side="left", fill="x", expand=True)

    @staticmethod
    def open_url(url):
        import webbrowser
        webbrowser.open(url)

    def _terms_text(self):
        if self.terms_widget is not None:
            return self.terms_widget.get("1.0", "end")
        return self.var_terms.get()

    def _locs_text(self):
        if self.locs_widget is not None:
            return self.locs_widget.get("1.0", "end")
        return self.var_locations.get()

    def finish(self):
        # Required-flow validation: the flow cannot finish broken.
        answers = self.collect_answers()
        errors = setup_flow.validate_flow(answers)
        if errors:
            messages = []
            for step_errors in errors.values():
                messages.extend(step_errors)
            messagebox.showwarning("A few things are missing", "Please fill: " + " ".join(messages))
            first_step = [s["id"] for s in setup_flow.STEPS if s["id"] in errors][0]
            self.show_page(flow_page_ids().index(first_step))
            return

        username = (self._var_account_username.get() or "").strip()
        password = self._var_account_password.get()
        # Fall back to the advanced account page for users who filled that instead.
        if not username:
            username = (self.var_username.get() or "").strip()
        if not password:
            password = self.var_password.get()
        if len(username) < 5 or len(password) < 5:
            messagebox.showwarning(
                "Almost there",
                "Please double-check your LinkedIn email and password (each needs at least 5 characters).",
            )
            self.show_page(flow_page_ids().index("account"))
            return

        cfg = build_config(
            username=username,
            password=password,
            gemini_key=self.var_gemini.get(),
            current_city=self.var_city.get(),
            years_of_experience=self.var_years.get(),
            resume_path=self.var_resume.get(),
            website=self.var_website.get(),
            linkedin_url=self.var_linkedin.get(),
            search_terms=self._terms_text(),
            locations=self._locs_text(),
            current_experience=self.var_experience.get(),
            job_types=self.var_jobtype.get(),
            existing=self.existing,
            first_name=self.var_first.get(),
            last_name=self.var_last.get(),
            license_key=self.var_license.get(),
        )
        # The flow's answers always win for the keys the flow owns.
        cfg = setup_flow.apply_answers(cfg, answers)
        write_config(cfg)

        created = []
        if self.var_shortcut.get():
            lnk = create_shortcut("Auto Job Applier", run_target(), ROOT)
            if lnk:
                created.append("Desktop shortcut created")
        if self.var_logon.get():
            r = register_task(APPLY_AT_LOGON_TASK, run_target(), {"type": "ONLOGON", "logon": True})
            created.append("Run at PC startup: " + ("ready" if r.returncode == 0 else r.stderr.strip()))
        if self.var_daily.get():
            r = register_task(APPLY_DAILY_TASK, run_target(), {"type": "DAILY", "start": self.var_time.get()})
            created.append("Daily run at %s: %s" % (self.var_time.get(), "ready" if r.returncode == 0 else r.stderr.strip()))

        self.report = created or []
        self.show_page(self.quick_last)


def probe_write(out=None):
    cfg = build_config(
        username="test@example.com", password="testpass",
        gemini_key="AIza-EXAMPLE-KEY-FOR-PROBE",
        current_city="Pune", years_of_experience="3",
        resume_path=r"C:\resume\REDACTED.pdf",
        website="example.com", linkedin_url="https://www.linkedin.com/in/example",
        search_terms="Product Manager\nAI Product Manager",
        locations="Pune\nRemote\nSingapore",
        current_experience="4", job_types="Full-time, Contract",
        existing=load_existing_config(),
    )
    cfg = setup_flow.apply_answers(cfg, {
        "resume": {"resume_path": r"C:\resume\REDACTED.pdf"},
        "wants": {"sentence": "AI Product Manager roles in Europe, remote or hybrid, posted this week."},
        "policy": {"ask_before_sending": True},
    })
    if not out:
        out = os.path.join(tempfile.gettempdir(), "ajaprobe_config.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("PROBE-WRITE-OK:", out)
    return cfg


def run_gui(initial_step=0) -> None:
    root = tk.Tk()
    root.title(setup_flow.FLOW_TITLE)
    root.minsize(780, 560)
    app = Wizard(root, initial_step=initial_step)

    nav = tk.Frame(root)
    nav.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))
    quick_labels = ["Welcome"] + [s["title"] for s in setup_flow.STEPS] + ["Review", "All set"]
    advanced_labels = ["Account", "AI key", "Jobs", "Resume", "Unlock", "Schedule"]
    buttons = []
    advanced_buttons = []

    def rebuild_nav(in_advanced):
        for b in buttons + advanced_buttons:
            b.destroy()
        buttons.clear()
        advanced_buttons.clear()
        if in_advanced:
            labels = advanced_labels
            container = advanced_buttons
        else:
            labels = quick_labels
            container = buttons
        for i, lbl in enumerate(labels):
            b = tk.Button(nav, text=lbl, font=("Segoe UI", 9), relief="flat",
                          command=lambda i=i, c=container: nav_to(c, i))
            b.pack(side="left", padx=(0, 10))
            container.append(b)
        if not in_advanced:
            b = tk.Button(nav, text="Advanced...", font=("Segoe UI", 9), fg="#666",
                          command=lambda: enter_advanced())
            b.pack(side="right", padx=(0, 10))
            buttons.append(b)
        else:
            b = tk.Button(nav, text="Back to quick setup", font=("Segoe UI", 9), fg="#1a7f37",
                          command=lambda: nav_to(buttons, app.last_quick))
            b.pack(side="right", padx=(0, 10))
            advanced_buttons.append(b)

    def highlight(container, i):
        for j, b in enumerate(container):
            b.config(relief="solid" if j == i else "flat")

    def nav_to(container, i):
        app.show_page(i)
        for c in (buttons, advanced_buttons):
            highlight(c, -1)
        rebuild_nav(app.in_advanced)
        highlight(container, i)
        if not app.in_advanced:
            app.refresh_wants_parse()
            app._refresh_summary()

    def enter_advanced():
        adv_start = app.quick_last + 1
        app.show_page(adv_start)
        rebuild_nav(True)
        highlight(advanced_buttons, app.current - adv_start)

    rebuild_nav(False)
    if app.in_advanced:
        rebuild_nav(True)
        highlight(advanced_buttons, app.current - (app.quick_last + 1))
    else:
        highlight(buttons, app.current)

    root.mainloop()


if __name__ == "__main__":
    run_gui()