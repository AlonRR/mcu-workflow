# workbench — networked test instrument (deliverable #9)

Turns any **Python + USB host** (Raspberry Pi, mini-PC, an old laptop, the dev box itself) into a shared test instrument reachable over the LAN. The core here uses only the Python standard library, so it runs anywhere; the radio/GPIO instruments are pluggable backends (default: the ESP32 satellite, deliverable #8) and are advertised, not assumed.

## Run

```bash
python workbench.py --port 6283                 # binds 0.0.0.0 for the LAN
python workbench.py --enable wifi,ble,gpio      # advertise satellite-backed instruments
```

## Endpoints

Reads (`GET`):

| Endpoint | Returns |
|----------|---------|
| `/api/health` | `{"ok": true}` |
| `/api/info` | hostname, platform, slot count, uptime |
| `/api/capabilities` | which instruments this host provides |
| `/api/devices` | discovered serial slots (devnode, RFC2217 url, chip) |
| `/api/satellite/caps` | capabilities the attached satellite reports |
| `/api/udplog?source&n` | device logs received over UDP (newest `n`, filter by ip) |
| `/api/firmware` | OTA images available to serve (`GET /firmware/<name>` downloads one) |
| `/api/mqtt/recent` | recent messages seen by the embedded broker |

Actions (`POST`):

| Endpoint | Does |
|----------|------|
| `/api/satellite/ping` | `→ {"ok": true, "fw": ...}` |
| `/api/wifi/ap_start`, `/api/wifi/ap_stop`, `/api/wifi/scan` | drive the satellite WiFi radio |
| `/api/gpio/set`, `/api/gpio/get` | satellite GPIO stimulus / read-back |
| `/api/siggen/start`, `/api/siggen/stop` | PWM signal on a satellite pin |
| `/api/firmware/upload` | stage an OTA image (`{name, data_b64}`) |
| `/api/mqtt/publish` | inject onto the embedded broker (also listening on TCP 1883) |
| `/api/ble/scan` | NimBLE observer scan (experimental on the C3 — see below) |

## Capability advertisement

This is the heart of the host-agnostic design (`docs/architecture.md` §9). `serial`, `udp_log`, and `ota` are always available; `gdb`/`mqtt` are auto-detected (OpenOCD/Mosquitto on PATH); `wifi`/`ble`/`gpio`/`siggen` are turned on by a backend (`--enable`, or `WORKBENCH_CAPS`). Tests declare what they need and are routed only to a host that advertises it — missing capabilities become skipped tests, never hard failures.

## Scope

Discovery + capability advertisement + the read endpoints are the always-on core. The satellite-backed action instruments above — WiFi/BLE/GPIO/siggen, the UDP-log buffer, the OTA repo, and the embedded MQTT broker — are built on top of it. `BLE scan` is wired end to end and works in the simulator, but the on-silicon NimBLE scan currently resets the C3 (experimental, pending on-device debugging). The two pieces that live **outside** the workbench process are the RFC2217 serial proxy and the OpenOCD/GDB server — shipped as the standalone `mcuflow bridge` and `mcuflow debug` verbs. Together this is what makes the agent's hardware story "one allowlisted network host" instead of USB passthrough.

## Verifying

```bash
python workbench.py --host 127.0.0.1 --port 8099 --enable wifi,ble &
curl -s localhost:8099/api/capabilities
curl -s localhost:8099/api/devices
```
