# Micro-controller workflow

A modular toolkit that speeds up the full microcontroller workflow — from hardware design and part selection, through firmware build/flash, to hardware-in-the-loop (HIL) testing and a 3D-printable enclosure. Target-first **ESP32**, designed to generalize (STM32 / RP2040 / Zephyr via adapters). It is deliberately **many small, independently-useful pieces** rather than one monolith, coordinated by a deterministic CLI and optionally an AI agent running in a sandboxed "cage".

Start with **`ARCHITECTURE.md`** (the full plan and the rationale for every decision) and **`HANDOFF.md`** (status + how to resume, especially on a new machine).

## Folder map

| Folder | Deliverable | What it is | Verified in sandbox |
|--------|-------------|------------|---------------------|
| `board-schema/` | #1 | `board.yml` schema + friendly validator (the single source of truth) | yes |
| `project-template/` | #3 | scaffold: `board.yml` → buildable ESP-IDF project | yes |
| `mcuflow/` | #2 | the conductor CLI (validate/scaffold/build/flash/test/env, JSON, exit codes) | yes |
| `launcher/` | #4 | `mcuflow up`: open the cage, pass USB through, seat the agent | dry-run only |
| `design/` | #6 | Stage 0 design assistant: BOM + purchase links, wiring, power; + skill | yes |
| `enclosure/` | #7 | parametric build123d enclosure → STL/3MF for FDM | yes |
| `cage/` | #5 | sandbox + egress-allowlist proxy (boundary enforcement) | topology + allowlist |
| `workbench/` | #9 | host-agnostic HTTP test instrument (capabilities, device discovery) | yes |
| `satellite/` | #8 | ESP32 radio/GPIO backend: protocol + firmware + host driver | driver only |
| `skills/` | #10 | agent skills: orchestrator, build-flash, hil-test, workbench-instruments | n/a (markdown) |
| `sim/` | — | hardware-free simulator: emulated satellite + DUT, the workbench-mediated HIL run (`mcuflow --sim`) | yes |
| `tests/` | — | `smoke.py`: end-to-end regression with no toolchain/boards | yes |
| `adapters/` | #12 | platform adapters (esp32 supported; stm32/rp2040/zephyr experimental) | yes |
| `ci-templates/` | #11 | GitHub Actions build gate + self-hosted HIL stage | valid YAML |

Each folder has its own `README.md`.

## Quick start

Only Python 3.10+ needs to pre-exist — the tool installs the rest itself.

```bash
# The tool provisions its own prerequisites: a uv-managed .venv with the Python
# deps (pyyaml, jsonschema, pyserial, esptool), plus usbipd-win / Docker / the
# ESP-IDF cage image when you go to real hardware.
python mcuflow/mcuflow.py doctor --fix

# Run the WHOLE loop with no toolchain and no boards (simulation):
python mcuflow/mcuflow.py --sim run board-schema/examples/board-c3.yml -o ./my-project
# -> validate -> scaffold -> build -> flash -> workbench-mediated HIL, all green

# Reverse the install: removes the .venv, build artifacts, and the cage container
# (add --purge to also drop the ~15GB cage image and usbipd-win). Never touches
# Docker Desktop or uv, which pre-exist.
python mcuflow/mcuflow.py doctor --uninstall

python tests/smoke.py                      # hardware-free regression check
```

On Windows, put `bin\` on your PATH and the command is just `mcuflow ...`
(`bin/mcuflow` on POSIX). Unified verbs: `validate scaffold build flash monitor
test hil run up workbench doctor env`. Add `--sim` to run build/flash/test with
no hardware; drop it (and add `--port`/`--workbench`) for the real boards. With
no native ESP-IDF, `build` runs in the Docker cage and `flash` uses host esptool
over the board's COM port — see `RUNBOOK-C3.md`.

**Two ESP32-C3 Super Minis end to end:** see **`RUNBOOK-C3.md`** — it walks the
sim run, the wiring, the two-board USB passthrough, and the sim-to-real swap.

## How the pieces fit

`board.yml` is the contract everything derives from. The `mcuflow` CLI is the deterministic conductor (CI, scripts, and the agent all go through it). The `launcher` opens a containerized **cage** where an agent (Claude Code by default) works with bypassed permissions inside but a hard boundary at the wall. Hardware is reached either over local USB or through the networked **workbench**, whose radio/GPIO instruments are backed by a cheap **ESP32 satellite**. See `ARCHITECTURE.md` for the full design.
