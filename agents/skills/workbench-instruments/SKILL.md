---
name: mcu-workbench-instruments
description: >
  Drive the networked workbench's wireless and protocol instruments - WiFi
  AP/STA, BLE, MQTT, UDP logging, OTA, and GPIO stimulus - over its HTTP API.
  Use when a test needs to exercise how the firmware *communicates*: WiFi
  provisioning/captive portal, BLE GATT, MQTT messaging, OTA update, reading
  logs when USB is busy, or pulsing a DUT pin to force a boot mode.
---

# Workbench instruments

The workbench (deliverable #9) exposes hardware as one HTTP API on the LAN. The
ESP32 satellite backs the radios/GPIO. Always check `GET /api/capabilities`
first and skip cleanly if an instrument isn't present.

## Common patterns

**WiFi provisioning.** Start an AP, wait for the DUT to join, drive its portal:
```
POST /api/wifi/ap_start {"ssid":"TestAP","password":"password123"}
GET  /api/wifi/ap_status            # see joined stations
POST /api/wifi/http {"method":"GET","url":"http://<dut-ip>/status"}
POST /api/wifi/ap_stop
```

**BLE.** `POST /api/ble/scan` -> `connect` -> `write` (hex) -> `disconnect`.

**GPIO stimulus / recovery.** Hold the DUT BOOT pin low and pulse EN to enter
download mode or a captive-portal boot; always release pins (`value:"z"`).

**UDP logging.** When USB is busy (HID gadget, mid-OTA), read device logs from
`GET /api/udplog?source=<ip>` instead of the serial monitor.

**OTA.** `POST /api/firmware/upload` then point the DUT's OTA URL at
`http://<workbench>:6283/firmware/<project>/<file>.bin`.

## Rules

- Read `/api/capabilities`; route only to a host that has the instrument.
- AP and STA are mutually exclusive on one radio.
- One BLE connection at a time.
- Report what the instrument observed (joined station, GATT response, log lines),
  not just success/failure.
