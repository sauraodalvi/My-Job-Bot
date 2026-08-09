# Setting up CLA-assistant for future pull requests

> **Note:** This is a setup guide, not legal advice. The binding terms are in
> [`../../CLA.md`](../../CLA.md), which should be reviewed by a lawyer before you rely
> on it. This guide explains how to make new contributors accept that CLA
> automatically when they open a pull request.

## What CLA-assistant does

[CLA-assistant](https://cla-assistant.io/) is a free, open-source tool (maintained by
SAP) that:

- Comments on every new pull request asking the contributor to agree to your CLA.
- Records each contributor's agreement against their **GitHub account**.
- Sets a PR **status check** that stays "pending"/failing until every commit author in
  the PR has signed — so unsigned PRs are easy to spot and can be blocked from merging.
- **Re-prompts** contributors to sign again when the CLA text changes (see step 6).

There are two ways to run it. Pick one:

- **Option A — Hosted app at `cla-assistant.io`** (fastest; the CLA text lives in a
  GitHub Gist). Steps below.
- **Option B — [CLA Assistant Lite](https://github.com/contributor-assistant/github-action)**
  (a GitHub Action that runs entirely inside this repo; signatures are stored in a file
  in your repo/branch). Good if you'd rather not grant a third-party service access.
  Summary at the end.

---

## Option A — Hosted `cla-assistant.io` (recommended for speed)

### Step 1 — Put the CLA text where CLA-assistant can read it (a Gist)

The hosted service reads the CLA text from a **public GitHub Gist**.

1. Go to <https://gist.github.com> (signed in as `GodsScion`).
2. Create a **public** Gist. Name the file e.g. `CLA.md`.
3. Paste the **contents of [`../../CLA.md`](../../CLA.md)** into it, and **Create public
   gist**.
4. Copy the Gist URL — you'll need it in Step 4.

> Keep this Gist as the single source of truth that CLA-assistant shows contributors.
> Whenever you change [`CLA.md`](../../CLA.md) in the repo, update this Gist too (Step 6).

### Step 2 — Sign in to CLA-assistant

1. Go to <https://cla-assistant.io/>.
2. Click **Sign in with GitHub** and authorize the CLA-assistant OAuth app.
   - It requests permission to set up a webhook and status checks and to comment on
     PRs. Review the requested scopes before approving.

### Step 3 — Configure a new CLA

1. In the CLA-assistant dashboard, click **Configure CLA**.
2. Choose scope: select the repository **`GodsScion/Auto_job_applier_linkedIn`**
   (or configure it org-wide if you prefer it to cover all your repos).

### Step 4 — Point it at your CLA Gist

1. Paste the **Gist URL** from Step 1 as the CLA source.
2. (Optional) Add **custom fields** you want contributors to fill in when signing (for
   example: full name, email, country) — useful given the Indian-law signing questions
   flagged in `CLA.md`.
3. Save. CLA-assistant will install a **webhook** and a **status check** on the repo.

### Step 5 — Require the check before merging

1. In the repo: **Settings → Branches → Branch protection rules**.
2. Add/edit a rule for the branch you merge contributions into
   (**`community-version`**, and `main` if you want it there too).
3. Enable **"Require status checks to pass before merging"** and select the
   **CLA-assistant** check (e.g. `license/cla`).

Now: when someone opens a PR, the bot comments with a sign link; once they click and
agree, the check turns green and the PR becomes mergeable.

### Step 6 — Re-prompting when the CLA changes

CLA-assistant tracks the **revision** of the CLA source. When you meaningfully change
the CLA:

1. Update the **Gist** (edit it) so its content matches the new
   [`CLA.md`](../../CLA.md) — this creates a new Gist revision.
2. CLA-assistant will treat existing signatures as tied to the older revision, so
   contributors are asked to **sign again** on their next PR.
   - If needed, use the dashboard's **re-check / re-notify** controls to prompt
     re-signing.

> Keep [`CLA.md`](../../CLA.md), the Gist, and (if used) the Option-B signatures source
> in sync so contributors always see the current terms.

### Step 7 — Keep a link in the repo

`CONTRIBUTING.md` already tells contributors the bot will ask them to sign the CLA.
No extra change is needed, but double-check the link to [`CLA.md`](../../CLA.md) is
correct after setup.

---

## Option B — CLA Assistant Lite (self-hosted GitHub Action)

If you'd rather not grant a hosted service access, use the
[CLA Assistant Lite](https://github.com/contributor-assistant/github-action) Action:

1. Add a workflow (e.g. `.github/workflows/cla.yml`) using
   `contributor-assistant/github-action`.
2. Point `path-to-document` at your CLA (e.g. a link to `CLA.md` on the default branch)
   and set `path-to-signatures` to a JSON file (often stored on a dedicated
   `cla-signatures` branch).
3. Contributors sign by commenting a configured phrase (e.g. *"I have read the CLA
   Document and I hereby sign the CLA"*) on their PR; the Action records their GitHub
   login and commit info in the signatures file.
4. Configure it to require re-signing when the CLA changes (the Action supports
   invalidating signatures when the document/version changes).
5. Add the Action's check to branch protection as in Option A, Step 5.

This keeps everything — CLA text and signature records — inside the repository under
your control, at the cost of a little more setup.

---

## Notes and open questions for the lawyer

- Confirm that **electronic acceptance via CLA-assistant** is sufficient for the
  **license** grant in `CLA.md` (Section 2/11), and what, if anything, more is needed
  to make the **assignment** (Section 3) effective — see the § 19(1) flag in `CLA.md`.
- Decide whether to require the extra **custom fields** (name/email/country) at
  signing time to strengthen the record.
- Decide the policy for PRs from contributors who won't sign (typically: not merged).
