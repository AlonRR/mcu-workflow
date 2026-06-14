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
(discovered serial slots), `/api/satellite/caps`, `/api/udplog` (device logs
received over UDP), `/api/firmware` + `/firmware/<name>` (OTA images),
`/api/mqtt/recent`.

Actions (POST): `/api/satellite/ping`, `/api/wifi/ap_start`, `/api/wifi/ap_stop`,
`/api/wifi/scan`, `/api/gpio/set`, `/api/gpio/get`, `/api/siggen/start`,
`/api/siggen/stop`, `/api/firmware/upload`, `/api/mqtt/publish`. The workbench
also runs an embedded MQTT broker on TCP 1883.

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

**Signal generator (PWM).** Drive a square wave on a satellite pin:
```
POST /api/siggen/start {"pin":4,"freq":2000,"duty":25}   # Hz, duty 0-100
POST /api/siggen/stop
```

**UDP logging.** When the DUT's USB serial is busy (HID gadget, mid-OTA), have
its firmware ship log lines as UDP datagrams to `<workbench-ip>:6284`, then read
them back:
```
GET /api/udplog?source=<dut-ip>&n=100   -> {"ok":true,"lines":[{t,src,line}]}
```

**OTA.** Upload an image, then point the DUT's OTA URL at it (the DUT firmware
pulls it via `esp_https_ota`):
```
POST /api/firmware/upload {"name":"app-v2.bin","data_b64":"<base64>"}
# -> {"ok":true,"url":"http://<workbench>:6283/firmware/app-v2.bin"}
GET  /api/firmware                      # list available images
GET  /firmware/app-v2.bin              # the DUT downloads this
```

**MQTT.** The workbench runs an embedded broker (TCP 1883). A DUT (or any MQTT
client) connects there to pub/sub; you can inject and inspect from the API:
```
POST /api/mqtt/publish {"topic":"sensors/temp","payload":"24.1"}
GET  /api/mqtt/recent                    # messages the broker has seen
```

**BLE (scan).** `POST /api/ble/scan {"timeout":5}` -> `{devices:[{addr,name,
rssi}]}` via the satellite's NimBLE observer. ⚠️ Known issue: on the ESP32-C3
the on-silicon scan currently resets the satellite (the software path and the
simulator work; the firmware crash needs on-device `idf.py monitor` debugging).
Treat ble.scan as experimental on real hardware. `ble.write` is not supported
(observer only).

**Satellite health.** `POST /api/satellite/ping` -> `{"ok":true,"fw":...}`;
`GET /api/satellite/caps` for what the attached satellite reports.

## Rules

- Read `/api/capabilities` and route only to a host that has the instrument;
  skip (don't fail) a test whose instrument is absent.
- AP and STA are mutually exclusive on the one satellite radio.
- Report what the instrument observed (scan results, joined-then-`wifi:
  connected` on the DUT serial, GPIO read-back), not just `{"ok":true}`.

## Not yet available here

An HTTP-through-AP proxy is **not** implemented in this workbench (see
`agents/skills/README.md` "Planned"). Don't call endpoints for it - check
`/api/capabilities` and skip. BLE scan is wired but experimental on hardware
(see above). (Network flashing over RFC2217 is available via `mcuflow bridge`.)
