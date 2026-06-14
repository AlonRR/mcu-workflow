"""Unit regression for the RFC2217 serial bridge (src/serialbridge)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_serialbridge_test", ROOT / "src" / "serialbridge" / "serialbridge.py"
)
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)


def test_build_cmd():
    assert sb.build_cmd("COM6", 4000, python="py") == [
        "py",
        "-m",
        "esp_rfc2217_server",
        "-p",
        "4000",
        "COM6",
    ]


def test_build_cmd_posix_device_and_default_python():
    cmd = sb.build_cmd("/dev/ttyACM0", 2217, python="/usr/bin/python3")
    assert cmd[-1] == "/dev/ttyACM0" and "2217" in cmd and cmd[0] == "/usr/bin/python3"
