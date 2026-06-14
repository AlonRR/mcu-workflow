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
    read_window = 8.0  # max wait for one reply (covers a blocking wifi.scan)
    ready_window = 8.0  # max wait for the board to come up after an open-reset
    ping_every = 1.5  # re-ping cadence during the readiness handshake only

    def __init__(self, transport):
        self.t = transport

    def _drain(self):
        """Discard buffered input so the next reply belongs to the next command.
        Without this, leftover boot-log noise or a duplicate reply would be read
        as the answer to a later command (a request/response desync)."""
        rib = getattr(self.t, "reset_input_buffer", None)
        if callable(rib):
            try:
                rib()
            except Exception:
                pass

    def _send(self, payload):
        self.t.write(payload)
        try:
            self.t.flush()
        except Exception:
            pass

    def _read_reply(self, deadline):
        """Read lines until a JSON object arrives or `deadline`. Returns
        (obj_or_None, last_nonempty_line)."""
        last = ""
        while time.monotonic() < deadline:
            raw = self.t.readline()
            if not raw:
                time.sleep(0.005)  # idle (real serial already blocked on timeout)
                continue
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            last = line
            obj = _extract_json_obj(line)
            if obj is not None:
                return obj, last
        return None, last

    def _rpc(self, cmd, **kw):
        # Send exactly once (no resends -> no duplicate replies to desync the
        # stream), after draining any stale input.
        self._drain()
        self._send((json.dumps({"cmd": cmd, **kw}) + "\n").encode("utf-8"))
        obj, last = self._read_reply(time.monotonic() + self.read_window)
        if obj is not None:
            return obj
        return {
            "ok": False,
            "error": "no JSON response" + (" (last line: " + last + ")" if last else ""),
        }

    def wait_ready(self):
        """Absorb the post-open reset: re-ping until the board answers, draining
        the bootloader/log noise that precedes app_main. Called once on open so
        no per-command resends (and their duplicate replies) are ever needed."""
        deadline = time.monotonic() + self.ready_window
        while time.monotonic() < deadline:
            self._send(b'{"cmd": "ping"}\n')
            window = min(deadline, time.monotonic() + self.ping_every)
            obj, _ = self._read_reply(window)
            if obj is not None:
                self._drain()  # clear any extra ping replies
                return True
        return False

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

    def siggen_start(self, pin, freq=1000, duty=50):
        return self._rpc("siggen.start", pin=pin, freq=freq, duty=duty)

    def siggen_stop(self):
        return self._rpc("siggen.stop")

    @classmethod
    def open_serial(cls, port, baud=115200, timeout=1.0):
        import serial  # pyserial; only needed for a real board

        # Short per-read timeout so _read_reply iterates promptly; wait_ready then
        # absorbs the board's open-induced reset before any real command is sent.
        inst = cls(serial.serial_for_url(port, baudrate=baud, timeout=timeout))
        inst.wait_ready()
        return inst
