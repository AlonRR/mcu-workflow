#!/usr/bin/env python3
"""
dut.py - a behavioural simulator of the *device under test* firmware.

It models what the scaffolded firmware is meant to do on a real C3: print the
boot string on start-up, and (for a wifi project) join an access point the
satellite raises. It reads the same board.yml the rest of the workflow uses, so
the simulated behaviour tracks the contract. This is a stand-in for real silicon
- clearly labelled as such - so the end-to-end interface can be exercised with
zero hardware; on a real board the identical test assertions run against the
chip's actual serial output instead.
"""
from __future__ import annotations


class SimDUT:
    def __init__(self, board, target_ssid=None, target_password=None):
        self.meta = board.get("meta", {})
        self.test = board.get("test", {})
        self.boot_string = self.test.get("boot_string", "app_main started")
        self.needs = self.test.get("needs", []) or []
        # Credentials the DUT firmware is provisioned to look for.
        self.target_ssid = target_ssid
        self.target_password = target_password
        self.joined = None
        self.serial_log = []

    def boot(self):
        """Emulate the chip booting and emitting its first log lines."""
        self.serial_log = [
            "rst:0x1 (POWERON),boot:0x9",
            "I (312) cpu_start: Pro cpu start user code",
            "I (320) " + self.meta.get("project", "app") + ": " + self.boot_string,
        ]
        return list(self.serial_log)

    def expect(self, needle):
        """Mirror pytest-embedded's dut.expect(): is needle in the boot output?"""
        return any(needle in line for line in self.serial_log)

    def provision(self, ap):
        """Try to join the AP dict the satellite is broadcasting (or None)."""
        if "wifi" not in self.needs:
            return False, "DUT does not request wifi"
        if not ap:
            return False, "no AP is up"
        if self.target_ssid and ap.get("ssid") != self.target_ssid:
            return False, "AP ssid mismatch"
        if self.target_password is not None and ap.get("password", "") != self.target_password:
            return False, "wrong password"
        self.joined = ap.get("ssid")
        self.serial_log.append(
            "I (1500) wifi: connected to '" + self.joined + "', got ip " + ap.get("ip", "0.0.0.0"))
        return True, "joined " + self.joined
