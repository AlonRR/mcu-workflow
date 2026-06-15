# MCU Flow — VS Code extension

A GUI for the `mcuflow` CLI (in the root of this repository). It doesn't reimplement anything;
it surfaces the verbs you already run — build, flash, monitor, run, HIL — as
buttons, a board view, and a command palette, the way PlatformIO wraps its CLI.

## What you get

- **Status bar** (bottom-left): Build · Flash · Monitor · Port picker.
- **Activity-bar view "MCU Flow"** with three groups:
  - **Boards** — connected serial ports from `mcuflow --json ports`, each tagged
    with its detected role (DUT / satellite) and USB serial. Click one to select
    it as the port for flash/monitor/run.
  - **Actions** — one row per verb.
  - **Doctor** — toolchain/module status from `mcuflow --json doctor`, with an
    "Install prerequisites" action.
- **Command palette**: every verb under the `MCU Flow:` category.
- **Setup / onboarding**: `MCU Flow: Set Up Project` creates the uv-managed
  `.venv`, installs dependencies, and runs `doctor --fix`.

## How it runs the CLI

- Quick, structured reads (`ports`, `doctor`) are called with `--json` and parsed
  to feed the tree and status bar.
- Verbs that stream output or are interactive (build, flash, monitor, run,
  workbench, bridge, debug, up) run in a named VS Code **terminal** so you see
  live output and can Ctrl-C them.

## Finding `mcuflow`

Resolution order:

1. The `mcuflow.path` setting, if set.
2. Workspace `.venv` + `src/mcuflow/mcuflow.py` (preferred — no shell, no
   re-exec hop).
3. `bin/mcuflow` / `bin/mcuflow.bat`.
4. `mcuflow` on `PATH`.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `mcuflow.path` | `""` | Explicit launcher path; empty = auto-detect. |
| `mcuflow.boardFile` | `examples/board-c3.yml` | `board.yml` passed to run/validate/scaffold. |
| `mcuflow.simulate` | `false` | Add `--sim` to build/flash/test/run. |

## Develop

```bash
npm install
npm run compile      # tsc -> out/
# press F5 in VS Code to launch an Extension Development Host
```

Package a `.vsix` with `npx @vscode/vsce package`.
