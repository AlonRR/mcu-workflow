---
name: release-check
description: >
  Pre-release / pre-push finalization checklist for this repo. Use when the user
  says "finalize before pushing", "release checklist", "is this ready to push",
  or "what needs doing before GitHub". Verifies license/metadata consistency, CI,
  changelog, and commit hygiene against the repo's standing rules.
---

# Release / pre-push check

Run through each section and report pass/fix. This is a verification pass — fix
what's wrong, then re-verify; do **not** push (that's the user's to do).

## 1. License & metadata consistency

- `LICENSE` present (MPL-2.0). The same license is declared in **both**
  `pyproject.toml` (`License ::` classifier) and `editors/vscode/package.json`
  (`"license": "MPL-2.0"`).
- README License section matches (MPL-2.0) — no leftover "not yet licensed" /
  "all rights reserved".
- Repo slug filled consistently (`AlonRR/mcu-workflow`) in README badges/links,
  `pyproject.toml` URLs, `editors/vscode/package.json` `repository`, and the
  install scripts (`install.sh`, `install.ps1`) — no `OWNER/REPO` placeholders.

## 2. CI uses uv (never pip)

- `.github/workflows/*.yml` install via `astral-sh/setup-uv` + `uv pip install`,
  and lint runs `uvx ruff`. No bare `pip install` or `actions/setup-python`-only
  paths. (Standing rule: this project always uses uv.)

## 3. Changelog

- `CHANGELOG.md` `[Unreleased]` section reflects what changed this cycle (new
  verbs, extension, license, CI, tools). Don't ship a finalize pass with an empty
  or stale Unreleased.

## 4. Quality gates green

```bash
uv run pytest                       # hardware-free regression
uv run --with ruff ruff check .     # lint (CI enforces)
uv run --with ruff ruff format --check .   # format (CI enforces)
# extension (if touched):
cd editors/vscode && npm run compile
```

## 5. Commit hygiene (hard rules)

- **Commit email MUST be the GitHub noreply address**
  `45129051+AlonRR@users.noreply.github.com` — never a personal email. Check
  `git config user.email` and scan recent history (`git log --format='%ae'`).
  If a personal email is in history or in files (e.g. `pyproject.toml` authors),
  it must be scrubbed (filter-repo mailmap + replace-text) **before** the first
  push.
- **Never add a `Co-Authored-By:` trailer** to any commit message.
- Prefer many small **logical** commits over one large one; if changes from
  different workstreams are interleaved, split them so each commit compiles/passes
  standalone.

## 6. Working tree

- `git status` clean (or only the intended changes staged). No stray scratch
  files, no `build-out/` or scaffold output committed.

## Report

Per section: ✅ pass / 🔧 fixed (what) / ⚠️ needs user (what + why). End with the
one action that's the user's: the actual `git push` — and flag if history was
rewritten (force-push + GitHub may cache old SHAs).
