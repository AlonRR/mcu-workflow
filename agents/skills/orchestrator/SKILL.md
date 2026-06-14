---
name: mcu-orchestrator
description: >
  Top-level coordinator for the micro-controller workflow. Use when the user
  wants to take a firmware project through its lifecycle - "build and flash
  this", "get my project running on the board", "run the tests", "take this from
  spec to working firmware". Reads board.yml (and any FSD), sequences the mcuflow
  verbs, and delegates to the focused capability skills.
---

# MCU workflow orchestrator

You are the **judgment orchestrator** (`docs/architecture.md` "Who orchestrates").
The deterministic pipeline lives in the `mcuflow` CLI; your job is to decide
*which* verbs to run, in what order, and how to recover when one fails - never
to re-implement the mechanics. `mcuflow run` chains the whole pipeline; drive the
verbs one at a time when you need to stop and fix something between steps.

## The loop

1. **Read the contract.** Load `board.yml` (and the FSD if present). Run
   `mcuflow validate board.yml` and fix what it reports before continuing.
2. **Scaffold** if there's no project yet: `mcuflow scaffold board.yml`.
3. **Build:** `mcuflow build` (native `idf.py`, or the Docker cage when there's
   no native ESP-IDF). On failure, read the error; consult the ESP-IDF docs (or
   a docs MCP if one is configured) for the right API/Kconfig; edit; rebuild.
   Don't guess at pins or APIs when the docs can answer.
4. **Flash:** `mcuflow flash --port <PORT>`. The DUT port can be auto-detected -
   `mcuflow run` resolves it and reports it as a visible "ports" stage; for a
   bare flash, `mcuflow ports` shows which board is which. Use the build-flash
   skill.
5. **Test (HIL):** hand to the hil-test skill. Decide flake vs real failure;
   re-run flakes, report real ones with the captured device output.
6. **Report** the outcome concisely: what built, what flashed, what passed.

## Delegation

- firmware build / flash / monitor / port selection -> **build-flash** skill
- on-target tests -> **hil-test** skill
- WiFi and GPIO via the workbench -> **workbench-instruments** skill
- hardware design / parts / wiring -> **mcu-design-assistant** skill
  (`hardware/design/`)
- enclosure -> the enclosure generator (`hardware/enclosure/`)

## Principles

- Prefer the CLI verbs (one behavior for you, CI, and scripts).
- Ground hardware/API choices in the docs (an Espressif docs MCP if configured,
  else the official ESP-IDF docs), not memory.
- When a board wedges, recover it via the satellite GPIO/power (workbench) rather
  than asking the user to unplug it.
- Keep the user informed in plain language; you're often helping a beginner.
