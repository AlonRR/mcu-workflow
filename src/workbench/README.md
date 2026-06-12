# workbench — networked test instrument (deliverable #9)

Turns any **Python + USB host** (Raspberry Pi, mini-PC, an old laptop, the dev box itself) into a shared test instrument reachable over the LAN. The core here uses only the Python standard library, so it runs anywhere; the radio/GPIO instruments are pluggable backends (default: the ESP32 satellite, deliverable #8) and are advertised, not assumed.

## Run

```bash
python workbench.py --port 8080                 # binds 0.0.0.0 for the LAN
python workbench.py --enable wifi,ble,gpio      # advertise satellite-backed instruments
```

## Endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /api/health` | `{"ok": true}` |
| `GET /api/info` | hostname, platform, slot count, uptime |
| `GET /api/capabilities` | which instruments this host provides |
| `GET /api/devices` | discovered serial slots (devnode, RFC2217 url, chip) |

## Capability advertisement

This is the heart of the host-agnostic design (`docs/architecture.md` §9). `serial`, `udp_log`, and `ota` are always available; `gdb`/`mqtt` are auto-detected (OpenOCD/Mosquitto on PATH); `wifi`/`ble`/`gpio`/`siggen` are turned on by a backend (`--enable`, or `WORKBENCH_CAPS`). Tests declare what they need and are routed only to a host that advertises it — missing capabilities become skipped tests, never hard failures.

## Scope

This is the **core** instrument: discovery + capability advertisement + the read endpoints. The serial proxy (RFC2217), auto-started GDB, WiFi/BLE/MQTT/GPIO actions, UDP-log buffer, and OTA repo are the next layers (they slot onto these endpoints and the satellite backend). The core is what makes the agent's hardware story "one allowlisted network host" instead of USB passthrough.

## Verifying

```bash
python workbench.py --host 127.0.0.1 --port 8099 --enable wifi,ble &
curl -s localhost:8099/api/capabilities
curl -s localhost:8099/api/devices
```
