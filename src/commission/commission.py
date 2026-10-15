#!/usr/bin/env python3
"""
commission.py - assert the bench matches board.yml before any test runs.

`doctor` checks the toolchain and that a port answers; this checks that the
*bench* is the one board.yml describes, so that a later test failure means the
code (docs/architecture.md section 13). Every check has an outcome the host can
observe that differs between "bench right" and "bench wrong":

  dut_port      the DUT's port is connected
  dut_chip      esptool's chip type matches meta.chip
  dut_flash     esptool's detected flash size covers build.sdkconfig's
  satellite     a satellite answers, is not the DUT, and has the capabilities
                test.needs and the rig lines call for
  boot_line     the satellite holds rig.dut_boot_gpio low and the DUT's ROM
                reports DOWNLOAD at reset; released, it reports a flash boot.
                A DUT the control reset leaves in the loader is recovered
                with esptool's hard reset, never left there silently
  reset_line    the satellite holds rig.dut_reset_gpio low and the DUT's USB
                port disappears; released, it comes back
  pins_devices  pins:/devices: need code on the DUT to probe - reported as
                "unverified", never as passed

Each check is pass | fail | skip (not applicable to this board) | unverified
(applicable but not checked). The gate passes when nothing fails.

The checks talk to a *bench* object, so the same code runs against real
hardware (SerialBench, below) and the simulator (sim/bench.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# test.needs items that only the satellite provides (the DUT's own serial and
# the workbench's MQTT/OTA/UDP-log don't need one).
SAT_RADIO_NEEDS = ("wifi", "ble")

# esptool v5 prints "Chip type:   ESP32-C3 (...)", v4 printed "Chip is ESP32-C3 (...)".
_CHIP_RE = re.compile(r"^(?:Chip type:\s+|Chip is )(.+?)\s*$", re.M)
_FLASH_RE = re.compile(r"^Detected flash size:\s*(\S+)", re.M)
# The ROM's first line after a reset names the boot mode it sampled from the
# strapping pins, e.g. "rst:0x15 (USB_UART_CHIP_RESET),boot:0xf (SPI_FAST_FLASH_BOOT)"
# (captured on a C3, 15 Oct 2026). The hex differs by chip, so match the name.
_BOOT_RE = re.compile(r"boot:0x[0-9a-fA-F]+\s*\(([A-Z_]+)")
_SDK_FLASH_RE = re.compile(r"^CONFIG_ESPTOOLPY_FLASHSIZE_(\d+)MB$")


def parse_identity(text):
    """esptool flash_id output -> {"chip": str|None, "flash": "4MB"|None}."""
    chip = _CHIP_RE.search(text or "")
    flash = _FLASH_RE.search(text or "")
    return {
        "chip": chip.group(1) if chip else None,
        "flash": flash.group(1) if flash else None,
    }


def chip_slug(s):
    """'ESP32-C3 (QFN32) (revision v0.4)' or 'esp32c3' -> 'esp32c3'."""
    first = (s or "").strip().split()[0] if (s or "").strip() else ""
    return re.sub(r"[^a-z0-9]", "", first.lower())


def boot_mode(lines):
    """The boot mode of the last ROM boot line: 'download', 'flash', or None."""
    mode = None
    for ln in lines or []:
        m = _BOOT_RE.search(ln)
        if m:
            mode = "download" if m.group(1).startswith("DOWNLOAD") else "flash"
    return mode


def declared_flash(board):
    """The flash size build.sdkconfig selects ('4MB'), or None if it selects none."""
    sdk = (board.get("build") or {}).get("sdkconfig") or {}
    for key, val in sdk.items():
        m = _SDK_FLASH_RE.match(str(key))
        if m and str(val).lower() in ("y", "yes", "true", "1"):
            return m.group(1) + "MB"
    return None


def _mb(size):
    m = re.match(r"(\d+)\s*MB", str(size or ""), re.I)
    return int(m.group(1)) if m else None


def _result(check, status, detail):
    return {"check": check, "status": status, "detail": detail}


def _wait_until(pred, timeout, poll):
    """True as soon as pred() holds; checked at least once, then until timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if pred():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


# --- the checks ------------------------------------------------------------


def _check_dut_port(bench):
    if not bench.dut_port:
        return _result("dut_port", "fail", "no DUT port given")
    present = bench.ports()
    if bench.dut_port in present:
        return _result("dut_port", "pass", bench.dut_port + " is connected")
    return _result(
        "dut_port",
        "fail",
        bench.dut_port + " is not connected (ports: " + (", ".join(present) or "none") + ")",
    )


def _check_identity(board, bench):
    """dut_chip and dut_flash share one esptool read."""
    want_chip = (board.get("meta") or {}).get("chip")
    want_flash = declared_flash(board)
    try:
        text = bench.identify()
    except Exception as e:
        text = ""
        err = "esptool failed: " + str(e)
    else:
        err = None
    ident = parse_identity(text)
    last = next((ln for ln in reversed(text.splitlines()) if ln.strip()), "")
    why = err or ("esptool: " + last if last else "esptool printed nothing")

    if not want_chip:
        chip = _result("dut_chip", "skip", "meta.chip not declared")
    elif ident["chip"] is None:
        chip = _result("dut_chip", "fail", "no chip type read (" + why + ")")
    elif chip_slug(ident["chip"]) == chip_slug(want_chip):
        chip = _result("dut_chip", "pass", ident["chip"] + " matches meta.chip " + want_chip)
    else:
        chip = _result(
            "dut_chip", "fail", "DUT is " + ident["chip"] + ", board.yml says " + want_chip
        )

    if not want_flash:
        flash = _result("dut_flash", "skip", "build.sdkconfig selects no flash size")
    elif ident["flash"] is None:
        flash = _result("dut_flash", "fail", "no flash size read (" + why + ")")
    elif (_mb(ident["flash"]) or 0) >= (_mb(want_flash) or 0):
        flash = _result(
            "dut_flash",
            "pass",
            "detected " + ident["flash"] + ", build.sdkconfig selects " + want_flash,
        )
    else:
        flash = _result(
            "dut_flash",
            "fail",
            "detected "
            + ident["flash"]
            + " but build.sdkconfig selects "
            + want_flash
            + " - the image would not fit",
        )
    return [chip, flash]


def _needed_caps(board):
    needs = [str(n).strip().lower() for n in ((board.get("test") or {}).get("needs") or [])]
    rig = board.get("rig") or {}
    caps = [n for n in SAT_RADIO_NEEDS if n in needs]
    if "dut_boot_gpio" in rig or "dut_reset_gpio" in rig:
        caps.append("gpio")
    return caps


def _check_satellite(board, bench):
    """Returns (result, capabilities) - capabilities is None when unknown."""
    rig = board.get("rig") or {}
    needed = _needed_caps(board)
    required = rig.get("satellite") == "required" or bool(needed)
    if bench.sat is None:
        if not required:
            return (
                _result(
                    "satellite",
                    "skip",
                    "not needed (rig.satellite: "
                    + str(rig.get("satellite", "unset"))
                    + "; no wifi/ble in test.needs; no rig GPIO)",
                ),
                None,
            )
        why = getattr(bench, "sat_error", None) or (
            "none given - pass --satellite PORT or --workbench URL"
        )
        return (
            _result(
                "satellite",
                "fail",
                "board.yml needs one (" + (", ".join(needed) or "rig.satellite: required") + "); "
                "no satellite: " + why,
            ),
            None,
        )
    if bench.sat_port and bench.sat_port == bench.dut_port:
        return (
            _result("satellite", "fail", "satellite and DUT are the same port " + bench.dut_port),
            None,
        )
    r = bench.sat.caps()
    if not r.get("ok"):
        return _result("satellite", "fail", "caps failed: " + json.dumps(r)), None
    have = [str(c) for c in (r.get("capabilities") or [])]
    missing = [c for c in needed if c not in have]
    if missing:
        return (
            _result(
                "satellite",
                "fail",
                "satellite lacks " + ", ".join(missing) + " (it has: " + ", ".join(have) + ")",
            ),
            have,
        )
    return (
        _result(
            "satellite",
            "pass",
            "capabilities " + ", ".join(have) + ("; covers " + ", ".join(needed) if needed else ""),
        ),
        have,
    )


def _line_precondition(name, key, board, caps, dut_ok):
    """A rig-line check's skip/unverified result, or None when it can run."""
    rig = board.get("rig") or {}
    if key not in rig:
        return _result(name, "skip", "rig." + key + " not declared")
    if not dut_ok:
        return _result(name, "unverified", "not run: the DUT port is not connected")
    if caps is None:
        return _result(name, "unverified", "not run: no working satellite to drive it")
    if "gpio" not in caps:
        return _result(name, "unverified", "not run: the satellite has no gpio capability")
    return None


def _release(bench, pin, errors):
    # gpio.get resets the satellite pin to an input: the line floats back to the
    # DUT's pull-up instead of being driven (no fight with the BOOT button).
    try:
        r = bench.sat.gpio_get(pin)
        if not r.get("ok"):
            errors.append("release failed: " + json.dumps(r))
    except Exception as e:
        errors.append("release failed: " + str(e))


def _check_boot_line(board, bench):
    pin = board["rig"]["dut_boot_gpio"]
    held = released = None
    errors = []
    try:
        r = bench.sat.gpio_set(pin, 0)
        if r.get("ok"):
            held = boot_mode(bench.reset_capture())
        else:
            errors.append("gpio.set failed: " + json.dumps(r))
    except Exception as e:
        errors.append("held low: " + str(e))
    finally:
        _release(bench, pin, errors)
        # The control reading, and the reset that puts the DUT back in its app.
        try:
            released = boot_mode(bench.reset_capture())
        except Exception as e:
            errors.append("released: " + str(e))

    seen = "held low -> " + str(held) + ", released -> " + str(released)
    if released != "flash":
        # The control reset should have put the DUT back in its app. From the ROM
        # loader a USB RTS pulse can print nothing and leave the chip there
        # (measured on a C3, 15 Oct 2026), while esptool's hard reset frees it -
        # so recover, then read the control again. (Pulsing EN through
        # rig.dut_reset_gpio would also work, independent of USB.)
        try:
            bench.recover()
            released = boot_mode(bench.reset_capture())
        except Exception as e:
            errors.append("recovery: " + str(e))
        seen += ", after an esptool hard reset -> " + str(released)
    stuck = (
        ""
        if released == "flash"
        else " The DUT may still be in download mode: recover it with "
        "esptool --port " + str(bench.dut_port) + " --before no_reset --after hard_reset chip_id"
    )
    if errors:
        return _result("boot_line", "fail", seen + "; " + "; ".join(errors) + "." + stuck)
    if held is None or released is None:
        return _result(
            "boot_line",
            "fail",
            seen + ": no ROM boot line captured, so the wire is unproven." + stuck,
        )
    if released == "download":
        return _result(
            "boot_line",
            "fail",
            seen + ": the DUT enters download mode even with the line released "
            "(strap stuck low or BOOT held)." + stuck,
        )
    if held == "flash":
        return _result(
            "boot_line",
            "fail",
            seen
            + ": no effect - satellite GPIO "
            + str(pin)
            + " does not reach the DUT's BOOT strap (check the wire and common GND)",
        )
    return _result(
        "boot_line",
        "pass",
        seen + ": satellite GPIO " + str(pin) + " drives the DUT's BOOT strap",
    )


def _check_reset_line(board, bench):
    pin = board["rig"]["dut_reset_gpio"]
    port = bench.dut_port
    errors = []
    gone = False
    try:
        r = bench.sat.gpio_set(pin, 0)
        if r.get("ok"):
            gone = _wait_until(lambda: port not in bench.ports(), bench.hold_s, bench.poll_s)
        else:
            errors.append("gpio.set failed: " + json.dumps(r))
    except Exception as e:
        errors.append("held low: " + str(e))
    finally:
        _release(bench, pin, errors)
    back = _wait_until(lambda: port in bench.ports(), bench.return_s, bench.poll_s)

    if errors:
        return _result("reset_line", "fail", "; ".join(errors))
    if not gone:
        return _result(
            "reset_line",
            "fail",
            port
            + " stayed connected while satellite GPIO "
            + str(pin)
            + " was held low - the line does not reach the DUT's EN",
        )
    if not back:
        return _result(
            "reset_line",
            "fail",
            port + " dropped while EN was held low but did not come back after release",
        )
    return _result(
        "reset_line",
        "pass",
        port + " dropped while satellite GPIO " + str(pin) + " held EN low, and returned",
    )


def _check_pins_devices(board):
    pins = list((board.get("pins") or {}).keys())
    devices = list((board.get("devices") or {}).keys())
    if not pins and not devices:
        return _result("pins_devices", "skip", "no pins: or devices: declared")
    listed = []
    if pins:
        listed.append("pins: " + ", ".join(pins))
    if devices:
        listed.append("devices: " + ", ".join(devices))
    return _result(
        "pins_devices",
        "unverified",
        "; ".join(listed) + " - probing these needs code on the DUT (not built yet)",
    )


def commission(board, bench):
    """Run every check against `bench`; return the structured report."""
    checks = []
    port = _check_dut_port(bench)
    checks.append(port)
    dut_ok = port["status"] == "pass"
    if dut_ok:
        checks += _check_identity(board, bench)
    else:
        for name in ("dut_chip", "dut_flash"):
            checks.append(_result(name, "unverified", "not run: the DUT port is not connected"))

    sat, caps = _check_satellite(board, bench)
    checks.append(sat)

    for name, key, fn in (
        ("boot_line", "dut_boot_gpio", _check_boot_line),
        ("reset_line", "dut_reset_gpio", _check_reset_line),
    ):
        pre = _line_precondition(name, key, board, caps, dut_ok)
        checks.append(pre if pre is not None else fn(board, bench))

    checks.append(_check_pins_devices(board))

    counts = {s: sum(1 for c in checks if c["status"] == s) for s in _STATUSES}
    return {
        "ok": counts["fail"] == 0,
        "total": len(checks),
        "counts": counts,
        "checks": checks,
    }


_STATUSES = ("pass", "fail", "skip", "unverified")


# --- the real bench ----------------------------------------------------------


class WorkbenchSatellite:
    """The satellite behind a running workbench (`mcuflow workbench`), with the
    driver's caps/gpio_set/gpio_get surface. Use it when the workbench already
    holds the satellite's serial port."""

    def __init__(self, base):
        self.base = base.rstrip("/")

    def _http(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method="POST" if body is not None else "GET"
        )
        token = os.environ.get("WORKBENCH_TOKEN")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return {"ok": False, "error": "HTTP " + str(e.code) + " on " + path}
        except (urllib.error.URLError, OSError) as e:
            return {"ok": False, "error": "workbench unreachable: " + str(getattr(e, "reason", e))}

    def caps(self):
        return self._http("/api/satellite/caps")

    def gpio_set(self, pin, value):
        return self._http("/api/gpio/set", {"pin": pin, "value": value})

    def gpio_get(self, pin):
        return self._http("/api/gpio/get", {"pin": pin})


class SerialBench:
    """The bench on this host: the DUT on a USB serial port, esptool for its
    identity, and a satellite (driver or WorkbenchSatellite) for the rig lines."""

    hold_s = 2.0  # how long EN is held low waiting for the DUT's USB to drop
    return_s = 10.0  # how long to wait for it to re-enumerate after release
    poll_s = 0.25
    capture_s = 3.0  # ROM banner capture window after a reset

    def __init__(self, dut_port, sat=None, sat_port=None, sat_error=None, python=None):
        self.dut_port = dut_port
        self.sat = sat
        self.sat_port = sat_port
        self.sat_error = sat_error
        self.python = python or sys.executable

    def ports(self):
        from serial.tools import list_ports

        return [p.device for p in list_ports.comports()]

    def identify(self):
        # Default reset into the ROM loader, read, then hard-reset back to the app.
        cmd = [self.python, "-m", "esptool", "--port", self.dut_port]
        cmd += ["--before", "default_reset", "--after", "hard_reset", "flash_id"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return (proc.stdout or "") + (proc.stderr or "")

    def recover(self):
        """Get the DUT out of the ROM loader into its app: esptool connects without
        resetting (it is already in the loader) and hard-resets on the way out."""
        cmd = [self.python, "-m", "esptool", "--port", self.dut_port]
        cmd += ["--before", "no_reset", "--after", "hard_reset", "chip_id"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (proc.stdout or "") + (proc.stderr or "")

    def reset_capture(self):
        """Reset the DUT over its USB-Serial/JTAG (DTR low leaves the BOOT strap
        alone, an RTS pulse is EN) and return what it prints. The strap is then
        whatever the wire holds it at - which is the point."""
        import serial

        deadline = time.monotonic() + 10.0
        while True:  # the C3's native USB can be mid re-enumeration
            try:
                ser = serial.serial_for_url(self.dut_port, baudrate=115200, timeout=0.2)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        try:
            ser.dtr = False
            ser.rts = True
            time.sleep(0.2)  # esptool's hold for USB-JTAG chips
            ser.rts = False
            buf = b""
            end = time.monotonic() + self.capture_s
            while time.monotonic() < end:
                buf += ser.read(512)
        finally:
            ser.close()
        return buf.decode("utf-8", "replace").splitlines()
