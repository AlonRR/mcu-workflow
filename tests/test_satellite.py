"""Regression for the satellite host driver against the in-process simulator.

Exercises the command round-trip (driver -> protocol -> sim firmware model) with
no serial hardware, so it runs in CI. The same commands run unchanged against
the real ESP32 satellite over USB.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from satellite.host.sim import make_sim_satellite  # noqa: E402


def test_caps_includes_siggen():
    sat = make_sim_satellite()
    assert "siggen" in sat.caps()["capabilities"]


def test_siggen_start_stop_roundtrip():
    sat = make_sim_satellite()
    r = sat.siggen_start(5, freq=2000, duty=25)
    assert r["ok"] and r["freq"] == 2000 and r["duty"] == 25
    assert sat.siggen_stop()["ok"]


def test_siggen_duty_is_clamped():
    sat = make_sim_satellite()
    assert sat.siggen_start(5, duty=250)["duty"] == 100


def test_siggen_requires_pin():
    sat = make_sim_satellite()
    assert sat.siggen_start(-1)["ok"] is False


def test_caps_includes_ble():
    assert "ble" in make_sim_satellite().caps()["capabilities"]


def test_ble_scan_returns_devices():
    devs = make_sim_satellite().ble_scan()["devices"]
    assert devs and all({"addr", "name", "rssi"} <= set(d) for d in devs)


def test_ble_write_is_unsupported():
    assert make_sim_satellite().ble_write("aa:bb", "ff01", "00")["ok"] is False
