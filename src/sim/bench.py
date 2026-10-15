#!/usr/bin/env python3
"""
bench.py - a simulated two-board bench for `mcuflow commission`.

It exposes the same surface as commission.SerialBench (ports / identify /
reset_capture, plus a satellite driver) and models the physics the checks
observe on real hardware:

  - the ROM boot line follows the DUT's BOOT strap at reset: low -> DOWNLOAD,
    high or floating (pull-up) -> SPI_FAST_FLASH_BOOT;
  - the DUT's USB port disappears while its EN is held low.

What is wired where is a constructor argument, so a test can build the bench
board.yml describes (the default) or a mis-wired one, and check that commission
tells them apart. The satellite is the real driver over the satellite emulator.
"""

from __future__ import annotations

import json
import os as _os
import re
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from commission.probe_fw import MARK, PROBE_FW, probe_plan, safe_name
from satellite.host.satellite_driver import Satellite
from satellite.host.sim import SimSatelliteTransport, SimState

_AS_DECLARED = object()


def _chip_description(chip):
    """'esp32c3' -> 'ESP32-C3 (QFN32) (revision v0.4)', in esptool's own shape."""
    m = re.match(r"esp32(\w*)", str(chip or "esp32c3").lower())
    suffix = m.group(1).upper() if m else ""
    return "ESP32" + ("-" + suffix if suffix else "") + " (QFN32) (revision v0.4)"


class SimBench:
    hold_s = 0.0  # the simulated line acts instantly, so no waiting
    return_s = 0.0
    poll_s = 0.0

    def __init__(
        self,
        board,
        chip=None,
        flash=None,
        caps=("wifi", "gpio", "siggen", "ble"),
        satellite=True,
        boot_wire=_AS_DECLARED,
        reset_wire=_AS_DECLARED,
        boot_stuck_low=False,
        usb_reset_frees_loader=True,
        rom_silent=False,
        dut_present=True,
        probe=False,
        i2c_present=None,
        probe_hangs=False,
        dut_port="SIM-DUT",
        sat_port="SIM-SAT",
    ):
        rig = board.get("rig") or {}
        meta = board.get("meta") or {}
        # The satellite GPIO physically wired to each DUT line (None = no wire).
        self.boot_wire = rig.get("dut_boot_gpio") if boot_wire is _AS_DECLARED else boot_wire
        self.reset_wire = rig.get("dut_reset_gpio") if reset_wire is _AS_DECLARED else reset_wire
        self.boot_stuck_low = boot_stuck_low
        # False models what was seen on a C3 on 15 Oct 2026: in the loader (with
        # the esptool stub running), a USB RTS reset printed nothing and left it
        # there; only esptool's hard reset (recover) brought it back.
        self.usb_reset_frees_loader = usb_reset_frees_loader
        self.rom_silent = rom_silent  # every reset prints nothing readable
        self.recoveries = 0
        # The probe image (commission --probe): which I2C addresses answer on
        # each bus ({bus: [addr]}); None = every device board.yml declares.
        self.probe_enabled = probe
        self.i2c_present = i2c_present
        self.probe_hangs = probe_hangs
        self.probe_runs = 0
        self.dut_present = dut_present
        self.chip = chip or _chip_description(meta.get("chip"))
        self.flash = flash or _declared_flash(board) or "4MB"
        self.dut_port = dut_port
        self.state = SimState()
        self.sat = Satellite(SimSatelliteTransport(self.state, caps)) if satellite else None
        self.sat_port = sat_port if satellite else None
        self.sat_error = None
        self.mode = None  # what the DUT last booted into: 'flash' | 'download'

    def _driven_low(self, pin):
        s = self.state
        return pin is not None and pin in s.gpio and pin not in s.inputs and s.gpio[pin] == 0

    def ports(self):
        out = []
        if self.dut_present and not self._driven_low(self.reset_wire):
            out.append(self.dut_port)
        if self.sat_port:
            out.append(self.sat_port)
        return out

    def identify(self):
        return (
            "esptool v5.3.1\n"
            "Chip type:          " + self.chip + "\n"
            "Detected flash size: " + self.flash + "\n"
            "Hard resetting via RTS pin...\n"
        )

    def recover(self):
        self.recoveries += 1
        low = self.boot_stuck_low or self._driven_low(self.boot_wire)
        self.mode = "download" if low else "flash"
        return "Hard resetting via RTS pin...\n"

    def run_probe(self, board):
        """Emulate the probe image's console output (probe_fw.py) on this bench."""
        self.probe_runs += 1
        plan = probe_plan(board)
        present = self.i2c_present
        if present is None:
            present = {b["bus"]: [d["addr"] for d in b["devices"]] for b in plan["i2c"]}
        project = safe_name((board.get("meta") or {}).get("project", "project"))

        def line(obj):
            return MARK + json.dumps(obj, separators=(",", ":"))

        out = [
            "ESP-ROM:esp32c3-api1-20210207",
            line({"kind": "start", "fw": PROBE_FW, "project": project}),
        ]
        for b in plan["i2c"]:
            bus = safe_name(b["bus"])
            found = sorted(present.get(b["bus"], []))
            idle = 1 if found else 0  # a breakout brings the pull-ups
            out.append(
                line(
                    {
                        "kind": "i2c_bus",
                        "bus": bus,
                        "sda_idle": idle,
                        "scl_idle": idle,
                        "error": None,
                    }
                )
            )
            for d in b["devices"]:
                result = "ack" if d["addr"] in found else "ESP_ERR_NOT_FOUND"
                out.append(
                    line(
                        {
                            "kind": "i2c_device",
                            "bus": bus,
                            "device": safe_name(d["name"]),
                            "addr": d["addr"],
                            "result": result,
                        }
                    )
                )
            out.append(line({"kind": "i2c_scan", "bus": bus, "found": found}))
        out.append(line({"kind": "done"}))
        return out[:3] if self.probe_hangs else out

    def reset_capture(self, seconds=None, until=None):
        if self.mode == "download" and not self.usb_reset_frees_loader:
            return []
        low = self.boot_stuck_low or self._driven_low(self.boot_wire)
        self.mode = "download" if low else "flash"
        if self.rom_silent:
            return []
        boot = "boot:0x5 (DOWNLOAD(USB/UART0))" if low else "boot:0xf (SPI_FAST_FLASH_BOOT)"
        lines = ["ESP-ROM:esp32c3-api1-20210207", "rst:0x15 (USB_UART_CHIP_RESET)," + boot]
        lines.append("waiting for download" if low else "I (320) app: app_main started")
        return lines


def _declared_flash(board):
    sdk = (board.get("build") or {}).get("sdkconfig") or {}
    for key, val in sdk.items():
        m = re.match(r"^CONFIG_ESPTOOLPY_FLASHSIZE_(\d+)MB$", str(key))
        if m and str(val).lower() in ("y", "yes", "true", "1"):
            return m.group(1) + "MB"
    return None
