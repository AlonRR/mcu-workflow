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

import os as _os
import re
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
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
        dut_port="SIM-DUT",
        sat_port="SIM-SAT",
    ):
        rig = board.get("rig") or {}
        meta = board.get("meta") or {}
        # The satellite GPIO physically wired to each DUT line (None = no wire).
        self.boot_wire = rig.get("dut_boot_gpio") if boot_wire is _AS_DECLARED else boot_wire
        self.reset_wire = rig.get("dut_reset_gpio") if reset_wire is _AS_DECLARED else reset_wire
        self.boot_stuck_low = boot_stuck_low
        # False models the C3 measured 15 Oct 2026: once in the ROM loader, a USB
        # RTS reset printed nothing and left it there; only esptool's hard reset
        # (recover) brought it back.
        self.usb_reset_frees_loader = usb_reset_frees_loader
        self.rom_silent = rom_silent  # every reset prints nothing readable
        self.recoveries = 0
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

    def reset_capture(self):
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
