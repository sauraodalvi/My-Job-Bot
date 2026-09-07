'''
Unit tests for modules/resumes/profile.py - the Resume Profile detector behind
the "Your resume" setup step.

Pins the contract:
  * detect_profile(path) never raises, always returns a record dict,
  * a readable text file yields years + skills and a one-line summary,
  * the summary never exceeds a plain sentence,
  * setup_flow keeps file and extracted profile as SEPARATE records.

License: MIT  (https://opensource.org/license/mit)
'''

import pytest

from modules.resumes import profile as resume_profile
import setup_flow


def _sample_resume(tmp_path, text=None):
    p = tmp_path / "resume.txt"
    p.write_text(text or (
        "Ada Lovelace - Senior Data Analyst\n"
        "5+ years experience in SQL, Python, Excel.\n"
        "Built dashboards and A/B tests.\n"
    ), encoding="utf-8")
    return str(p)


def test_detect_never_raises_and_returns_ok():
    from modules.resumes.profile import detect_profile
    for path in ("", None, "C:/no/such/file.pdf"):
        record = detect_profile(path)
        assert record is not None and record["ok"] is False
        assert record["message"]


def test_detect_reads_txt_and_finds_years_and_skills(tmp_path):
    record = resume_profile.detect_profile(_sample_resume(tmp_path))
    assert record["ok"] is True
    assert record["source"].endswith("resume.txt")
    assert str(record["years"]).startswith("5")
    assert "SQL" in record["skills"]
    assert "python" in record["skills"]


def test_detect_reads_docx(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Ada Lovelace - Machine Learning Engineer")
    doc.add_paragraph("3+ years experience in python, LLMs.")
    path = str(tmp_path / "resume.docx")
    doc.save(path)
    record = resume_profile.detect_profile(path)
    assert record["ok"] is True
    assert "python" in record["skills"]
    assert str(record["years"]).startswith("3")


def test_multiple_recency_points_pick_largest(tmp_path):
    record = resume_profile.detect_profile(_sample_resume(
        tmp_path,
        "2 years of analysis, and 7+ years experience in shipping logistics.",
    ))
    assert record["ok"] is True
    assert str(record["years"]).startswith("7")


def test_skills_limited_and_ordered_by_occurrence(tmp_path):
    record = resume_profile.detect_profile(_sample_resume(tmp_path))
    assert len(record["skills"]) <= 10
    assert record["skills"]  # at least one skill found


def test_summary_is_one_plain_sentence(tmp_path):
    record = resume_profile.detect_profile(_sample_resume(tmp_path))
    line = resume_profile.describe(record)
    assert line and line.count(".") <= 1
    assert "experience" in line and "skills in " in line


def test_setup_flow_keeps_file_and_profile_as_separate_records(monkeypatch, tmp_path):
    import json
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(setup_flow, "USER_CONFIG_PATH", cfg_path)

    path = _sample_resume(tmp_path)
    setup_flow.save_flow({"resume": {"resume_path": path},
                          "wants": {"sentence": "Data Analyst roles"},
                          "policy": {"ask_before_sending": True}})

    with open(cfg_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["questions"]["default_resume_path"] == path
    record = saved["resume_profiles"][path]
    assert record["ok"] is True and record["summary_line"]
    # The text itself is not dumped as the resume value.
    assert "Ada Lovelace" not in saved["questions"]["default_resume_path"]

    text, ok = setup_flow.describe_resume_path(path)
    assert ok is True and text == record["summary_line"]
    pre = setup_flow.prefill()
    assert pre["resume"]["resume_path"] == path
    assert pre["resume"]["profile_text"] == record["summary_line"]


_RESUME_WITH_COMPANIES = (
    "Ada Lovelace - Senior Data Analyst\n"
    "5+ years experience in SQL, Python.\n"
    "PROFESSIONAL EXPERIENCE\n"
    "D Robotops (Drone SaaS) · Bengaluru, India | Jan 2022 - Mar 2024\n"
    "Senior Data Analyst\n"
    "Some bullet here.\n"
    "BuildCo (Construction) · Remote | Apr 2024 - Present\n"
    "Data Lead\n"
    "EDUCATION\n"
    "Uni of Things - 2020 - 2022\n"
    "Masters, CS\n"
)


def test_detect_companies_extracts_only_experience_headers():
    from modules.resumes.profile import detect_companies
    companies = detect_companies(_RESUME_WITH_COMPANIES)
    assert companies == ["D Robotops", "BuildCo"]


def test_detect_companies_ignores_bare_year_lines_and_bullets():
    from modules.resumes.profile import detect_companies
    text = (
        "SUMMARY\n"
        "Led teams, shipped AI products - 5 years.\n"
        "2020 - 2022 some project, no clear header.\n"
        "PROFESSIONAL EXPERIENCE\n"
        "Acme Corp (SaaS) · Pune, India | Oct 2020 - Dec 2021\n"
    )
    assert detect_companies(text) == ["Acme Corp"]


def test_detect_companies_deduped_and_case_insensitive():
    from modules.resumes.profile import detect_companies
    text = (
        "PROFESSIONAL EXPERIENCE\n"
        "Acme Corp · Pune | Jan 2020 - Dec 2020\n"
        "acme corp · Mumbai | Jan 2021 - Dec 2021\n"
        "Beta Ltd · Remote | Feb 2022 - Present\n"
    )
    assert detect_companies(text) == ["Acme Corp", "Beta Ltd"]


def test_profile_record_includes_companies(tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text(_RESUME_WITH_COMPANIES, encoding="utf-8")
    record = resume_profile.detect_profile(str(p))
    assert record["ok"] is True
    assert record["companies"] == ["D Robotops", "BuildCo"]