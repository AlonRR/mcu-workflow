#!/usr/bin/env python3
"""
satellite_driver.py - host-side driver for the ESP32 satellite (deliverable #8).

Speaks the JSON-line protocol (see ../protocol.md) over any transport that
provides write(bytes) and readline()->bytes. Use `Satellite.open_serial(port)`
for a real board (needs pyserial), or inject a fake transport for tests.
"""
from __future__ import annotations

import json
import time


def _extract_json_obj(line):
    """Pull the first JSON object out of a line, even if boot-log noise precedes
    it (a real board prints bootloader/esp_image logs on the same USB-Serial/JTAG
    console before app_main can silence them). Returns a dict or None."""
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    i = line.find("{")
    dec = json.JSONDecoder()
    while i != -1:
        try:
            obj, _end = dec.raw_decode(line[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        i = line.find("{", i + 1)
    return None


class Satellite:
    # How long to keep listening for a JSON reply, and how often to re-send the
    # command while the board is still coming up after an open-induced reset.
    read_window = 8.0
    resend_every = 1.5

    def __init__(self, transport):
        self.t = transport

    def _rpc(self, cmd, **kw):
        payload = (json.dumps({"cmd": cmd, **kw}) + "\n").encode("utf-8")
        deadline = time.monotonic() + self.read_window
        next_send = 0.0
        last = ""
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self.t.write(payload)
                try:
                    self.t.flush()
                except Exception:
                    pass
                next_send = now + self.resend_every
            raw = self.t.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            last = line
            obj = _extract_json_obj(line)
            if obj is not None:
                return obj
        if last:
            return {"ok": False, "error": "no JSON response (last line: " + last + ")"}
        return {"ok": False, "error": "no response"}

    # --- protocol surface ---
    def ping(self):
        return self._rpc("ping")

    def caps(self):
        return self._rpc("caps")

    def wifi_ap_start(self, ssid, password="", channel=None):
        kw = {"ssid": ssid, "password": password}
        if channel is not None:
            kw["channel"] = channel
        return self._rpc("wifi.ap_start", **kw)

    def wifi_ap_stop(self):
        return self._rpc("wifi.ap_stop")

    def wifi_scan(self):
        return self._rpc("wifi.scan")

    def ble_scan(self, timeout=5):
        return self._rpc("ble.scan", timeout=timeout)

    def ble_write(self, addr, char, data_hex):
        return self._rpc("ble.write", addr=addr, char=char, data=data_hex)

    def gpio_set(self, pin, value):
        return self._rpc("gpio.set", pin=pin, value=value)

    def gpio_get(self, pin):
        return self._rpc("gpio.get", pin=pin)

    @classmethod
    def open_serial(cls, port, baud=115200, timeout=1.0):
        import serial  # pyserial; only needed for a real board
        # Short per-read timeout: _rpc loops and re-sends within read_window, so a
        # quick readline lets it ride out the board's post-reset boot noise.
        return cls(serial.serial_for_url(port, baudrate=baud, timeout=timeout))
