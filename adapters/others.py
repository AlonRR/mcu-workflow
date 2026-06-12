#!/usr/bin/env python3
"""
Experimental adapters for STM32 / RP2040 / Zephyr (deliverable #12).

The command mappings are the known-good toolchain patterns, but these are
marked `supported = False` until built and tested on real hardware. They exist
to prove the abstraction: adding a platform is a new adapter, not a rewrite.
"""
from __future__ import annotations

from .base import PlatformAdapter


class Stm32Adapter(PlatformAdapter):
    name = "stm32"
    supported = False   # experimental: CMake + arm-none-eabi-gcc + OpenOCD

    def set_target_cmd(self, chip, path="."):
        # target is selected by the CMake/board config, not a CLI verb
        return ["cmake", "-S", path, "-B", path + "/build", "-DCHIP=" + chip]

    def build_cmd(self, path="."):
        return ["cmake", "--build", path + "/build"]

    def flash_cmd(self, path=".", port=None):
        return ["openocd", "-f", "interface/stlink.cfg", "-f", "target/stm32.cfg",
                "-c", "program build/firmware.elf verify reset exit"]

    def monitor_cmd(self, path=".", port=None):
        return ["python", "-m", "serial.tools.miniterm", port or "/dev/ttyACM0", "115200"]


class Rp2040Adapter(PlatformAdapter):
    name = "rp2040"
    supported = False   # experimental: Pico SDK (CMake) + picotool

    def set_target_cmd(self, chip, path="."):
        return ["cmake", "-S", path, "-B", path + "/build"]

    def build_cmd(self, path="."):
        return ["cmake", "--build", path + "/build"]

    def flash_cmd(self, path=".", port=None):
        return ["picotool", "load", "-x", "build/firmware.uf2"]

    def monitor_cmd(self, path=".", port=None):
        return ["python", "-m", "serial.tools.miniterm", port or "/dev/ttyACM0", "115200"]


class ZephyrAdapter(PlatformAdapter):
    name = "zephyr"
    supported = False   # experimental: west + Twister (HIL mirrors pytest-embedded)

    def set_target_cmd(self, chip, path="."):
        return ["west", "build", "-b", chip, path]

    def build_cmd(self, path="."):
        return ["west", "build", path]

    def flash_cmd(self, path=".", port=None):
        return ["west", "flash"]

    def monitor_cmd(self, path=".", port=None):
        return ["west", "espressif", "monitor"] if False else \
               ["python", "-m", "serial.tools.miniterm", port or "/dev/ttyACM0", "115200"]
