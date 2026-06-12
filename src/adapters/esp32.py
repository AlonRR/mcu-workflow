#!/usr/bin/env python3
"""ESP32 adapter - wraps idf.py / esptool / pytest-embedded. (deliverable #12)"""

from __future__ import annotations

from .base import PlatformAdapter


class Esp32Adapter(PlatformAdapter):
    name = "esp32"
    supported = True

    def set_target_cmd(self, chip, path="."):
        return ["idf.py", "-C", path, "set-target", chip]

    def build_cmd(self, path="."):
        return ["idf.py", "-C", path, "build"]

    def flash_cmd(self, path=".", port=None):
        cmd = ["idf.py", "-C", path]
        if port:
            cmd += ["-p", port]
        return cmd + ["flash"]

    def monitor_cmd(self, path=".", port=None):
        cmd = ["idf.py", "-C", path]
        if port:
            cmd += ["-p", port]
        return cmd + ["monitor"]
