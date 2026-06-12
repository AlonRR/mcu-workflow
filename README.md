# mcu-workflow

A modular, contract-first toolkit for the whole microcontroller loop — hardware
design and part selection → firmware scaffold/build/flash → hardware-in-the-loop
(HIL) testing → a 3D-printable enclosure. Targets **ESP32** first and is designed
to generalize (STM32 / RP2040 / Zephyr via adapters).

It's deliberately **many small, independently-useful pieces** wired by one
deterministic CLI (`mcuflow`) — and, optionally, an AI agent running in a
sandboxed "cage". `board.yml` is the single source of truth everything derives
from.

<!-- After pushing to GitHub, enable the badge:
[![smoke](https://github.com/<owner>/<repo>/actions/workflows/smoke.yml/badge.svg)](../../actions/workflows/smoke.yml)
-->

## Quick start

Only **Python 3.10+** needs to pre-exist — the tool installs the rest itself.

```bash
# 1. Provision prerequisites into a project-local uv .venv (pyyaml, jsonschema,
#    pyserial, esptool) — plus usbipd-win / Docker / the ESP-IDF cage image when
#    you go to real hardware. Nothing else needs to be installed by hand.
python src/mcuflow/mcuflow.py doctor --fix

# 2. Run the WHOLE loop with no toolchain and no boards (simulation):
python src/mcuflow/mcuflow.py --sim run examples/board-c3.yml -o ./my-project
#    validate -> scaffold -> build -> flash -> workbench-mediated HIL, all green

python tests/smoke.py        # hardware-free regression (also runs in CI)
```

Put `bin/` on your PATH and it's just `mcuflow ...` (`bin/mcuflow` on POSIX,
`bin\mcuflow.bat` on Windows). Verbs: `validate scaffold build flash monitor test
hil run up workbench doctor env`. Add `--sim` for no hardware; drop it (and add
`--port`/`--workbench`) for real boards. With no native ESP-IDF, `build` runs in
the Docker cage and `flash` uses host `esptool` over the board's COM port.

To undo the install: `mcuflow doctor --uninstall` (add `--purge` to also drop the
~15 GB cage image and usbipd-win; never touches Docker Desktop or uv).

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
examples/       sample board.yml files
hardware/       Stage-0 helpers: BOM/wiring (design/) and the FDM case (enclosure/)
deploy/         the cage's egress-allowlist proxy + compose
ci-templates/   GitHub Actions you copy into a generated project
bin/            mcuflow / mcuflow.bat entry points
tests/          smoke.py — hardware-free regression
docs/           human documentation  (see docs/README.md)
agents/         material for AI coding agents  (see agents/README.md)
CLAUDE.md       brief auto-loaded by Claude Code (kept at root by convention)
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

## License

Not yet licensed. Until a `LICENSE` is added, all rights are reserved — open an
issue if you'd like to use it.
