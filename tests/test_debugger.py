"""Unit regression for the OpenOCD debug launcher (src/debugger)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_debugger_test", ROOT / "src" / "debugger" / "debugger.py"
)
dbg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbg)


def test_build_cmd_for_builtin_jtag_chip():
    assert dbg.build_cmd("esp32c3") == ["openocd", "-f", "board/esp32c3-builtin.cfg"]


def test_build_cmd_custom_openocd_path():
    assert dbg.build_cmd("esp32s3", openocd="/x/openocd")[0] == "/x/openocd"


def test_build_cmd_unknown_chip_is_none():
    assert dbg.build_cmd("nrf52") is None


def test_build_cmd_board_override():
    assert dbg.build_cmd("nrf52", board="board/foo.cfg") == ["openocd", "-f", "board/foo.cfg"]
