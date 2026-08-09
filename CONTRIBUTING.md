# Contributing

Thanks for your interest in contributing to **Auto_job_applier_linkedIn**! All
contributions are welcome, no matter how small or large.

## 1. Sign the Contributor License Agreement (CLA)

Before your contribution can be merged, you must agree to the project's
**[Contributor License Agreement](CLA.md)**.

- **How you sign:** When you open a pull request, an automated bot
  ([CLA-assistant](https://cla-assistant.io/)) will comment with a link. Follow it
  and confirm that you agree to [`CLA.md`](CLA.md). Your agreement is recorded against
  your GitHub account. If the CLA changes later, you may be asked to agree again.
- **What you are agreeing to (plain English):** you grant the maintainer, **Sai
  Vignesh Golla (an individual)**, a broad, permanent license to your contribution —
  including the right to relicense it (even under proprietary terms) — while the
  project **stays free and open under AGPL-3.0**. You keep the right to use your own
  contribution elsewhere. Please read [`CLA.md`](CLA.md) for the full terms and the
  important "template — not legal advice" disclaimer.

> If you have contributed **before** this CLA existed, thank you! We may reach out to
> ask you to confirm the CLA applies to your already-merged work. See
> [`docs/contributor-consent/`](docs/contributor-consent/).

## 2. Follow the existing code guidelines

This project already documents its code style, naming conventions, configuration-variable
rules, and the **attestation format** for contributions. Please read and follow the
**Contributor Guidelines** section of the [README](README.md#-contributor-guidelines)
rather than duplicating it here. In particular:

- **Code guidelines** — function naming/docstrings/type hints, variable naming, and
  configuration-variable rules: see [README → Code Guidelines](README.md#code-guidelines).
- **Attestation** — every contribution needs an attestation marker in the code, in the
  form:

  ```python
  ##> ------ <Your full name> : <github id> OR <email> - <Type of change> ------
      # your code
  ##<
  ```

  See [README → Attestation](README.md) for full examples. Keeping accurate attestation
  markers also helps us maintain the contributor records in
  [`docs/contributor-consent/contributors.md`](docs/contributor-consent/contributors.md).

## 3. Where to send pull requests

Per the README, **pull requests should target the `community-version` branch**, not
`main`. PRs to other branches (especially `main`) are declined by default. Once your
change is tested, it is merged into `main` in the next cycle. See
[README → Contributor Guidelines](README.md#-contributor-guidelines) for details.

## 4. Quick checklist before opening a PR

- [ ] My PR targets the `community-version` branch.
- [ ] I followed the code and attestation guidelines in the [README](README.md#-contributor-guidelines).
- [ ] I added an attestation marker for my change.
- [ ] I have read and agreed to the [CLA](CLA.md) (the bot will prompt me).
- [ ] My contribution is my own work, or I have the right to submit it.

Thank you for helping improve the project!
