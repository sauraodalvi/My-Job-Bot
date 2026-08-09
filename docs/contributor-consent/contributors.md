# Past contributors to contact for retroactive CLA consent

> ## ⚠️ TEMPLATE / WORKING DOCUMENT — NOT LEGAL ADVICE
>
> This list supports the effort to ask **past** contributors to confirm that the
> project's [Contributor License Agreement](../../CLA.md) applies to their
> already-merged contributions. It is a working record, not legal advice. Have a
> lawyer confirm the approach before relying on any consent collected here.

## Purpose

The project historically had **no CLA**. This file lists the **external** past
contributors (everyone except the maintainer, Sai Vignesh Golla / `GodsScion`) whose
already-merged work we want covered by [`CLA.md`](../../CLA.md). Use the
[outreach email](outreach-email.md) to contact each person and the
[retroactive consent form](retroactive-consent.md) to record their agreement.

## How this list was derived (evidence)

This list was built from the repository's own history and in-code attestation
markers, cross-checked three ways:

1. **`git shortlog -sne`** on `origin/main` — every distinct author name + email and
   their commit count.
2. **In-code attestation markers** — `grep -rn "##>" --include="*.py" --include="*.html" .`
   (the project's `##> ------ Name : github-id OR email - Type ------ ... ##<` format
   documented in the README).
3. **Merge-commit PR references** — `git log --merges` — to recover each contributor's
   **GitHub username** and **PR number** from the merged branch (e.g.
   `Merge pull request #46 from WINDY-WINDWARD/...`).

The maintainer **Sai Vignesh Golla** (`GodsScion`; emails `saivigneshgolla@outlook.com`
and `100998531+GodsScion@users.noreply.github.com`) is **excluded** — he is the party
receiving the grant, not a party to contact.

**Caveats to verify before contacting people:**

- Email addresses come from git commit metadata and may be stale.
- Where a GitHub username was taken from a `...@users.noreply.github.com` email or a
  merge-commit branch source, it is reliable; a few real-name authors (Jason Fry, Eric
  Zhang) map to GitHub handles only via the PR that merged their work — those are noted
  and marked **(confirm)**.
- Commit counts include merge commits, so they approximate effort rather than measure it.

## External contributors (excluding the maintainer)

| # | Name | GitHub | Email(s) (from git) | Commits | PR(s) | Attestation in code? | What they contributed |
|---|------|--------|---------------------|:-------:|-------|:--------------------:|-----------------------|
| 1 | **Karthik Sarode** | [`WINDY-WINDWARD`](https://github.com/WINDY-WINDWARD) | karthik.sarode23@gmail.com | 7 | #46 | Yes | Flask app + "Applied Jobs history" web UI (`app.py`, `templates/index.html`); fuzzy-logic matching for location-based questions (`runAiBot.py`); related README updates. |
| 2 | **Dheeraj Deshwal** | [`Dheeraj9811`](https://github.com/Dheeraj9811) | dheeraj20194@iiitd.ac.in; dheerajdeshwal9811@gmail.com | 5 | #40, #41 | Yes | "Answer unknown questions using AI" / user-information feature (`runAiBot.py`, `config/questions.py`, `modules/ai/prompts.py`, `modules/ai/openaiConnections.py`); AI skill-extraction & multi-select double-click bug fix (`modules/clickers_and_finders.py`). |
| 3 | **Yang Li** | [`MARKYangL`](https://github.com/MARKYangL) | tendernesscurtain@gmail.com | 1 | #50 | Yes | DeepSeek AI integration (`modules/ai/deepseekConnections.py`) plus related feature hooks in `runAiBot.py`, `modules/validator.py`, `modules/ai/prompts.py`, `config/secrets.py`. |
| 4 | **Tim L** | [`tulXoro`](https://github.com/tulXoro) | tulxoro@hotmail.com | 5 | #63, #65 | Yes | Refactor for multi-LLM compatibility / removing DeepSeek-specific assumptions (`config/secrets.py`, `modules/ai/openaiConnections.py`, `modules/ai/deepseekConnections.py`, `modules/validator.py`). |
| 5 | **Iliya Brook** | [`IliyaBrook`](https://github.com/IliyaBrook) | iliyabrook1987@gmail.com | 5 | #96 | No | Fallback "Easy Apply" detection via URL pattern (`openSDUIApplyFlow`) in `runAiBot.py`. |
| 6 | **ArshCypherZ** | [`ArshCypherZ`](https://github.com/ArshCypherZ) | weebarsh@protonmail.com | 3 | #61 | No | Google Gemini support (`modules/ai/geminiConnections.py`, `test_gemini.py`); date-parsing fixes; OpenAI positional-argument fix (`runAiBot.py`, `modules/validator.py`, `config/secrets.py`). |
| 7 | **Jason Fry** | [`tillydray`](https://github.com/tillydray) **(confirm)** | small.job8148@fastmail.com | 1 | #43 | No | Made the LLM `temperature` parameter optional (`modules/ai/openaiConnections.py`). |
| 8 | **Eric Zhang** | [`EricZhang2`](https://github.com/EricZhang2) **(confirm)** | yansongzhang@outlook.com | 1 | #39 | No | Fixed a select-then-deselect bug in the LinkedIn job filters (`runAiBot.py`). |
| 9 | **M4NU5** | [`M4NU5`](https://github.com/M4NU5) | 31220123+M4NU5@users.noreply.github.com | 1 | #35 | No | Pagination fix: match on the button element, not the `li` (`runAiBot.py`). |
| 10 | **yeswanthmaturi** | [`yeswanthmaturi`](https://github.com/yeswanthmaturi) | 137012121+yeswanthmaturi@users.noreply.github.com | 1 | #71 | No | Raised the CSV field-size limit and added safe truncation for CSV writing (`modules/helpers.py`, `runAiBot.py`). |

**Total: 10 external contributors** (consistent with the expected "~5–11" range).

## Outreach tracking

Fill this in as you contact people. Consent is recorded via
[`retroactive-consent.md`](retroactive-consent.md).

| # | Name | Contacted (date) | Method | Consent received (date) | Notes |
|---|------|------------------|--------|-------------------------|-------|
| 1 | Karthik Sarode |  |  |  |  |
| 2 | Dheeraj Deshwal |  |  |  |  |
| 3 | Yang Li |  |  |  |  |
| 4 | Tim L |  |  |  |  |
| 5 | Iliya Brook |  |  |  |  |
| 6 | ArshCypherZ |  |  |  |  |
| 7 | Jason Fry |  |  |  |  |
| 8 | Eric Zhang |  |  |  |  |
| 9 | M4NU5 |  |  |  |  |
| 10 | yeswanthmaturi |  |  |  |  |

## Open questions for the lawyer

- Is retroactive consent from every past contributor **required** to relicense, or is
  it a risk-reduction step? What happens for contributors who do not respond?
- For contributions too small to be independently copyrightable (e.g. a 2-line fix),
  is consent needed at all?
- Does the existing in-code **attestation** create any expectation or obligation
  regarding attribution that survives relicensing?
