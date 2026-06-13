#!/usr/bin/env python3
"""ESP32 adapter - wraps idf.py / esptool / pytest-embedded. (deliverable #12)"""

from __future__ import annotations

import json
from pathlib import Path

from .base import PlatformAdapter


class Esp32Adapter(PlatformAdapter):
    name = "esp32"
    supported = True
    cage_image = "espressif/idf:release-v6.0"  # headless ESP-IDF toolchain
    toolchain_tools = ("idf.py", "esptool")

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

    def cage_build_cmd(self, project_dir, chip, image):
        # set-target (first time) then build, inside the cage image. The image
        # entrypoint sources the ESP-IDF env, so idf.py is on PATH in the shell.
        proj = Path(project_dir).resolve()
        need_target = not (proj / "sdkconfig").exists()
        script = "idf.py set-target " + chip + " && idf.py build" if need_target else "idf.py build"
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            str(proj) + ":/work",
            "-w",
            "/work",
            image,
            "bash",
            "-c",
            script,
        ]

    def host_flash_cmd(self, project_dir, port, chip, python):
        # Flash already-built artifacts from the host with esptool over the COM
        # port (no usbipd needed for the C3's native USB-Serial/JTAG).
        build_dir = Path(project_dir) / "build"
        fa = build_dir / "flasher_args.json"
        if not fa.exists():
            raise FileNotFoundError(
                "flasher_args.json not in " + str(build_dir) + " - build the project first"
            )
        files = json.loads(fa.read_text(encoding="utf-8")).get("flash_files") or {}
        if not files:
            raise ValueError("no flash_files in flasher_args.json")
        pairs = []
        for off, rel in sorted(files.items(), key=lambda kv: int(kv[0], 16)):
            pairs += [off, str((build_dir / rel).resolve())]
        cmd = [python, "-m", "esptool", "--chip", chip]
        if port:
            cmd += ["-p", port]
        return cmd + ["--before", "default_reset", "--after", "hard_reset", "write_flash"] + pairs
