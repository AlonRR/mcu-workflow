---
name: mcu-workbench-instruments
description: >
  Drive the networked workbench's instruments over its HTTP API: WiFi (AP +
  scan), GPIO stimulus/recovery, and the ESP32 satellite. Use when a test needs
  to exercise how the firmware communicates over WiFi (provisioning / joining an
  AP), or to pulse a DUT pin - e.g. hold BOOT low and pulse EN to force download
  mode or recover a wedged board.
---

# Workbench instruments

The workbench (`src/workbench/`) exposes hardware as one HTTP API on the LAN
(default port `6283`). The ESP32 satellite backs the WiFi radio and GPIO. Always
check `GET /api/capabilities` first and skip cleanly if an instrument isn't
present.

## What the API actually provides

Read-only: `GET /api/health`, `/api/info`, `/api/capabilities`, `/api/devices`
(discovered serial slots), `/api/satellite/caps`.

Actions (POST): `/api/satellite/ping`, `/api/wifi/ap_start`, `/api/wifi/ap_stop`,
`/api/wifi/scan`, `/api/gpio/set`, `/api/gpio/get`.

## Common patterns

**WiFi provisioning.** Raise an AP and confirm the DUT joins it (the DUT's
serial prints `wifi: connected ...`; read that from its monitor, not the
workbench):
```
POST /api/wifi/ap_start {"ssid":"mcuflow-test","password":"password123"}
POST /api/wifi/scan                  # see nearby networks
POST /api/wifi/ap_stop
```
Use the same SSID/PASS the firmware was built with (`mcuflow-test` /
`password123`; see `src/sim/hil.py` and the scaffolded `main.c`), or change both
sides together.

**GPIO stimulus / recovery.** The satellite's GPIO is wired to the DUT's
BOOT/EN (see `board.yml` `rig.dut_boot_gpio`). To force download mode or recover
a bootlooping DUT, hold BOOT low and pulse EN:
```
POST /api/gpio/set {"pin":<dut_boot_gpio>,"value":0}   # BOOT low
POST /api/gpio/set {"pin":<en_pin>,"value":0}          # pulse EN ...
POST /api/gpio/set {"pin":<en_pin>,"value":1}          # ... to reset
POST /api/gpio/get {"pin":<dut_boot_gpio>}
```

**Satellite health.** `POST /api/satellite/ping` -> `{"ok":true,"fw":...}`;
`GET /api/satellite/caps` for what the attached satellite reports.

## Rules

- Read `/api/capabilities` and route only to a host that has the instrument;
  skip (don't fail) a test whose instrument is absent.
- AP and STA are mutually exclusive on the one satellite radio.
- Report what the instrument observed (scan results, joined-then-`wifi:
  connected` on the DUT serial, GPIO read-back), not just `{"ok":true}`.

## Not yet available here

BLE, MQTT, OTA, UDP logging, and an HTTP-through-AP proxy are **not** implemented
in this workbench (see `agents/skills/README.md` "Planned"). Don't call endpoints
for them - check `/api/capabilities` and skip. (Network flashing over RFC2217 is
available separately via `mcuflow bridge`.)
