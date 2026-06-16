# mcu-workflow

A modular, contract-first toolkit for the whole microcontroller loop — hardware
design and part selection → firmware scaffold/build/flash → hardware-in-the-loop
(HIL) testing → a 3D-printable enclosure. Targets **ESP32** first and is designed
to generalize (STM32 / RP2040 / Zephyr via adapters).

It's deliberately **many small, independently-useful pieces** wired by one
deterministic CLI (`mcuflow`) — and, optionally, an AI agent running in a
sandboxed "cage". `board.yml` is the single source of truth everything derives
from.

[![smoke](https://github.com/AlonRR/mcu-workflow/actions/workflows/smoke.yml/badge.svg)](https://github.com/AlonRR/mcu-workflow/actions/workflows/smoke.yml)
[![lint](https://github.com/AlonRR/mcu-workflow/actions/workflows/lint.yml/badge.svg)](https://github.com/AlonRR/mcu-workflow/actions/workflows/lint.yml)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](https://www.mozilla.org/en-US/MPL/2.0/)

## Install (one line)

You don't need to install anything first — not even Python. The bootstrap
installs **uv**, a Python, the repo, and all prerequisites, and puts `mcuflow` on
your PATH.

**Windows** — PowerShell (from `cmd`, wrap it: `powershell -c "irm … | iex"`):

```powershell
irm https://raw.githubusercontent.com/AlonRR/mcu-workflow/main/install.ps1 | iex
```

**macOS / Linux / WSL / Git-Bash**:

```sh
curl -fsSL https://raw.githubusercontent.com/AlonRR/mcu-workflow/main/install.sh | sh
```

Then open a new terminal:

```sh
mcuflow doctor                                  # confirm everything is green
mcuflow --sim run examples/board-c3.yml -o ./my-project
```

The installer runs `mcuflow doctor --fix`, which provisions a project-local uv
`.venv` (pyyaml, jsonschema, pyserial, esptool) plus — for real hardware —
usbipd-win, Docker, and the ESP-IDF cage image. To undo it later:
`mcuflow doctor --uninstall` (add `--purge` to also drop the ~15 GB image and
usbipd-win; never touches Docker Desktop or uv).

## Run from a checkout

Cloned it yourself? You **still don't need a pre-existing Python** — uv provides
one. The project is a standard `pyproject.toml` package, so an editable install
pulls the dependencies and creates the `mcuflow` command in one step:

```sh
# install uv  (macOS/Linux/WSL/Git-Bash:)  curl -LsSf https://astral.sh/uv/install.sh | sh
#             (Windows PowerShell:)         irm https://astral.sh/uv/install.ps1 | iex

uv venv                                  # make a .venv (uv supplies Python)
uv pip install -e .                      # deps from pyproject + the `mcuflow` console script
uv run mcuflow --sim run examples/board-c3.yml -o ./my-project
uv run pytest             # hardware-free regression (also in CI)
```

`mcuflow doctor --fix` does exactly this `uv pip install -e .` for you, plus the
hardware prerequisites. (Already have Python 3.10+? `pip install -e .` works too.)

Put `bin/` on your PATH and it's just `mcuflow ...` (`bin/mcuflow` on POSIX,
`bin\mcuflow.bat` on Windows). Verbs: `validate scaffold build flash monitor test
hil run up workbench ports bridge debug doctor env`. Add `--sim` for no hardware; drop it (and
add `--port`/`--workbench`) for real boards. With no native ESP-IDF, `build` runs
in the Docker cage and `flash` uses host `esptool` over the board's COM port.
`mcuflow ports` opens a viewer that shows which board is on which COM port.

**Real hardware:** the two-ESP32-C3 bring-up is in
**[docs/runbook-c3.md](docs/runbook-c3.md)**.

## Repository layout

```
src/            the runtime (one module per deliverable)
  mcuflow/          the conductor CLI (validate…run, --sim, cage-build, host-flash)
  board-schema/     board.yml JSON Schema + friendly validator (source of truth)
  project-template/ scaffold a chip-correct ESP-IDF project from board.yml
  launcher/         `mcuflow up`: open the cage, pass USB through, seat the agent
  workbench/        host-agnostic HTTP test instrument
  satellite/        ESP32 test instrument: firmware + protocol + host driver
  sim/              behavioural DUT/satellite simulators + the HIL run
  adapters/         pluggable per-platform toolchain commands
  portviewer/       `mcuflow ports`: viewer of which board is on which COM port
  serialbridge/     `mcuflow bridge`: share a serial port over the network (RFC2217)
  debugger/         `mcuflow debug`: start an OpenOCD GDB server (JTAG)
examples/       sample board.yml files
hardware/       Stage-0 helpers: BOM/wiring (design/) and the FDM case (enclosure/)
deploy/         the cage's egress-allowlist proxy + compose
ci-templates/   GitHub Actions you copy into a generated project
editors/        editor integrations — the VS Code extension (editors/vscode/)
bin/            mcuflow / mcuflow.bat entry points
tools/          standalone dev/diagnostic helpers (e.g. satcheck.py)
tests/          hardware-free regression suite (run `pytest`)
docs/           human documentation  (see docs/README.md)
agents/         material for AI coding agents  (see agents/README.md)
CLAUDE.md       brief auto-loaded by Claude Code (kept at root by convention)
LICENSE         Mozilla Public License 2.0
pyproject.toml  package metadata + dependencies (the single source of truth)
cage.yaml       the launcher's cage configuration
```

## How the pieces fit

`board.yml` is the contract everything derives from. The `mcuflow` CLI is the
deterministic conductor (CI, scripts, and the agent all go through it). The
launcher opens a containerized **cage** where an agent works with bypassed
permissions inside but a hard boundary at the wall. Hardware is reached over
local USB or through the networked **workbench**, whose radio/GPIO instruments
are backed by a cheap **ESP32 satellite**. The whole loop also runs fully
simulated, so nothing here needs hardware to try.

See **[docs/architecture.md](docs/architecture.md)** for the full design and the
rationale behind each decision.

## Documentation

- **[docs/](docs/)** — architecture, the C3 runbook, and per-module references.
- **[agents/](agents/)** — onboarding brief, the portable project "memory"
  (handoff), and skill descriptors, for AI coding agents.

## Development

Parts of this project were developed with the assistance of an AI coding agent.

## Acknowledgements

The VS Code extension in [`editors/vscode/`](editors/vscode/) is inspired by
[PlatformIO IDE](https://github.com/platformio/platformio-vscode-ide) — its Home
page, activity-bar view, and the idea of recognizing a project by a contract
file (`platformio.ini` there, `board.yml` here). MCU Flow is an independent
project: it is **not affiliated with or endorsed by PlatformIO** and contains no
PlatformIO code.

## License

[Mozilla Public License 2.0](LICENSE) (MPL-2.0). You may use mcu-workflow in
open- or closed-source projects; if you modify mcu-workflow's own files and
distribute them, those changes must remain under MPL-2.0.
