#!/usr/bin/env python3
"""
hil.py - the workbench-mediated HIL run, in simulation.

This is the "firmware that communicates" test the architecture promises, wired
end-to-end through the *real* interfaces:

    workbench HTTP API  ->  satellite driver  ->  (sim) satellite firmware
                                                        |
                                  shared radio state    v
    SimDUT  <-------------------------------------  WiFi AP is up

Steps:
  1. boot the DUT, assert the boot string (the test_boots gate)
  2. raise an AP on the satellite *through the workbench HTTP API*
  3. assert the DUT joins it (the wifi provisioning gate)
  4. pulse the DUT BOOT gpio through the workbench (recovery/stimulus demo)

Run on real hardware by pointing the workbench at a real satellite port and
flashing a real DUT - the assertions are identical.
"""

from __future__ import annotations

import json
import os as _os
import sys as _sys
import threading
import time
import urllib.error
import urllib.request

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from sim.dut import SimDUT


class SerialDUT:
    """Real DUT over its serial console - same interface SimDUT exposes (boot /
    expect / provision / serial_log), so run_hil asserts against actual silicon
    when a dut_port is given. A background thread accumulates every line; opening
    the port resets the C3, so 'app_main started' is reprinted on connect."""

    def __init__(
        self, board, port, target_ssid="mcuflow-test", target_password="password123", baud=115200
    ):
        import serial  # pyserial

        self.boot_string = (board.get("test") or {}).get("boot_string") or "app_main started"
        self.target_ssid = target_ssid
        self.serial_log = []
        self._buf = ""
        self._lock = threading.Lock()
        self._stop = False
        # Opening the USB-Serial/JTAG port resets the board -> fresh boot output.
        # The C3's native USB re-enumerates around a flash, so the port can be
        # briefly unavailable; retry opening for a few seconds.
        deadline = time.monotonic() + 10.0
        while True:
            try:
                self._ser = serial.serial_for_url(port, baudrate=baud, timeout=0.3)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        # The reader is now listening; reset the chip into the app so the boot
        # banner ("app_main started") is emitted while we're capturing. On the
        # C3's USB-Serial/JTAG, RTS->EN (reset) with DTR->GPIO9 high = normal boot
        # (DTR low would drop it into download mode).
        self._reset_into_app()

    def _reset_into_app(self):
        try:
            self._ser.dtr = False  # GPIO9 high -> boot the app, not the loader
            self._ser.rts = True  # EN low  -> hold in reset
            time.sleep(0.1)
            self._ser.rts = False  # EN high -> release -> chip boots
        except Exception:
            pass

    def _reader(self):
        while not self._stop:
            try:
                chunk = self._ser.read(256)
            except Exception:
                break
            if not chunk:
                continue
            text = chunk.decode("utf-8", "replace")
            with self._lock:
                self._buf += text
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    self.serial_log.append(line.rstrip("\r"))

    def _seen(self, substr):
        with self._lock:
            return any(substr in ln for ln in self.serial_log)

    def _wait_for(self, substr, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._seen(substr):
                return True
            time.sleep(0.2)
        return False

    # --- SimDUT-compatible surface ---
    def boot(self, timeout=12.0):
        self._wait_for(self.boot_string, timeout)
        with self._lock:
            return list(self.serial_log)

    def expect(self, substr):
        return self._seen(substr)

    def provision(self, ap, timeout=30.0):
        # The DUT retries esp_wifi_connect() until the AP is up, then logs
        # "wifi: connected to '<ssid>', got ip ...". That line is the real join.
        target = "wifi: connected to '" + ap.get("ssid", self.target_ssid) + "'"
        if self._wait_for(target, timeout):
            line = next((ln for ln in self.serial_log if target in ln), target)
            return True, "DUT serial: " + line.strip()
        return False, ("no '" + target + "' on DUT serial within " + str(int(timeout)) + "s")

    def close(self):
        self._stop = True
        try:
            self._ser.close()
        except Exception:
            pass


def _load_board(path):
    import yaml

    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _http(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    method = "POST" if body is not None else "GET"
    req = urllib.request.Request(base + path, data=data, method=method)
    # A token-protected workbench (--token / WORKBENCH_TOKEN) accepts the same
    # secret from the environment here - no extra CLI plumbing needed.
    token = _os.environ.get("WORKBENCH_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Non-2xx replies (e.g. 503 "no satellite backend") still carry the
        # JSON error envelope; return it as a normal failed result so the run
        # produces its structured report instead of crashing mid-scenario.
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": "HTTP " + str(e.code) + " on " + path}
    except (urllib.error.URLError, OSError) as e:
        # No HTTP response at all (workbench unreachable, connection refused,
        # DNS failure, read timeout) - same contract as the HTTPError branch:
        # a failed result, never a raised exception, so run_hil always gets to
        # produce its structured per-step report.
        reason = getattr(e, "reason", e)
        return {"ok": False, "error": "workbench unreachable: " + str(reason)}


def run_hil(
    board_path,
    satellite="sim",
    workbench_base=None,
    ssid="mcuflow-test",
    password="password123",
    boot_gpio=None,
    dut_port=None,
):
    """Run the HIL scenario. Returns a structured report dict.

    satellite='sim' spins up an in-process workbench with the emulator.
    Pass workbench_base='http://host:port' to test against a running workbench
    (e.g. a real one with a real satellite).
    Pass dut_port='COMx'/'/dev/ttyACMx' to assert against a *real* DUT over its
    serial console instead of the modelled SimDUT (fully on-silicon HIL).
    """
    board = _load_board(board_path)
    if boot_gpio is None:
        boot_gpio = (board.get("rig") or {}).get("dut_boot_gpio")
    # Only assert what the board contract asks for: a serial-only project has
    # no wifi in test.needs, so the AP/join steps are skipped, not failed.
    # board_path is loaded straight from yaml here (no schema check), so
    # normalize case rather than requiring the exact casing `mcuflow validate`
    # would enforce.
    needs = [str(n).strip().lower() for n in ((board.get("test") or {}).get("needs") or [])]
    wifi_wanted = "wifi" in needs
    steps = []
    srv = None
    dut = None
    own_server = workbench_base is None

    def record(name, ok, detail):
        steps.append({"step": name, "ok": bool(ok), "detail": detail})

    if own_server:
        # Spin up a workbench bound to a sim satellite, in-process.
        import importlib.util
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "wb", os.path.join(root, "workbench", "workbench.py")
        )
        wb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wb)
        workbench_base, srv = wb.serve_inprocess(satellite)

    try:
        # Precondition: when the board needs wifi, the workbench must advertise
        # it (a satellite is present). Otherwise reachability alone is enough.
        caps = _http(workbench_base, "/api/capabilities").get("capabilities", {})
        record(
            "workbench_ready",
            caps.get("wifi", False) if wifi_wanted else True,
            "capabilities: " + ",".join(k for k, v in caps.items() if v),
        )

        real = dut_port is not None
        if real:
            dut = SerialDUT(board, dut_port, target_ssid=ssid, target_password=password)
        else:
            dut = SimDUT(board, target_ssid=ssid, target_password=password)

        # 1. boot gate
        dut.boot()
        boot_ok = dut.expect(dut.boot_string)
        record(
            "test_boots",
            boot_ok,
            ("DUT " + str(dut_port) + ": " if real else "")
            + "expected '"
            + dut.boot_string
            + "' -> "
            + ("found" if boot_ok else "MISSING"),
        )

        if wifi_wanted:
            # 2. raise the AP through the workbench HTTP API
            r = _http(workbench_base, "/api/wifi/ap_start", {"ssid": ssid, "password": password})
            record("ap_start", r.get("ok"), "satellite AP -> " + json.dumps(r))

            # 3. DUT joins (only meaningful if the AP actually came up).
            if r.get("ok"):
                # Read back the AP the satellite is actually broadcasting.
                ap = {"ssid": ssid, "password": password, "ip": r.get("ip", "192.168.4.1")}
                joined, why = dut.provision(ap)
                record("test_wifi_provision", joined, why)
            else:
                record("test_wifi_provision", False, "skipped: satellite AP failed to start")

        # 4. stimulus: pulse the DUT BOOT gpio via the workbench
        if boot_gpio is not None:
            a = _http(workbench_base, "/api/gpio/set", {"pin": boot_gpio, "value": 0})
            b = _http(workbench_base, "/api/gpio/set", {"pin": boot_gpio, "value": 1})
            record(
                "gpio_stimulus", a.get("ok") and b.get("ok"), "toggled BOOT gpio " + str(boot_gpio)
            )
    finally:
        # Teardown runs even when a step blew up mid-scenario, and is attempted
        # whenever wifi was wanted at all - not gated on a successfully-parsed
        # ap_start reply, since the satellite can raise the AP and then have
        # the *response* to that call get lost (timeout/dropped connection);
        # in that race a "did it start" flag would still say no and skip
        # teardown, leaking the test AP into every later run on the rig.
        # ap_stop on a satellite with no AP running is a harmless no-op.
        if wifi_wanted:
            try:
                _http(workbench_base, "/api/wifi/ap_stop", {})
            except Exception:
                pass
        if dut is not None and hasattr(dut, "close"):
            dut.close()  # release the real DUT serial port
        if srv is not None:
            srv.shutdown()

    passed = sum(1 for s in steps if s["ok"])
    return {
        "ok": all(s["ok"] for s in steps),
        "passed": passed,
        "total": len(steps),
        "satellite": satellite,
        "steps": steps,
        "serial_log": list(dut.serial_log) if dut is not None else [],
    }


if __name__ == "__main__":
    import argparse
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser(description="Run the simulated workbench HIL scenario.")
    ap.add_argument("board")
    ap.add_argument("--satellite", default="sim")
    ap.add_argument("--workbench", default=None, help="base URL of a running workbench")
    args = ap.parse_args()
    rep = run_hil(args.board, satellite=args.satellite, workbench_base=args.workbench)
    print(json.dumps(rep, indent=2))
    raise SystemExit(0 if rep["ok"] else 1)
