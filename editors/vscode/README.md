# MCU Flow — VS Code extension

A GUI for the `mcuflow` CLI (in the root of this repository). It doesn't reimplement anything;
it surfaces the verbs you already run — build, flash, monitor, run, HIL — as
buttons, a board view, and a command palette, the way PlatformIO wraps its CLI.

## What you get

- **Home page** (PlatformIO-Home style): a landing panel with New Project,
  Open Folder, and quick actions, plus a live status snapshot (Doctor + boards).
  Opens on startup (toggle with `mcuflow.home.showOnStartup`).
- **New Project**: an in-editor panel that asks only for a folder + name, writes
  a starter `board.yml`, and opens it — then a Configure step fills in
  platform / chip / devices / test needs (or you refine it with the agent).
- **Project recognition**: a folder containing a `board.yml` is detected as an
  MCU Flow project (the way PlatformIO keys off `platformio.ini`); project-only
  actions appear only when one is open.
- **Status bar** (bottom-left): Build · Flash · Monitor · Port picker.
- **Activity-bar view "MCU Flow"**:
  - **Boards** — connected serial ports from `mcuflow --json ports`, each tagged
    with its detected role (DUT / satellite) and USB serial. Click one to select
    it as the port for flash/monitor/run.
  - **Project** — per-verb actions (Configure, Build, Flash, Monitor, Run, …),
    shown only when a project is open.
  - **Tools** — New Project, Home, Port Viewer, Workbench, Bridge, Debug.
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
| `mcuflow.path` | `""` | Explicit launcher path, the `mcuflow.py` script, or the repo folder; empty = auto-detect. |
| `mcuflow.boardFile` | `examples/board-c3.yml` | `board.yml` passed to run/validate/scaffold. |
| `mcuflow.simulate` | `false` | Add `--sim` to build/flash/test/run. |
| `mcuflow.home.showOnStartup` | `true` | Open the Home page when a window starts. |

## Develop

```bash
npm install
npm run compile      # tsc -> out/
# press F5 in VS Code to launch an Extension Development Host
```

Package a `.vsix` with `npx @vscode/vsce package`.

## Acknowledgements & disclaimer

The design of this extension is inspired by **[PlatformIO IDE](https://github.com/platformio/platformio-vscode-ide)**
and PlatformIO's approach of wrapping a CLI in a VS Code GUI — the Home page, the
activity-bar view, and recognizing a project by a contract file (PlatformIO keys
off `platformio.ini`; MCU Flow keys off `board.yml`).

MCU Flow is an **independent project — not affiliated with, endorsed by, or
derived from PlatformIO**, and it contains **no PlatformIO code**. It is an
original implementation that wraps this repository's `mcuflow` CLI. "PlatformIO"
and related names/marks belong to their respective owners.
