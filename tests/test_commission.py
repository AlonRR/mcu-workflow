"""Regression for `mcuflow commission`: the bench-matches-board.yml gate.

Each check is exercised against a simulated bench twice - wired as board.yml
declares (must PASS) and mis-wired or mis-matched (must FAIL) - so a check that
cannot tell the two apart fails here. The parsers are fed text captured from a
real ESP32-C3 (esptool v5 and the ROM boot banner), not text written to match.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from satellite.host.sim import make_sim_satellite  # noqa: E402
from sim.bench import SimBench  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "mcuflow_commission_test", ROOT / "src" / "commission" / "commission.py"
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

MCUFLOW = [sys.executable, str(ROOT / "src" / "mcuflow" / "mcuflow.py")]
C3_PATH = ROOT / "examples" / "board-c3.yml"
C3 = yaml.safe_load(C3_PATH.read_text(encoding="utf-8"))

# The esptool v5 header (chip type .. USB mode) was captured from an ESP32-C3 Super
# Mini on 15 Oct 2026 by a chip-id run (esptool v5.3.1; MAC lines dropped). The
# "Detected flash size:" line was NOT captured: its shape is taken from esptool
# 5.3.1's own source (cli_util.py / cmds.py print f"Detected flash size: {size}").
ESPTOOL_V5 = """esptool v5.3.1
Connected to ESP32-C3 on COM13:
Chip type:          ESP32-C3 (QFN32) (revision v0.4)
Features:           Wi-Fi, BT 5 (LE), Single Core, 160MHz, Embedded Flash 4MB (XMC)
Crystal frequency:  40MHz
USB mode:           USB-Serial/JTAG
Detected flash size: 4MB
Hard resetting via RTS pin...
"""
ESPTOOL_V4 = """esptool.py v4.8.1
Chip is ESP32-S3 (QFN56) (revision v0.2)
Detected flash size: 8MB
"""
# Captured from the same C3 on 15 Oct 2026: the ROM banner of an app boot.
ROM_APP_BOOT = [
    "ESP-ROM:esp32c3-api1-20210207",
    "Build:Feb  7 2021",
    "rst:0x15 (USB_UART_CHIP_RESET),boot:0xf (SPI_FAST_FLASH_BOOT)",
    "Saved PC:0x40383646",
]


def statuses(rep):
    return {c["check"]: c["status"] for c in rep["checks"]}


def detail(rep, name):
    return next(c["detail"] for c in rep["checks"] if c["check"] == name)


# --- parsers -----------------------------------------------------------------


def test_parse_identity_esptool_v5():
    ident = cm.parse_identity(ESPTOOL_V5)
    assert ident == {"chip": "ESP32-C3 (QFN32) (revision v0.4)", "flash": "4MB"}


def test_parse_identity_esptool_v4():
    ident = cm.parse_identity(ESPTOOL_V4)
    assert ident == {"chip": "ESP32-S3 (QFN56) (revision v0.2)", "flash": "8MB"}


def test_parse_identity_reports_absence_not_a_guess():
    assert cm.parse_identity("A fatal error occurred: Failed to connect") == {
        "chip": None,
        "flash": None,
    }


def test_chip_slug_matches_board_spelling():
    assert cm.chip_slug("ESP32-C3 (QFN32) (revision v0.4)") == "esp32c3"
    assert cm.chip_slug("esp32c3") == "esp32c3"
    assert cm.chip_slug("ESP32-S3 (QFN56)") != cm.chip_slug("esp32c3")


def test_boot_mode_reads_the_rom_line():
    assert cm.boot_mode(ROM_APP_BOOT) == "flash"
    # NOT captured (the download-mode capture was lost); written in the ROM's format.
    # The parser keys on the mode NAME, so the chip-specific hex does not matter.
    dl = ["rst:0x15 (USB_UART_CHIP_RESET),boot:0x5 (DOWNLOAD(USB/UART0))", "waiting for download"]
    assert cm.boot_mode(dl) == "download"
    # app output with no ROM line (or nothing at all) proves nothing either way
    assert cm.boot_mode(["I (320) app: app_main started"]) is None
    assert cm.boot_mode([]) is None


def test_declared_flash_from_sdkconfig():
    assert cm.declared_flash(C3) == "4MB"
    assert cm.declared_flash({"meta": {"chip": "esp32c3"}}) is None


# --- the gate against a correctly wired bench ---------------------------------


def test_c3_bench_wired_as_declared_passes():
    rep = cm.commission(C3, SimBench(C3))
    st = statuses(rep)
    assert rep["ok"], rep
    for name in ("dut_port", "dut_chip", "dut_flash", "satellite", "boot_line", "reset_line"):
        assert st[name] == "pass", (name, detail(rep, name))
    # pins:/devices: need code on the DUT; reported as unverified, never as passed
    assert st["pins_devices"] == "unverified"
    assert rep["counts"] == {"pass": 6, "fail": 0, "skip": 0, "unverified": 1}
    assert rep["total"] == 7


def test_boot_line_leaves_dut_in_app_and_line_released():
    bench = SimBench(C3)
    cm.commission(C3, bench)
    pin = C3["rig"]["dut_boot_gpio"]
    assert bench.mode == "flash"  # the last reset booted the app, not the loader
    assert pin in bench.state.inputs  # satellite released the line (gpio.get)


# --- each check must fail when the bench is wrong (negative controls) ----------


def test_wrong_chip_fails():
    rep = cm.commission(C3, SimBench(C3, chip="ESP32-S3 (QFN56) (revision v0.2)"))
    assert statuses(rep)["dut_chip"] == "fail"
    assert not rep["ok"]


def test_smaller_flash_than_declared_fails():
    rep = cm.commission(C3, SimBench(C3, flash="2MB"))
    assert statuses(rep)["dut_flash"] == "fail"


def test_larger_flash_than_declared_passes():
    rep = cm.commission(C3, SimBench(C3, flash="8MB"))
    assert statuses(rep)["dut_flash"] == "pass"


def test_satellite_missing_a_needed_capability_fails():
    rep = cm.commission(C3, SimBench(C3, caps=("gpio", "siggen")))
    assert statuses(rep)["satellite"] == "fail"
    assert "wifi" in detail(rep, "satellite")


def test_required_satellite_absent_fails():
    rep = cm.commission(C3, SimBench(C3, satellite=False))
    st = statuses(rep)
    assert st["satellite"] == "fail"
    # the rig lines can't be driven, so they are unverified - not passed, not skipped
    assert st["boot_line"] == "unverified"
    assert st["reset_line"] == "unverified"


def test_satellite_on_the_dut_port_fails():
    rep = cm.commission(C3, SimBench(C3, sat_port="SIM-DUT"))
    assert statuses(rep)["satellite"] == "fail"


def test_unwired_boot_line_fails():
    # the bug this gate exists for: the satellite drives a pin that reaches nothing
    rep = cm.commission(C3, SimBench(C3, boot_wire=None))
    assert statuses(rep)["boot_line"] == "fail"
    assert "no effect" in detail(rep, "boot_line")


def test_boot_line_on_another_satellite_pin_fails():
    # board.yml says GPIO2, the wire is really on GPIO9 - the old board-c3.yml mix-up
    rep = cm.commission(C3, SimBench(C3, boot_wire=9))
    assert statuses(rep)["boot_line"] == "fail"


def test_boot_strap_stuck_low_fails():
    rep = cm.commission(C3, SimBench(C3, boot_stuck_low=True))
    assert statuses(rep)["boot_line"] == "fail"
    assert "released" in detail(rep, "boot_line")


def test_boot_line_recovers_a_dut_the_usb_reset_cannot_free():
    # Measured 15 Oct 2026: from the ROM loader an RTS pulse printed nothing and
    # left the chip there, while esptool's hard reset brought it back. The check
    # must not leave the DUT in download mode when its control reset can't.
    bench = SimBench(C3, usb_reset_frees_loader=False)
    rep = cm.commission(C3, bench)
    assert statuses(rep)["boot_line"] == "pass", detail(rep, "boot_line")
    assert bench.recoveries == 1
    assert bench.mode == "flash"
    assert "esptool hard reset" in detail(rep, "boot_line")


def test_boot_line_names_the_manual_recovery_when_it_cannot_confirm():
    # Nothing readable after any reset: unproven, and the DUT's state unknown -
    # the detail must say how to get it out of the loader by hand.
    bench = SimBench(C3, rom_silent=True)
    rep = cm.commission(C3, bench)
    assert statuses(rep)["boot_line"] == "fail"
    assert bench.recoveries == 1
    assert "--before no_reset --after hard_reset chip_id" in detail(rep, "boot_line")


def test_boot_line_does_not_recover_a_dut_that_booted_normally():
    bench = SimBench(C3)
    cm.commission(C3, bench)
    assert bench.recoveries == 0


def test_unwired_reset_line_fails():
    rep = cm.commission(C3, SimBench(C3, reset_wire=None))
    assert statuses(rep)["reset_line"] == "fail"


def test_missing_dut_port_fails_and_dut_checks_do_not_run():
    rep = cm.commission(C3, SimBench(C3, dut_present=False))
    st = statuses(rep)
    assert st["dut_port"] == "fail"
    for name in ("dut_chip", "dut_flash", "boot_line", "reset_line"):
        assert st[name] == "unverified", name


# --- applicability -------------------------------------------------------------


def test_board_without_rig_or_radio_needs_skips_satellite_checks():
    board = {"meta": {"project": "x", "platform": "esp32", "chip": "esp32c3"}}
    rep = cm.commission(board, SimBench(board, satellite=False))
    st = statuses(rep)
    assert rep["ok"]
    assert st["satellite"] == "skip"
    assert st["boot_line"] == "skip"
    assert st["reset_line"] == "skip"
    assert st["dut_flash"] == "skip"  # nothing declared to compare against
    assert st["pins_devices"] == "skip"


# --- the satellite simulator mirrors the firmware's pin release ----------------


def test_sim_gpio_get_releases_the_pin_like_the_firmware():
    sat = make_sim_satellite()
    sat.gpio_set(2, 0)
    assert 2 not in sat.t.state.inputs
    sat.gpio_get(2)  # firmware: gpio_reset_pin + INPUT
    assert 2 in sat.t.state.inputs
    sat.gpio_set(2, 1)  # driving it again takes it back
    assert 2 not in sat.t.state.inputs


# --- board-c3.yml's rig pins are the ones the runbook wires --------------------


def test_board_c3_rig_pins_match_the_runbook_wiring():
    # rig.dut_*_gpio name SATELLITE pins (hil drives them via /api/gpio/set).
    # The runbook's diagram is the bench as built; the board file must agree.
    text = (ROOT / "docs" / "runbook-c3.md").read_text(encoding="utf-8")
    wired = {
        role: int(sat) for sat, role in re.findall(r"GPIO(\d+)\s+\((stimulus|reset)\)\s+-+>", text)
    }
    assert wired, "no wiring diagram found in the runbook"
    assert C3["rig"]["dut_boot_gpio"] == wired["stimulus"]
    assert C3["rig"]["dut_reset_gpio"] == wired["reset"]


# --- CLI -----------------------------------------------------------------------


def test_cli_sim_commission_passes_with_json_envelope():
    r = subprocess.run(
        MCUFLOW + ["--sim", "--json", "commission", str(C3_PATH)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["verb"] == "commission" and out["ok"] is True
    assert out["report"]["counts"]["fail"] == 0


def test_cli_real_commission_without_port_is_a_usage_error():
    # it resets the board, and a connected ESP32 is not necessarily the DUT -
    # so it never auto-picks one, and touches no hardware before refusing
    r = subprocess.run(
        MCUFLOW + ["--json", "commission", str(C3_PATH)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--port" in json.loads(r.stdout)["detail"]


def test_cli_satellite_on_the_dut_port_is_a_usage_error():
    r = subprocess.run(
        MCUFLOW + ["--json", "commission", str(C3_PATH), "--port", "COM9", "--satellite", "COM9"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2, r.stdout + r.stderr


def test_rig_pins_do_not_share_the_dut_pin_namespace():
    # A satellite pin and a DUT pin with the same number are different wires;
    # the validator's pin-conflict check must not mix them up.
    spec = importlib.util.spec_from_file_location(
        "mcuflow_validate_test", ROOT / "src" / "board-schema" / "validate.py"
    )
    v = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)
    board = {
        "meta": {"project": "x", "platform": "esp32", "chip": "esp32c3"},
        "pins": {"i2c0": {"sda": 2, "scl": 3}},
        "rig": {"dut_boot_gpio": 2, "dut_reset_gpio": 3, "satellite": "required"},
    }
    _errors, warnings = v.semantic_checks(board)
    assert not [w for w in warnings if "more than one role" in w], warnings
