---
name: mcu-hil-test
description: >
  Run hardware-in-the-loop tests on a real ESP32 and judge the results. Use when
  the user says "test", "run the HIL tests", "does it work on hardware", or after
  a flash. Drives pytest-embedded via mcuflow, routes by chip/instrument, and
  decides whether a failure is a flake (re-run) or real (report with device log).
---

# HIL testing

```bash
mcuflow test pytest_<project>.py --target <chip>
```

## Steps

1. Make sure the right instruments are available. Read `board.yml` `test.needs`
   (e.g. `[serial, wifi, ble]`) and check the workbench `/api/capabilities`
   (or the runner labels). If a needed instrument is absent, say so and skip
   those tests rather than failing hard.
2. Run the suite with `mcuflow test`. pytest-embedded flashes the board and runs
   the on-target tests; the boot-string check confirms the firmware came up.
3. **Judge failures.** Re-run once if a failure looks like a flake (timeout, USB
   re-enumeration, transient join). If it persists, it's real: report it with
   the **captured device serial/JTAG output**, not just the assertion - the chip
   tells you why.
4. If the board is wedged/bootlooping, recover it (workbench GPIO download-mode /
   `/api/serial/recover`) and re-run, rather than asking the user to intervene.

## Output

Summarize: N passed / M failed, which instruments were exercised, and for any
real failure the relevant device-log excerpt. Keep it concise.
