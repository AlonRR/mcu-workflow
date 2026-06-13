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

    # The headless toolchain image and the host tools this platform needs. The
    # conductor pulls `cage_image` and `doctor` checks `toolchain_tools`, so a
    # platform owns its own toolchain/provisioning - the CLI stays generic.
    cage_image = None
    toolchain_tools = ()

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

    # --- no-native-toolchain fallbacks (also just return argv) -----------------
    def cage_build_cmd(self, project_dir, chip, image):
        """docker argv to build `project_dir` inside `image` (no host toolchain).
        Return None if this platform has no containerized build."""
        return None

    def host_flash_cmd(self, project_dir, port, chip, python):
        """argv to flash already-built artifacts from the host (no host
        toolchain). Return None if unsupported; raise if the project isn't built
        yet (the message is surfaced to the user)."""
        return None
