# Satellite command protocol (deliverable #8)

The ESP32 **satellite** is the default, host-agnostic backend for the radio/GPIO
instruments (WiFi / BLE / GPIO / signal). The workbench (or any host) drives it
over **USB-serial**, 115200 baud, with a simple line protocol:

- **Request:** one JSON object per line (`\n`-terminated): `{"cmd": "...", ...}`
- **Response:** one JSON object per line: `{"ok": true|false, ...}` (or `"error"`)

Transport-agnostic by design (`docs/architecture.md` §13): USB-serial is the default;
the same line protocol can later run over TCP for a remotely-placed satellite.

## Commands

| `cmd` | Args | Response |
|-------|------|----------|
| `ping` | — | `{"ok":true,"fw":"sat-0.1"}` |
| `caps` | — | `{"ok":true,"capabilities":["wifi","ble","gpio"]}` |
| `wifi.ap_start` | `ssid`, `password?`, `channel?` | `{"ok":true,"ip":"192.168.4.1"}` |
| `wifi.ap_stop` | — | `{"ok":true}` |
| `wifi.scan` | — | `{"ok":true,"networks":[{"ssid","rssi"}]}` |
| `ble.scan` | `timeout?` | `{"ok":true,"devices":[{"addr","name","rssi"}]}` |
| `ble.write` | `addr`, `char`, `data` (hex) | `{"ok":true}` |
| `gpio.set` | `pin`, `value` (0/1) | `{"ok":true}` |
| `gpio.get` | `pin` | `{"ok":true,"value":0}` |

Unknown commands return `{"ok":false,"error":"unknown cmd: <x>"}`. Malformed
JSON returns `{"ok":false,"error":"bad json"}`.

## Why JSON lines

Trivial to produce/parse on both sides, human-readable for debugging over a
serial monitor, and extensible (add a `cmd` without breaking older clients).
