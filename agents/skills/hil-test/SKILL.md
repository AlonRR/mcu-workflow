---
name: mcu-hil-test
description: >
  Run hardware-in-the-loop tests on a real ESP32 and judge the results. Use when
  the user says "test", "run the HIL tests", "does it work on hardware", or after
  a flash. Drives pytest-embedded via mcuflow, and decides whether a failure is a
  flake (re-run) or real (report with the captured device log).
---

# HIL testing

```bash
mcuflow test pytest_<project>.py --target <chip>
```

## Steps

1. Check the instruments a suite needs. Read `board.yml` `test.needs` (e.g.
   `[serial, wifi]`) against the workbench `GET /api/capabilities` (or the runner
   labels). If a needed instrument is absent — or only experimental, like `ble`
   (wired and works in the simulator, but the on-silicon scan currently resets
   the C3) — say so and skip those tests rather than failing hard.
2. Run the suite with `mcuflow test`. pytest-embedded flashes the board and runs
   the on-target tests; the `test.boot_string` check confirms the firmware came
   up. For the full validate -> ... -> hil pipeline use `mcuflow run` (which also
   auto-detects and narrates the DUT port).
3. **Judge failures.** Re-run once if a failure looks like a flake (timeout, USB
   re-enumeration, transient WiFi join). If it persists it's real: report it with
   the captured device serial output, not just the assertion - the chip tells you
   why.
4. If the board is wedged/bootlooping, recover it via the satellite GPIO (force
   download mode: hold BOOT low and pulse EN through the workbench `/api/gpio/set`
   - see the workbench-instruments skill) and re-run, rather than asking the user
   to intervene.

## Output

Summarize: N passed / M failed, which instruments were exercised, and for any
real failure the relevant device-log excerpt. Keep it concise.
