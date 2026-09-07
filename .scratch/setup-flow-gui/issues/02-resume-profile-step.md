# 02: Resume step → Resume Profile

**What to build:** The "Your resume" step. A user attaches a PDF or Word resume
via a browse dialog (the only truly required input of the flow). The tool parses
it into a candidate profile and shows what it detected ("3+ years experience,
AI, Product Management") with a "Looks right" confirmation — the trust moment.
The uploaded file and the extracted profile are stored as separate records (a
Resume Profile), so the file is a snapshot and the extraction is inspectable.
Works the same in both UIs; pre-fills on re-run.

**Blocked by:** 01.

**Status:** done

- [x] Attaching a PDF or Word file via browse dialog produces a confirmation showing the file name.
- [x] The parser returns a candidate profile (years of experience, key skills) shown to the user with a "Looks right" confirmation.
- [x] The file and the extracted profile are stored as separate records, not one combined string.
- [x] The resume is the only genuinely required field; a user with the rest filled but no resume cannot finish.
- [x] Re-opening the flow pre-fills the resume step from what was saved.
- [x] Tests: extraction exercised as input→output transform reusing existing parser coverage; persistence writes file + profile separately.