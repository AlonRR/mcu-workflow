# CLAUDE.md — brief for Claude Code (real hardware bring-up)

You are running **on the user's machine** with a real shell and USB access —
the thing the Cowork assistant that built this repo could not do. Your job is to
take this project the last mile: **a real end-to-end run on two ESP32-C3 Super
Mini boards** (one satellite/test-instrument, one DUT).

## What this project is

A modular microcontroller workflow. `board.yml` is the single source of truth;
the `mcuflow` CLI is the deterministic conductor. Read `docs/architecture.md` for the
full design and `docs/runbook-c3.md` for the step-by-step two-C3 procedure. The whole
loop already runs in **simulation** (`mcuflow --sim run ...`); your task is the
real version.

## Already built and verified (no hardware)

- `mcuflow` CLI: verbs `validate scaffold build flash monitor test hil run up
  workbench ports bridge debug doctor env`; `--sim` runs build/flash/test with no
  toolchain.
- C3 DUT config: `examples/board-c3.yml` (LED=GPIO8 active-low,
  BOOT=GPIO9, native USB, 4MB). Scaffolds chip-correct (`set-target esp32c3`).
- DUT firmware: the scaffold now generates **real WiFi-join code** when
  `test.needs` includes `wifi` (`main/main.c` -> `wifi_join()`), printing
  `app_main started` then `wifi: connected to '<ssid>', got ip ...`.
- Satellite firmware, **ESP-IDF edition**: `src/satellite/firmware-idf/` (preferred,
  one toolchain for both boards). Arduino version still in `src/satellite/firmware/`.
- Workbench drives the satellite over HTTP: `mcuflow workbench --satellite COMx`.
- Launcher passes through **two** boards. `pytest` (tests/) is the regression.

## Your first tasks (in order)

0. `mcuflow doctor --fix` — the tool installs its own prerequisites (Python deps
   pyyaml/jsonschema/pyserial/esptool into a uv-managed `.venv`, usbipd-win on
   Windows, Docker if absent, and it pulls the ESP-IDF cage image). Re-run plain
   `mcuflow doctor` to confirm green. The cage side has the same:
   `mcuflow up doctor --fix`.
1. `pytest` — confirm the sim baseline is green.
2. `mcuflow doctor --satellite <SAT_PORT>` — check toolchain, both ports, ping.
3. Build + flash the **satellite** (`src/satellite/firmware-idf/`, `set-target
   esp32c3`). Verify: `mcuflow workbench --satellite <SAT_PORT>` then
   `curl -X POST http://127.0.0.1:6283/api/satellite/ping`.
4. `mcuflow run examples/board-c3.yml --port <DUT_PORT>
   --workbench http://127.0.0.1:6283` (drop `--sim`; this is real).
5. Confirm on the DUT serial that it booted AND printed the `wifi: connected`
   line while the satellite's AP was up.

## Known gaps you will likely hit (and how to handle)

- **Component REQUIRES drift:** the satellite/DUT `main/CMakeLists.txt` list
  `esp_wifi nvs_flash esp_netif esp_event` (+ `driver`/`json` for the satellite).
  If a name differs on the installed ESP-IDF point release, the build error names
  it — fix the REQUIRES line. This is expected agent work; the C is sound.
- **C3 native USB re-enumeration:** the port can drop/return around a flash or
  reset. Re-list ports if a command can't open one. Hold BOOT (GPIO9) low to
  force download mode if auto-reset into bootloader fails.
- **The `hil` verb's join assertion currently uses a modelled DUT.** For a fully
  on-silicon assertion, read the real DUT serial (idf.py monitor or pytest-
  embedded) and confirm the `wifi: connected` line. Wiring `hil` to read the real
  DUT serial instead of the model is the one remaining integration to finish.
- **WiFi creds:** firmware uses `WIFI_SSID="mcuflow-test"` / `WIFI_PASS=
  "password123"` (see `main.c` and `src/sim/hil.py`). Use the same when raising the
  AP, or change both sides together.

## Boundaries

Stay within the cage's intent (docs/architecture.md §6–7). Don't push to shared
remotes or exfiltrate secrets. Hardware on the bench is safe to iterate on; use
the satellite GPIO to reset/recover a wedged DUT rather than asking for hands.
