# Handoff / migration & resume guide

This file makes the project self-contained so the whole thing travels as **one
folder**. It captures the context that otherwise lives in the app's memory
(which is stored outside this folder and does NOT travel with a folder copy).

## Moving to a new PC

**Copy this one folder** to the new desktop:

```
C:\Users\alonr\Claude\Projects\micro-controller workflow
```

Put it anywhere you like on the desktop (e.g. a Claude project folder, or just
`C:\dev\micro-controller-workflow`). Everything the project needs is inside it.
You can zip it first if that's easier to transfer — there's nothing outside it
that's required.

> Note: the app's auto-memory (project facts/decisions) is saved per-machine and
> will not come along with the folder. That's why it's mirrored into this file.
> On the new PC, just point your assistant at this folder and at `docs/architecture.md`
> + this file; it can re-learn everything from here.

## What to install on the new desktop

Core: **nothing needs to pre-exist — not even Python.** The one-line installer
(or `mcuflow doctor --fix`) bootstraps **uv**, a standalone binary that provides
Python; the deps (pyyaml, jsonschema, pyserial, esptool) install into a
uv-managed project `.venv`.

Per-capability (install when you use that piece):
- **Docker Desktop + WSL2** — for the launcher/cage (you already have both).
- **ESP-IDF v6.0 via EIM** — for real `build`/`flash` (or use the cage image).
- **Arduino IDE / arduino-cli + ESP32 core + ArduinoJson** — to build the satellite firmware.
- **pyserial** — satellite host driver against a real board.
- **build123d + ocp_vscode** (and the OCP CAD Viewer VS Code extension) — enclosure preview/export.
- **pytest + pytest-embedded[-idf,-serial-esp]** — HIL tests.
- **Claude Code** (or another agent) — the in-cage agent; the launcher is agent-agnostic.

## Status

All 12 planned deliverables are built, and the end-to-end loop has now been run
on real hardware (two ESP32-C3 Super Minis) — see the session-3 update at the
bottom of this file for the details. In short: `mcuflow run board-c3.yml` is
**5/5 stages green** on real silicon (validate, scaffold, cage build, host
esptool flash, and an on-silicon HIL where the DUT joins the real satellite AP).

Still deeper than this bring-up exercised: the heavier workbench layers (RFC2217
serial proxy, auto-GDB, full BLE/MQTT/OTA actions), and the fully-locked-down
cage (egress allowlist proxy + docker network) which is wired but left open for
a first bench run.

## Resolved design decisions (mirror of project memory)

- `board.yml` is the **single source of truth** (one sectioned file; optional sections).
- The **CLI is the single canonical execution path** and is contract-first / language-agnostic
  (JSON in/out, documented exit codes). Implementation language is a swappable detail (Python now).
- **Orchestration is split**: deterministic conductor (the CLI — runs headless/CI, no model) vs
  judgment orchestrator (Claude — calls the same verbs, never the load-bearing sequencer).
- **Modules expose contracts; the conductor wires them** — nothing calls across modules directly,
  so each skill/agent/library is independently shippable. (The project is intentionally many
  deliverables, not one monolith.)
- Radio/GPIO test backend standardizes on an **ESP32 satellite over USB-serial** (transport-agnostic
  so a networked link can be added later). Onboard radios / USB dongles are fallbacks.
- The test rig is a **host-agnostic networked "workbench"** (not Pi-locked) — runs on Pi, mini-PC,
  or the dev box; capabilities are advertised and tests route to a host that has them.
- The agent runs in a **disposable cage**: permissions bypassed *inside*, boundary enforced *at the
  wall* (egress allowlist via internal-network + proxy, cap-drop, non-root, no secrets, audit).
- **CI host = GitHub Actions self-hosted runners**; labels carry the chip/instrument routing.
- **Environment default = the containerized cage even on the dev desktop**, opened by a one-step
  launcher (`mcuflow up`, CLI + GUI) that passes USB via usbipd→WSL2 on Windows and seats the agent.
- In-cage agent = **Claude Code by default, agent-agnostic**.
- Espressif **Docs MCP adopted** (ground decisions); **Tools MCP optional/complementary** (the CLI
  is the source of truth for build/flash).
- Stage 0 is a novice-friendly hardware-design assistant (BOM with live purchase links, wiring,
  power; KiCad only when justified) plus a build123d → FDM enclosure.

## Suggested next steps

1. **Prove it on hardware**: `python src/launcher/up.py doctor`, flash the satellite, walk a real
   `board.yml` through validate → scaffold → build → flash.
2. **Deepen the workbench** (#9) into the full instrument (RFC2217 proxy, auto-GDB, WiFi/BLE/OTA).
3. **Package** the folders into one installable `mcuflow` so `mcuflow up/validate/scaffold` are
   real commands with the sibling tools vendored.

## Recurring sandbox note

During the build session, the sandbox occasionally showed truncated copies of a few files due to a
file-sync glitch; the authoritative files were re-written complete. If any file looks cut off when
you open it on the new PC, it can be regenerated from `docs/architecture.md` + this guide.

## Update — 2026-06-11 (session 2): runnable interface + simulator

The workflow is now exercisable end to end **with no hardware**, and adapted to
the real target boards (2× ESP32-C3 Super Mini):

- **`examples/board-c3.yml`** — C3 DUT config (LED=GPIO8 active-low,
  BOOT=GPIO9 avoided, native-USB console, 4MB flash). Scaffolds to a chip-correct
  project (`set-target esp32c3`, `@pytest.mark.esp32c3`).
- **`sim/`** — a behavioural simulator: `src/satellite/host/sim.py` emulates the
  satellite firmware behind the real driver; `src/sim/dut.py` models the DUT; and
  `src/sim/hil.py` runs the workbench-mediated WiFi/GPIO HIL test through the **real**
  workbench HTTP API.
- **`src/workbench/workbench.py`** — now actually *drives* the satellite: POST
  endpoints for `wifi.ap_start/scan/ap_stop`, `gpio.set/get`, `ping`, selectable
  with `--satellite sim|COMx`. Cross-platform serial discovery (COM* on Windows).
- **`mcuflow`** — new `--sim` flag and `run` / `hil` / `up` / `workbench` verbs,
  so one command drives validate→scaffold→build→flash→HIL. Wrapper entry points
  in `bin/` (`mcuflow.bat` for Windows, `mcuflow` for POSIX).
- **`src/launcher/up.py`** — passes through **two** boards (DUT + satellite) via
  repeated `--device`/`--busid`; cross-platform serial listing.
- **`tests/smoke.py`** — hardware-free regression (7 checks); 18-point manual
  sweep also green.
- **`docs/runbook-c3.md`** — step-by-step two-C3 bring-up with the sim→real swap table.

Try it: `python src/mcuflow/mcuflow.py --sim run examples/board-c3.yml`.

Still hardware-gated (honest gaps): the satellite sketch is Arduino while the
cage is ESP-IDF (flash from host with arduino-cli, or rewrite the satellite on
ESP-IDF — pending decision); the DUT's WiFi-join code is still a generated stub;
and the `hil` verb asserts the join against a modelled DUT, so reading a *real*
DUT's serial to confirm the join on-silicon is the next integration layer.

### Addendum — firmware + handoff for the real run

- `src/satellite/firmware-idf/` — satellite rewritten on **ESP-IDF** (one toolchain
  builds both boards). Arduino version kept as the no-IDF fallback.
- Scaffold now emits **real WiFi-join firmware** for wifi boards (DUT joins the
  satellite AP, prints `wifi: connected ...`); CMake gains the wifi REQUIRES.
- `mcuflow doctor [--satellite ...]` — preflight: deps, toolchain, serial ports,
  satellite ping.
- `CLAUDE.md` — handoff brief auto-loaded by Claude Code on the board machine,
  with the exact real-run sequence and the known on-hardware gaps.

On-hardware verification is the remaining step (the sandbox can't compile C / reach
USB): build+flash both C3s and run `mcuflow run board-c3.yml --port <DUT>
--workbench http://127.0.0.1:8080` per `docs/runbook-c3.md` / `CLAUDE.md`.

## Update — 2026-06-12 (session 3): ran it on the real two C3s

Brought the project up on the actual hardware on a Windows host. The tool now
self-installs and runs end to end on real silicon; the codebase is under git
(see the commit history). What changed and what was observed:

- **Self-installing tool.** `mcuflow doctor --fix` provisions everything itself:
  a uv-managed `.venv` (pyyaml, jsonschema, pyserial, esptool), `usbipd-win` and
  Docker Desktop via winget if missing, starts the Docker engine, and pulls the
  ESP-IDF cage image. mcuflow re-execs into the `.venv` on every run.
- **Build in the cage, flash from the host.** With no native ESP-IDF, `mcuflow
  build` runs `idf.py` inside the Docker image (no USB passthrough needed) and
  `mcuflow flash`/`run` flash from the host with esptool straight to the C3's
  COM port. This sidesteps the fragile usbipd→WSL2→Docker USB bridge entirely;
  usbipd is only needed for the full caged-agent path (`mcuflow up`).
- **ESP-IDF v6.0 build drift fixed** (see firmware commit): cJSON is now the
  managed `espressif/cjson`; the split `esp_driver_*` components are required
  explicitly; `LINE_MAX` renamed.
- **Full run is green on hardware.** `mcuflow run board-c3.yml --port <DUT>
  --workbench http://127.0.0.1:8080` reports **5/5 stages PASS**: validate,
  scaffold, build (cage), flash (host esptool), and hil — where the hil reads the
  *real* DUT serial and confirms `app_main started` plus
  `wifi: connected to 'mcuflow-test', got ip 192.168.4.2` while the real satellite
  AP is up (DUT associates, WPA2-PSK, rssi ~-33 dBm).
- **The over-the-air join was an RF-proximity issue.** Initially the join looped
  at 802.11 auth (`reason=2`); the two PCB-antenna C3s sitting inches apart were
  desensing each other. **Separating them ~0.5 m fixed it immediately** (PMF and
  AP-only changes were already in but weren't the cause). If a join ever flaps,
  check board spacing first. Board identity is by `ping`, never by COM number (the
  C3 native USB re-enumerates and COM⇄busid can swap across reboots).
- **Boards as last seen:** satellite on COM6 (MAC e0:72:a1:70:d4:00, AP BSSID
  ...d4:01), DUT on COM9. Keep them ~0.5 m apart.
