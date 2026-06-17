---
name: docs-audit
description: >
  Audit and fix stale documentation across the repo. Use when the user says
  "fix the docs", "review the docs", "are the docs current", "doc audit", or
  after a change that adds/removes a CLI verb, a workbench endpoint, a board.yml
  field, or a module. Verifies every doc claim against the code (not memory) and
  corrects drift.
---

# Docs audit

The job is to find and fix documentation that has drifted from the code. The
rule that makes this worth doing: **verify each claim against ground truth in the
source, never against memory.** That is exactly where staleness hides (a verb
table listing 7 of 15 verbs, an endpoint list missing the ones that shipped).

## 1. Enumerate project-owned docs

```
Glob **/*.md
```

Then **exclude** vendored / generated trees — never edit these:
`.venv/`, `editors/vscode/node_modules/`, `build-out/`, `.pytest_cache/`, and any
`managed_components/`. What's left is the audit scope: the root docs
(`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CLAUDE.md`), `docs/`,
`agents/` (incl. `skills/*/SKILL.md`), every `src/*/README.md`, `hardware/*`,
`deploy/`, `ci-templates/`, and `editors/vscode/README.md`.

## 2. Establish ground truth (grep the code, don't trust the prose)

Pull the authoritative lists straight from source before reading any doc:

- **CLI verbs** — `Grep "add_parser\(" src/mcuflow/mcuflow.py`. The current set is
  the source of truth for every verb table and verb list (README, CLAUDE.md,
  `src/mcuflow/README.md`, skills).
- **Workbench endpoints** — `Grep "/api/" src/workbench/workbench.py`. Compare to
  what each doc claims the workbench provides vs. calls "next layers".
- **board.yml schema** — `src/board-schema/board.schema.json` (required fields,
  enums for `platform`/`framework`, `chip` is free-form). Validates any doc that
  describes the contract.
- **Adapters / platforms** — `src/adapters/` for supported vs. experimental.
- **Default ports, fw strings, file paths** — grep the actual constants
  (workbench port `6283`, satellite `sat-idf-0.1` vs Arduino `sat-0.1`).

## 3. Diff docs against ground truth and fix

For each doc, check: verb/endpoint/field lists complete and correct? Port
numbers, fw strings, file paths current? Status/next-steps sections describing
work that's already shipped? Cross-links resolve? Fix what's wrong.

Distinguish **stale fact** (fix it) from **dated record** (leave it):
- Design drafts (`docs/architecture.md`, `v0.x` headers) — preserve the original
  plan and rationale; only make additive corrections for concrete absences the
  user points at.
- Dated session logs (`agents/handoff.md` "Update — <date>") — append a new dated
  entry; don't rewrite old ones. *Undated* Status / Suggested-next-steps sections
  in the same file are live and should be corrected.

## 4. Report

List files changed and, per file, the one-line reason (what was stale → what's
correct). Note anything deliberately left alone and why. Do **not** commit unless
asked — if asked, follow the repo's commit conventions (see `release-check`).
