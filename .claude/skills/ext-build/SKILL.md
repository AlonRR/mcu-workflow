---
name: ext-build
description: >
  Build, type-check, and package the VS Code extension in editors/vscode. Use
  when the user says "build the extension", "compile the extension", "package
  the vsix", "check the extension", or after editing anything under
  editors/vscode/. Includes the webview-verification checklist (the part only a
  human can confirm).
---

# Build / package the VS Code extension

The extension lives in `editors/vscode/` and wraps the `mcuflow` CLI — it
reimplements nothing. All commands run from that folder.

## Compile (TypeScript → out/)

```bash
cd editors/vscode
npm install        # first time / after dependency changes
npm run compile    # tsc -p ./   (emits to out/)
npm run lint       # tsc --noEmit -p ./   (type-check only, no emit)
```

A green `compile`/`lint` means the TS type-checks. After editing any `.ts`,
re-run `compile` before claiming the change works.

## Package a .vsix

vsce is **not vendored** in `node_modules`, so run it via npx:

```bash
npx @vscode/vsce package --allow-missing-repository
```

Gotchas learned here:
- `--allow-missing-repository` silences a non-fatal warning when the manifest has
  no/old `repository` field. (The manifest now has one, but the flag is harmless.)
- An **old vsce** (e.g. v2.15.0) does **not** support `--skip-license` — it errors
  with "unknown option". Don't pass it; the `license` field in `package.json`
  (`MPL-2.0`) is what matters.

## Webview verification (human-in-the-loop)

The compiler cannot confirm rendered webviews. After a webview change, the user
must reload the Extension Development Host (F5, then reload window) and eyeball:

- **Home** page: cards render styled and are clickable.
- **New Project** panel: the `board.yml` preview updates live as fields are typed.
- CSP: no console errors about blocked inline scripts/styles (the webviews use a
  per-render nonce + `asWebviewUri` with external `media/*.css|js`).

Flag this step explicitly as "needs your ~30s eyeball" — don't mark a webview
change verified without it.

## Architecture invariants (don't break)

- Webviews share `src/webview.ts` (`esc`, `htmlShell`, `mediaUri`, nonce); CSS/JS
  live in `media/`, not inlined in `.ts`.
- The CLI is the single source of truth; the extension only surfaces its verbs.
  Quick reads (`ports`, `doctor`) use `--json`; streaming verbs run in a terminal.
