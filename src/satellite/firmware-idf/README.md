# Satellite firmware (ESP-IDF edition)

The radio/GPIO instrument backend, built with **ESP-IDF** so the cage's single
toolchain builds both this satellite and the DUT. Same JSON-line protocol as
`../protocol.md`; channel is the C3 Super Mini's native USB-Serial/JTAG.

```bash
idf.py set-target esp32c3
idf.py -p <SAT_PORT> flash
# verify over the workbench:
mcuflow workbench --satellite <SAT_PORT> &
curl -X POST http://127.0.0.1:8080/api/satellite/ping     # {"ok":true,"fw":"sat-idf-0.1"}
```

Implements: `ping`, `caps`, `wifi.ap_start|ap_stop|scan`, `gpio.set|get`.
`ble.*` returns "ble not built in this image" (add NimBLE later).

The Arduino sketch in `../firmware/satellite.ino` remains as the no-IDF
alternative; this IDF project is preferred for the caged workflow.
