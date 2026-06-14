#!/usr/bin/env python3
"""
sim.py - an in-process emulator of the ESP32 satellite firmware.

It implements the exact JSON-line protocol from ../protocol.md (and mirrors the
behaviour of ../firmware/satellite.ino) behind the same transport interface the
real serial link exposes: ``write(bytes)`` and ``readline() -> bytes``. That
means anything that drives a real satellite drives the simulator unchanged:

    from satellite.host.satellite_driver import Satellite
    from satellite.host.sim import SimSatelliteTransport
    sat = Satellite(SimSatelliteTransport())     # no board needed
    sat.ping()                                   # {'ok': True, 'fw': 'sat-sim-0.1'}

The simulator also keeps observable state (the running AP, GPIO levels) so a
test can assert on what the "hardware" did - and so a simulated DUT can ask the
sim whether an AP it should join is actually up.

This is what lets the whole two-board workflow run with zero hardware; swap the
transport for ``Satellite.open_serial(port)`` to talk to a real C3 instead.
"""

from __future__ import annotations

import json
from collections import deque

FW = "sat-sim-0.1"


class SimState:
    """Observable 'hardware' state shared with anything that needs to peek."""

    def __init__(self):
        self.ap = None  # dict(ssid, password, channel, ip) when up
        self.gpio = {}  # pin -> 0/1
        self.siggen = None  # dict(pin, freq, duty) when a PWM is running
        # A couple of fake neighbouring networks so wifi.scan returns something.
        self.visible_networks = [
            {"ssid": "office-2g", "rssi": -57},
            {"ssid": "iot-lab", "rssi": -71},
        ]


class SimSatelliteTransport:
    """A fake serial transport: parse a request line, queue a response line."""

    def __init__(self, state=None, capabilities=("wifi", "gpio", "siggen")):
        self.state = state or SimState()
        self.capabilities = list(capabilities)
        self._out = deque()  # queued response lines (str, no newline)

    # --- transport surface expected by Satellite ---------------------------
    def write(self, data: bytes):
        line = data.decode("utf-8").strip()
        if not line:
            return len(data)
        self._out.append(json.dumps(self._handle(line)))
        return len(data)

    def readline(self) -> bytes:
        if not self._out:
            return b""
        return (self._out.popleft() + "\n").encode("utf-8")

    # --- firmware emulation (mirrors satellite.ino) ------------------------
    def _handle(self, line):
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "error": "bad json"}
        cmd = req.get("cmd", "")
        s = self.state

        if cmd == "ping":
            return {"ok": True, "fw": FW}
        if cmd == "caps":
            return {"ok": True, "capabilities": list(self.capabilities)}
        if cmd == "wifi.ap_start":
            ssid = req.get("ssid", "")
            if not ssid:
                return {"ok": False, "error": "missing ssid"}
            s.ap = {
                "ssid": ssid,
                "password": req.get("password", ""),
                "channel": req.get("channel", 1),
                "ip": "192.168.4.1",
            }
            return {"ok": True, "ip": s.ap["ip"]}
        if cmd == "wifi.ap_stop":
            s.ap = None
            return {"ok": True}
        if cmd == "wifi.scan":
            return {"ok": True, "networks": list(s.visible_networks)}
        if cmd == "gpio.set":
            pin = req.get("pin", -1)
            if pin is None or pin < 0:
                return {"ok": False, "error": "missing pin"}
            s.gpio[pin] = 1 if req.get("value") else 0
            return {"ok": True}
        if cmd == "gpio.get":
            pin = req.get("pin", -1)
            if pin is None or pin < 0:
                return {"ok": False, "error": "missing pin"}
            return {"ok": True, "value": s.gpio.get(pin, 0)}
        if cmd == "siggen.start":
            pin = req.get("pin", -1)
            if pin is None or pin < 0:
                return {"ok": False, "error": "missing pin"}
            freq = req.get("freq", 1000)
            duty = max(0, min(100, req.get("duty", 50)))
            s.siggen = {"pin": pin, "freq": freq, "duty": duty}
            return {"ok": True, "freq": freq, "duty": duty}
        if cmd == "siggen.stop":
            s.siggen = None
            return {"ok": True}
        if cmd in ("ble.scan", "ble.write"):
            return {"ok": False, "error": "ble not built in this image"}
        return {"ok": False, "error": "unknown cmd: " + str(cmd)}


def make_sim_satellite(state=None, capabilities=("wifi", "gpio", "siggen")):
    """Convenience: a Satellite driver wired to a fresh simulator."""
    from satellite.host.satellite_driver import Satellite

    return Satellite(SimSatelliteTransport(state=state, capabilities=capabilities))


if __name__ == "__main__":
    # Tiny smoke test of the emulator over the real driver.
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from satellite.host.satellite_driver import Satellite

    st = SimState()
    sat = Satellite(SimSatelliteTransport(state=st))
    print("ping :", sat.ping())
    print("caps :", sat.caps())
    print("ap   :", sat.wifi_ap_start("TestAP", "password123"))
    print("scan :", sat.wifi_scan())
    print("gpioS:", sat.gpio_set(9, 0))
    print("gpioG:", sat.gpio_get(9))
    print("state.ap  =", st.ap)
    print("state.gpio=", st.gpio)
