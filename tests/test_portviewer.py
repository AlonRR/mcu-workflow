"""Unit regression for the COM-port viewer (src/portviewer/portviewer.py).

Pure logic only - no window, no serial hardware - so it runs headless in CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_portviewer_test", ROOT / "src" / "portviewer" / "portviewer.py"
)
pv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pv)


def _port(dev, vid=None, serial=None, desc="", pid=None, mfg=""):
    return {
        "device": dev,
        "vid": vid,
        "pid": pid,
        "serial": serial,
        "description": desc,
        "manufacturer": mfg,
    }


C3_A = _port("COM3", vid=pv.ESPRESSIF_VID, serial="4830A1", desc="USB Serial Device")
C3_B = _port("COM7", vid=pv.ESPRESSIF_VID, serial="4830C2", desc="USB Serial Device")
BRIDGE = _port("COM5", vid=0x10C4, serial="0001", desc="Silicon Labs CP210x")
OTHER = _port("COM1", desc="Communications Port")


def test_classify_kinds():
    assert pv.classify(C3_A)[0] == "board"
    assert pv.classify(BRIDGE)[0] == "possible"
    assert pv.classify(OTHER)[0] == "other"


def test_has_relevant():
    assert pv.has_relevant([OTHER, C3_A]) is True
    assert pv.has_relevant([OTHER]) is False
    assert pv.has_relevant([OTHER, BRIDGE]) is True  # a bridge might be a board


def test_two_boards_assigned_by_serial_order():
    # order of input must not matter; assignment is by serial number
    mapping, reason = pv.suggest_roles([C3_B, C3_A, OTHER])
    assert mapping == {"COM3": "DUT", "COM7": "satellite"}
    assert "serial" in reason


def test_one_board_is_dut():
    mapping, reason = pv.suggest_roles([C3_A, OTHER])
    assert mapping == {"COM3": "DUT"}
    assert "one board" in reason


def test_no_board():
    mapping, reason = pv.suggest_roles([OTHER])
    assert mapping == {}
    assert "no ESP32" in reason


def test_roles_to_ports_decodes_mapping():
    mapping, _ = pv.suggest_roles([C3_A, C3_B])
    assert pv.roles_to_ports(mapping) == ("COM3", "COM7")
    assert pv.roles_to_ports({"COM3": "DUT"}) == ("COM3", None)
    assert pv.roles_to_ports({}) == (None, None)


def test_render_commands_pairs_dut_and_satellite():
    mapping, _ = pv.suggest_roles([C3_A, C3_B])
    cmds = pv.render_commands(mapping)
    assert any("workbench --satellite COM7" in c for c in cmds)
    assert any("--port COM3" in c and "--workbench" in c for c in cmds)


def test_render_commands_single_board_has_no_workbench():
    cmds = pv.render_commands({"COM3": "DUT"})
    assert any("--port COM3" in c for c in cmds)
    assert not any("workbench" in c for c in cmds)


def test_diff_reports_connect_and_disconnect():
    (connected,) = pv.diff_ports([], [C3_A])
    assert connected.startswith("+ COM3 connected:") and "4830A1" in connected
    assert pv.diff_ports([C3_A], []) == ["- COM3 disconnected"]
    assert pv.diff_ports([C3_A], [C3_A]) == []


def test_format_report_is_text_and_mentions_boards():
    report = pv.format_report([C3_A, C3_B, OTHER])
    assert "boards found: 2" in report
    assert "DUT" in report and "satellite" in report


def test_report_is_structured_snapshot():
    # the shape the VS Code extension's Boards tree consumes
    r = pv.report([C3_A, C3_B, OTHER])
    assert r["boards"] == 2
    assert r["dut"] == "COM3" and r["satellite"] == "COM7"
    assert r["mapping"] == {"COM3": "DUT", "COM7": "satellite"}
    assert len(r["ports"]) == 3
    kinds = {row["device"]: row["kind"] for row in r["ports"]}
    assert kinds == {"COM3": "board", "COM7": "board", "COM1": "other"}
    assert any("workbench --satellite COM7" in c for c in r["commands"])


def test_report_no_board_is_empty_mapping():
    r = pv.report([OTHER])
    assert r["boards"] == 0
    assert r["dut"] is None and r["satellite"] is None
    assert r["mapping"] == {}
