'''
Resume Profile detection for the "Your resume" setup step.

A resume file stays a snapshot (the path the tool uploads), and this module
extracts a SEPARATE candidate profile record from it - years of experience and
key skills - so the two are stored apart and the extraction is inspectable.

Pure input -> output transform: `detect_profile(path)` reads a file and returns
a dict. It never writes anything. Used by both the Tkinter wizard and the web
control panel, and exercised directly by tests with a stubbed resume file.

Supported files: PDF (pypdf), Word .docx (python-docx), plain .txt, and a
best-effort read of legacy binary .doc.

License: MIT (https://opensource.org/license/mit)
'''

from __future__ import annotations

import os
import re

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt")


# ---------------------------------------------------------------------------
# Raw text extraction
# ---------------------------------------------------------------------------

def extract_text(resume_path: str) -> str:
    '''
    Read all text out of a resume file. Raises ValueError / FileNotFoundError
    with a plain-word message when the file is missing or unsupported.
    '''
    path = str(resume_path or "").strip()
    if not path:
        raise ValueError("No resume file was chosen.")
    if not os.path.exists(path):
        raise FileNotFoundError("Could not find the resume file: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    if ext == ".doc":
        return _extract_legacy_doc(path)
    raise ValueError(
        "Unsupported resume file type (.%s). Use a PDF, Word (.docx) or text file."
        % ext.lstrip(".")
    )


def _extract_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def _extract_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    chunks = [p.text for p in doc.paragraphs if (p.text or "").strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if (c.text or "").strip()]
            if cells:
                chunks.append(" | ".join(cells))
    return "\n".join(chunks)


def _extract_legacy_doc(path: str) -> str:
    # Binary .doc has no clean text API without extra tools; pull whatever
    # readable text the raw bytes contain so detection can still work.
    import string
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("latin-1", errors="replace")
    printable = [ch if ch in string.printable else "\n" for ch in text]
    lines = [" ".join(line.split()) for line in "".join(printable).splitlines()]
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Years-of-experience detection
# ---------------------------------------------------------------------------

_YEARS_PATTERNS = [
    re.compile(r"(?P<y>\d{1,2})\+?\s+years?(?:\s+of)?(?:\s+professional)?\s+experience", re.IGNORECASE),
    re.compile(r"experience(?:\s+of)?\s+(?P<y>\d{1,2})\+?\s+years?", re.IGNORECASE),
]


def detect_years(text: str):
    '''
    Estimate years of experience from resume text: prefer an explicit
    "N+ years ... experience" statement, else fall back to the span between the
    earliest and latest year mentioned in the work history. Returns a float or
    None (never a guess from noise).
    '''
    for pat in _YEARS_PATTERNS:
        m = pat.search(text or "")
        if m:
            return float(m.group("y"))
    span = _year_span(text or "")
    if span is not None:
        return span
    return None


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _year_span(text: str):
    years = sorted({int(m.group(0)) for m in _YEAR_RE.finditer(text)})
    if len(years) < 2:
        return None
    span = years[-1] - years[0]
    if 0 < span <= 30:
        return float(span)
    return None


# ---------------------------------------------------------------------------
# Key-skill detection
# ---------------------------------------------------------------------------

# Curated glossary of common skills. Short acronyms ("AI", "NLP") are matched
# with a non-alphanumeric boundary so words like "Email" don't false-positive.
_SKILLS = [
    # AI / data
    "AI", "artificial intelligence", "machine learning", "deep learning",
    "generative AI", "LLM", "LLMs", "large language model", "NLP",
    "natural language processing", "computer vision", "recommendation systems",
    "langchain", "pytorch", "tensorflow", "RAG", "retrieval", "fine-tuning",
    "prompt engineering", "data engineering", "data science", "data analysis",
    "statistics", "SQL", "data pipelines", "ETL", "MLOps",
    # Engineering
    "python", "java", "typescript", "javascript", "react", "node.js", "go",
    "rust", "C++", "kubernetes", "docker", "AWS", "azure", "GCP", "cloud",
    "CI/CD", "git", "REST APIs", "microservices", "system design", "testing",
    "REST", "fastapi", "django", "flask", "graphql",
    # Product / management
    "product management", "product strategy", "product roadmap", "roadmap",
    "go-to-market", "GTM", "agile", "scrum", "sprinting", "user research",
    "stakeholder", "cross-functional", "unit economics", "A/B testing", "figma",
    "wireframing", "prototyping", "OKR",
    # Soft skills
    "communication", "leadership", "team leadership", "mentoring", "presentation",
]

_SHORT_ACRONYMS = {"ai", "nlp", "llm", "llms", "rag", "mlops"}


def _skill_pattern(skill: str) -> re.Pattern:
    if skill.lower() in _SHORT_ACRONYMS or len(skill) <= 2:
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(skill.lower()) + r"(?![A-Za-z0-9])")
    return re.compile(r"\b" + re.escape(skill.lower()) + r"\b")


_SKILL_PATTERNS = [(skill, _skill_pattern(skill)) for skill in _SKILLS]


def detect_skills(text: str, limit: int = 10) -> list:
    '''
    Return up to `limit` skills found in resume text, ordered by first
    occurrence in the document.
    '''
    if not text:
        return []
    low = (text or "").lower()
    found = []
    for skill, pat in _SKILL_PATTERNS:
        m = pat.search(low)
        if m:
            found.append((m.start(), skill))
    found.sort()
    return [skill for _, skill in found[:limit]]


# ---------------------------------------------------------------------------
# Employer detection
# ---------------------------------------------------------------------------

# An experience heading looks like "Company (blurb) · City | Month Year - Month Year".
# The employer is the leading token: greedy name, optional parenthetical blurb,
# optional separator, then a location before a date pipe (or dash) that ends in a
# 4-digit year. Requiring the pipe/dash+year anchor drops summary lines, bullets,
# contact blocks and education headings that merely contain a comma or dot.
_COMPANY_HEADER = re.compile(
    r"^(?P<name>[A-Za-z0-9&%][^·|–—()\n]*)"
    r"\s*(?:\([^)]*\))?\s*"
    r"(?:·|–|—|,)?\s*"
    r"(?P<loc>[A-Za-z][^\d·|–—\n]*)"       # location words (letters first; no year/separators) - required
    r"(?:\|\s*|[-–·])\s*"
    r"[A-Za-z]{3,9}\s+\d{4}",           # "Month Year" (bare years are not a work header)
    re.IGNORECASE,
)


def detect_companies(text: str) -> list:
    '''
    Extract employer names from a resume's experience section. Lines that look
    like "Company (blurb) · Location | Dates" yield the leading company token.
    Returns a de-duplicated list in the order they appear; never raises.
    '''
    names = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _COMPANY_HEADER.match(line)
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group("name").strip(" ('\"….,;:-·")).strip()
        if len(name) < 2:
            continue
        if name.lower() in {n.lower() for n in names}:
            continue
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# Profile record
# ---------------------------------------------------------------------------

def detect_profile(resume_path: str) -> dict:
    '''
    Build a candidate profile record from a resume file. Never raises: cases
    where the file can't be read still return a record with ok=False and a
    plain-word message, so UIs can show a graceful note and the user can
    continue with just a file path.

    Returns:
        {"source", "ok", "years", "skills", "summary_line", "message"}
    '''
    record = {
        "source": str(resume_path or "").strip(),
        "ok": False,
        "years": None,
        "skills": [],
        "companies": [],
        "summary_line": "",
        "message": "I couldn't read a profile from this file yet. You can still continue.",
    }
    path = str(resume_path or "").strip()
    if not path:
        record["message"] = "No resume file chosen."
        return record
    try:
        text = extract_text(path)
    except FileNotFoundError as e:
        record["message"] = str(e)
        return record
    except ValueError as e:
        record["message"] = str(e)
        return record
    except Exception as e:  # corrupt/unsupported file internals
        record["message"] = "I couldn't read that resume file (%s)." % e
        return record

    years = detect_years(text)
    skills = detect_skills(text)
    if years is None and not skills:
        record["message"] = (
            "I read the file but couldn't spot years of experience or a "
            "skill set in it. You can still continue."
        )
        return record

    record["ok"] = True
    record["years"] = years
    record["skills"] = skills
    record["companies"] = detect_companies(text)
    record["summary_line"] = describe(record)
    record["message"] = ""
    return record


def describe(record) -> str:
    '''
    One plain-sentence summary of a profile record, e.g.
    "5 years experience, specializing in AI, Product Management, LLMs".
    '''
    if not record or not record.get("ok"):
        return ""
    parts = []
    years = record.get("years")
    if years:
        parts.append("%d+ years experience" % int(years))
    skills = record.get("skills") or []
    if skills:
        parts.append("skills in %s" % ", ".join(skills[:4]))
    return ", ".join(parts)