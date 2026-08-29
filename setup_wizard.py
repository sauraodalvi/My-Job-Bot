import sys
import os
import json
import subprocess
import datetime
import tempfile

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
CONFIG_PATH = os.path.join(ROOT, "user_config.json")
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
):
    existing = existing or {}
    existing = json.loads(json.dumps(existing))

    secrets = dict(existing.get("secrets", {}))
    secrets.update({
        "username": (username or "").strip(),
        "password": password or "",
        "use_AI": True,
        "ai_provider": "gemini",
        "llm_model": GEMINI_MODEL,
        "llm_api_key": (gemini_key or "").strip(),
    })

    personals = dict(existing.get("personals", {}))
    personals["current_city"] = (current_city or "").strip()
    if "first_name" not in personals:
        personals["first_name"] = ""
    if "middle_name" not in personals:
        personals["middle_name"] = ""
    if "last_name" not in personals:
        personals["last_name"] = ""

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
        "current_experience": int(float(current_experience)) if str(current_experience).strip().replace(".", "").isdigit() else search.get("current_experience", 4),
    })
    if job_types:
        search["job_type"] = [j.strip() for j in job_types.split(",") if j.strip()]

    return {
        "secrets": secrets,
        "personals": personals,
        "questions": questions,
        "search": search,
    }


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


class Wizard:
    def __init__(self, root):
        self.root = root
        self.existing = load_existing_config()
        self.secrets = self.existing.get("secrets", {})
        self.personals = self.existing.get("personals", {})
        self.questions = self.existing.get("questions", {})
        self.search = self.existing.get("search", {})

        self.var_username = tk.StringVar(value=self.secrets.get("username", ""))
        self.var_password = tk.StringVar(value=self.secrets.get("password", ""))
        self.var_gemini = tk.StringVar(value=self.secrets.get("llm_api_key", ""))
        self.var_city = tk.StringVar(value=self.personals.get("current_city", ""))
        self.var_years = tk.StringVar(value=self.questions.get("years_of_experience", ""))
        self.var_resume = tk.StringVar(value=self.questions.get("default_resume_path", ""))
        self.var_website = tk.StringVar(value=self.questions.get("website", ""))
        self.var_linkedin = tk.StringVar(value=self.questions.get("linkedIn", ""))
        self.var_terms = tk.StringVar(value="\n".join(self.search.get("search_terms", [])))
        self.var_locations = tk.StringVar(value="\n".join(self.search.get("search_location", "").split(", ")) if self.search.get("search_location") else "")
        self.var_experience = tk.StringVar(value=str(self.search.get("current_experience", 4)))
        self.var_jobtype = tk.StringVar(value=", ".join(self.search.get("job_type", ["Full-time"])))
        self.var_logon = tk.BooleanVar(value=True)
        self.var_daily = tk.BooleanVar(value=True)
        self.var_time = tk.StringVar(value="09:00")
        self.var_shortcut = tk.BooleanVar(value=True)

        self.pages = []
        self.current = 0

        self.build_welcome()
        self.build_account()
        self.build_ai()
        self.build_jobs()
        self.build_resume()
        self.build_schedule()
        for page in self.pages:
            page.grid_forget()
        self.show_page(0)

    def add_page(self, page):
        self.pages.append(page)

    def show_page(self, idx):
        for p in self.pages:
            p.grid_forget()
        page = self.pages[idx]
        page.grid(row=0, column=0, sticky="nsew")
        self.current = idx
        self.update_nav()

    def update_nav(self):
        pass

    # ----- page 0: welcome -----
    def build_welcome(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Auto Job Applier", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(f, text="Setup one time, then it reads jobs and sends applications for you.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 14))

        tk.Label(f, text="What this does", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        for line in [
            "1. Logs you into LinkedIn (one-time, then remembers you).",
            "2. Searches the job titles you choose, in the locations you choose.",
            "3. Answers the application questions automatically with Gemini AI.",
            "4. Sends Easy Apply applications and saves each one to local files.",
        ]:
            tk.Label(f, text=line, font=("Segoe UI", 10)).pack(anchor="w", padx=6)

        tk.Label(f, text="", font=("Segoe UI", 6)).pack()
        chrome = "Google Chrome: INSTALLED" if chrome_installed() else "Google Chrome: NOT DETECTED"
        color = "#1a7f37" if chrome_installed() else "#d1242f"
        tk.Label(f, text=chrome, font=("Segoe UI", 10, "bold"), fg=color).pack(anchor="w")

        tk.Label(f, text="Everything you enter is stored ONLY on this PC in user_config.json.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(12, 4))
        tk.Label(f, text="Never share that file. Use at your own risk against LinkedIn guidelines.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w")

    # ----- page 1: account -----
    def build_account(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="LinkedIn account", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="The bot logs in as you and applies on your behalf.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.make_row(f, "Email", self.var_username, show=None)
        self.make_row(f, "Password", self.var_password, show="*")
        tk.Label(f, text="Tip: use a dedicated profile and don't share these credentials.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(10, 0))

    # ----- page 2: AI -----
    def build_ai(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Gemini AI key", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="Gemini answers the application questions for you. It is free to get a key.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        self.make_row(f, "Gemini API key", self.var_gemini, show="*")

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

    # ----- page 3: jobs -----
    def build_jobs(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Jobs you want", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="One title per line, and one location per line.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        grid = tk.Frame(f)
        grid.pack(fill="both", expand=True)

        tk.Label(grid, text="Job titles", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(grid, text="Locations", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(16, 0))

        terms = tk.Text(grid, font=("Segoe UI", 10), height=6, width=34)
        terms.grid(row=1, column=0, sticky="nsew")
        terms.insert("1.0", self.var_terms.get())
        self.var_terms = terms

        locs = tk.Text(grid, font=("Segoe UI", 10), height=6, width=34)
        locs.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        locs.insert("1.0", self.var_locations.get())
        self.var_locations = locs

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

    # ----- page 4: resume -----
    def build_resume(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="Your resume", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="Attach the resume you want to send. PDF or Word is fine.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        row = tk.Frame(f)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.var_resume, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse...", font=("Segoe UI", 10), command=self.pick_resume).pack(side="left", padx=(8, 0))

        tk.Label(f, text="Optional profile links", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 6))
        self.make_row(f, "LinkedIn profile URL", self.var_linkedin, show=None)
        self.make_row(f, "Website / portfolio", self.var_website, show=None)

        tk.Label(f, text="Only pasted when an application form asks for it.",
                 font=("Segoe UI", 9), fg="#666").pack(anchor="w", pady=(10, 0))

    def pick_resume(self):
        path = filedialog.askopenfilename(
            title="Choose your resume",
            filetypes=[("Resumes", "*.pdf *.doc *.docx"), ("PDF", "*.pdf"), ("Word", "*.doc *.docx")],
        )
        if path:
            self.var_resume.set(path)

    # ----- page 5: schedule + finish -----
    def build_schedule(self):
        f = tk.Frame(self.root, padx=28, pady=24)
        self.add_page(f)
        tk.Label(f, text="When should it run?", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(f, text="The job application run takes a while. It runs whenever your PC is switched on.",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))

        ttk.Checkbutton(f, text="Apply as soon as I turn on / log into my PC",
                        variable=self.var_logon, font=("Segoe UI", 10)).pack(anchor="w", pady=3)
        daily = tk.Frame(f)
        daily.pack(anchor="w", pady=3)
        ttk.Checkbutton(daily, text="Also apply once daily at ",
                        variable=self.var_daily, font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(daily, textvariable=self.var_time, width=6, font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))
        tk.Label(daily, text="  (24h format, e.g. 09:00)", font=("Segoe UI", 9), fg="#666").pack(side="left")

        ttk.Checkbutton(f, text="Create a desktop shortcut so I can run it anytime",
                        variable=self.var_shortcut, font=("Segoe UI", 10)).pack(anchor="w", pady=3)

        tk.Label(f, text="", font=("Segoe UI", 6)).pack()
        tk.Button(f, text="Finish setup", font=("Segoe UI", 11, "bold"),
                  command=self.finish).pack(anchor="w")

    # ----- utils -----
    def make_row(self, parent, label, var, show):
        r = tk.Frame(parent)
        r.pack(anchor="w", fill="x", pady=4)
        tk.Label(r, text=label, width=20, anchor="w", font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(r, textvariable=var, font=("Segoe UI", 10), show=show).pack(side="left", fill="x", expand=True)

    @staticmethod
    def open_url(url):
        import webbrowser
        webbrowser.open(url)

    def finish(self):
        cfg = build_config(
            username=self.var_username.get(),
            password=self.var_password.get(),
            gemini_key=self.var_gemini.get(),
            current_city=self.var_city.get(),
            years_of_experience=self.var_years.get(),
            resume_path=self.var_resume.get(),
            website=self.var_website.get(),
            linkedin_url=self.var_linkedin.get(),
            search_terms=self.var_terms.get("1.0", "end"),
            locations=self.var_locations.get("1.0", "end"),
            current_experience=self.var_experience.get(),
            job_types=self.var_jobtype.get(),
            existing=self.existing,
        )

        missing = []
        if not (cfg["secrets"]["username"] and cfg["secrets"]["password"]):
            missing.append("LinkedIn email and password")
        if not cfg["secrets"]["llm_api_key"]:
            missing.append("Gemini API key")
        if not cfg["search"]["search_terms"]:
            missing.append("at least one job title")
        if not cfg["search"]["search_location"]:
            missing.append("at least one location")
        if missing:
            messagebox.showwarning("A few things are missing", "Please fill: " + ", ".join(missing))
            return

        path = write_config(cfg)

        created = []
        if self.var_shortcut.get():
            lnk = create_shortcut("Auto Job Applier", run_target(), ROOT)
            if lnk:
                created.append("Desktop shortcut: " + lnk)
        if self.var_logon.get():
            r = register_task(APPLY_AT_LOGON_TASK, run_target(), {"type": "ONLOGON", "logon": True})
            created.append("Run at PC startup: " + ("OK" if r.returncode == 0 else r.stderr.strip()))
        if self.var_daily.get():
            r = register_task(APPLY_DAILY_TASK, run_target(), {"type": "DAILY", "start": self.var_time.get()})
            created.append("Daily run at %s: %s" % (self.var_time.get(), "OK" if r.returncode == 0 else r.stderr.strip()))

        msg = "Setup saved to:\n%s\n\n%s\n\nNow press the desktop shortcut or run the App to start applying." % (
            path, "\n".join(created) if created else "No scheduling/shortcuts were created.")
        messagebox.showinfo("You're all set", msg)


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
    if not out:
        out = os.path.join(tempfile.gettempdir(), "ajaprobe_config.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("PROBE-WRITE-OK:", out)
    return cfg


def run_gui() -> None:
    root = tk.Tk()
    root.title("Auto Job Applier - Setup")
    root.minsize(780, 560)
    app = Wizard(root)

    nav = tk.Frame(root)
    nav.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))
    labels = ["Welcome", "LinkedIn", "AI key", "Jobs", "Resume", "Schedule"]
    buttons = []

    def nav_to(i):
        app.show_page(i)
        for j, b in enumerate(buttons):
            b.config(relief="solid" if j == i else "flat")

    for i, lbl in enumerate(labels):
        b = tk.Button(nav, text=lbl, font=("Segoe UI", 9), relief="flat",
                      command=lambda i=i: nav_to(i))
        b.pack(side="left", padx=(0, 10))
        buttons.append(b)
    if buttons:
        buttons[0].config(relief="solid")

    root.mainloop()


if __name__ == "__main__":
    run_gui()