---
name: mcu-build-flash
description: >
  Build, flash, and monitor ESP32 firmware. Use when the user says "build",
  "compile", "flash", "upload", "monitor the serial", or "put this on the board".
  Drives the mcuflow CLI, which wraps idf.py / esptool (or builds in the Docker
  cage when there's no native ESP-IDF). ESP-IDF projects today; other toolchains
  plug in behind the platform adapter.
---

# Build / flash / monitor

Use the `mcuflow` verbs; they are the canonical path (same behavior as CI).

```bash
mcuflow build                     # idf.py build (or the cage), structured result
mcuflow flash --port <PORT>       # host esptool over the COM port (or idf.py)
mcuflow monitor --port <PORT>     # serial monitor (interactive)
```

## Steps

1. Confirm the toolchain: `mcuflow doctor`. If `idf.py` is missing, `build` still
   works through the Docker cage; if even Docker is absent, run `mcuflow doctor
   --fix` (or work inside `mcuflow up`).
2. `mcuflow build`. On error, read the message; if it's an API/Kconfig issue,
   consult the ESP-IDF docs (or a docs MCP if one is configured) before editing.
   Rebuild until clean. Report size/warnings from the result, not the whole log.
3. Pick the port. `mcuflow run` auto-detects the DUT, but for a bare
   `flash`/`monitor` choose it explicitly: `mcuflow ports` (or `mcuflow ports
   --list`) shows each board, its USB serial, and which is DUT vs satellite;
   `mcuflow doctor` lists the ports; a networked workbench lists them at
   `GET /api/devices`.
4. `mcuflow flash --port <PORT>`, then `mcuflow monitor --port <PORT>` to confirm
   the boot string from `board.yml` `test.boot_string` appears.

## Network flash (RFC2217)

To flash a board attached to another machine, run `mcuflow bridge --port <COM>
--tcp 4000` there, then flash from anywhere with `--port rfc2217://<host>:4000`.
The serial path works over the network; on the C3's native USB, put the board in
download mode first (hold BOOT, or pulse it via the satellite GPIO) since
auto-reset doesn't carry over RFC2217.

## Notes

- With no native ESP-IDF, `build` runs in the cage image and `flash` uses host
  `esptool` over the COM port - no toolchain install needed.
- After a flash the C3's native USB can re-enumerate; if the port doesn't come
  back, re-list with `mcuflow ports`, or drive the satellite GPIO to reset the
  DUT (workbench `/api/gpio/set`) rather than power-cycling by hand.
- ESP-IDF is the only adapter implemented today; the verbs don't change when
  others land.
