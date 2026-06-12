---
name: mcu-build-flash
description: >
  Build, flash, and monitor ESP32 firmware. Use when the user says "build",
  "compile", "flash", "upload", "monitor the serial", or "put this on the
  board". Drives the mcuflow CLI (which wraps idf.py / esptool), auto-detecting
  whether the board is on local USB or a networked workbench. Handles both
  ESP-IDF and PlatformIO projects.
---

# Build / flash / monitor

Use the `mcuflow` verbs; they are the canonical path (same behavior as CI).

```bash
mcuflow build                     # idf.py build, structured result
mcuflow flash --port <PORT>       # or auto-detect; via workbench if configured
mcuflow monitor --port <PORT>     # serial monitor (interactive)
```

## Steps

1. Confirm the toolchain: `mcuflow env doctor`. If `idf.py` is missing, the user
   should run inside the cage (`mcuflow up`) - suggest it.
2. `mcuflow build`. On error, read the message; if it's an API/Kconfig issue,
   query the **Docs MCP** before editing. Rebuild until clean.
3. Pick the port: from `mcuflow env doctor` / `project://devices`, or the
   workbench `/api/devices`. On a networked workbench, flash over RFC2217.
4. `mcuflow flash`, then `mcuflow monitor` to confirm the boot string from
   `board.yml` `test.boot_string` appears.

## Notes

- ESP-IDF vs PlatformIO is auto-detected by the project layout; the verbs are
  the same either way.
- After a flash, a board may re-enumerate; if serial doesn't come back, reset it
  (workbench `/api/serial/reset`) rather than power-cycling by hand.
- Report size/warnings from the build result, not the whole log.
