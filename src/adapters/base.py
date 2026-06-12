#!/usr/bin/env python3
"""
Platform adapter interface (deliverable #12).

A `PlatformAdapter` maps the workflow's verbs to a specific toolchain. Each
method RETURNS the command argv (it does not execute) so the deterministic
conductor (`mcuflow`) runs it and the mapping stays testable. This is the hinge
that keeps ESP32 specifics behind an adapter so STM32 / RP2040 / Zephyr slot in
beside it (ARCHITECTURE.md "Extensibility beyond ESP32").
"""

from __future__ import annotations


class PlatformAdapter:
    name = "base"
    supported = False  # True once the adapter is real and tested

    def set_target_cmd(self, chip, path="."):
        raise NotImplementedError

    def build_cmd(self, path="."):
        raise NotImplementedError

    def flash_cmd(self, path=".", port=None):
        raise NotImplementedError

    def monitor_cmd(self, path=".", port=None):
        raise NotImplementedError

    def test_cmd(self, pyfile, target=None):
        # pytest-embedded is not ESP-exclusive, so the test verb is shared.
        cmd = ["pytest"]
        if target:
            cmd += ["--target", target]
        return cmd + [str(pyfile)]
