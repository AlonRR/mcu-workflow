# satellite — ESP32 radio/GPIO backend (deliverable #8, Layer 0)

The chosen default backend for the workbench's radio/GPIO instruments. A second, cheap ESP32 runs a fixed firmware and provides WiFi / BLE / GPIO (and basic signal) over **USB-serial**, so *any* host gains those instruments from one identical part — no OS-specific dongles, works on Windows/macOS/Linux alike (`docs/architecture.md` §9, §13).

## Contents

- `protocol.md` — the JSON-line command protocol (the contract).
- `firmware-idf/` — the **ESP-IDF edition** (preferred): one toolchain — the same
  cage image — builds both this satellite and the DUT. Reports `fw: "sat-idf-0.1"`.
- `firmware/satellite.ino` — the Arduino edition (no-IDF fallback; ESP32 core +
  ArduinoJson, add NimBLE for BLE). Reports `fw: "sat-0.1"`.
- `host/satellite_driver.py` — the host-side driver; transport-injectable for tests, `Satellite.open_serial(port)` for a real board.

## Build the firmware

**Preferred (ESP-IDF):** in `firmware-idf/`, `idf.py set-target esp32c3` then
`idf.py -p <SAT_PORT> flash` — the cage builds it with the same toolchain as the
DUT (see `firmware-idf/README.md`).

**Fallback (Arduino):** open `firmware/satellite.ino` in the Arduino IDE (or
arduino-cli) with the ESP32 core installed, add the **ArduinoJson** library, and
flash any spare ESP32.

Either way the satellite is built and flashed *by the workflow it serves* — the
project's first dogfooding case.

## Use from the host

```python
from satellite_driver import Satellite
sat = Satellite.open_serial("/dev/ttyACM0")     # or COMx on Windows
print(sat.ping())                                # {'ok': True, 'fw': 'sat-idf-0.1'}
sat.wifi_ap_start("TestAP", "password123")       # drive provisioning tests
sat.gpio_set(4, 1)                               # stimulus to the DUT
```

The workbench (#9) advertises `wifi`/`ble`/`gpio` when a satellite is attached (`--enable wifi,ble,gpio`).

## Verifying

The host driver's protocol handling is verified against a simulated firmware (round-trips ping/caps/wifi/gpio and unknown-command handling). The firmware itself is verified by an on-device build + flash — it can't be compiled in the Linux sandbox.

## Transport note

USB-serial is the default. The same line protocol can run over TCP later for a remotely-placed satellite, without changing the driver surface (`docs/architecture.md` §13).
