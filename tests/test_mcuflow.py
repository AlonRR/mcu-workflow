"""Unit regression for mcuflow CLI internals that don't need a subprocess."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_cli_test", ROOT / "src" / "mcuflow" / "mcuflow.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
C3 = ROOT / "examples" / "board-c3.yml"
TMP = ROOT / "build-out" / "_run_port_test"


def test_global_flag_strings_derived_from_parser():
    # The up/workbench passthrough skip-set is derived from the parser so it
    # can't drift; it must contain the real globals and not subcommand flags.
    flags = m._global_flag_strings(m.build_parser())
    assert "--json" in flags and "--sim" in flags
    assert "--port" not in flags  # a subcommand flag, not a global
    assert "-h" not in flags and "--help" not in flags


def test_autodetect_does_not_swallow_real_errors(monkeypatch):
    # A genuine failure must propagate (so verb_run fails the ports stage loudly)
    # rather than being masked as a benign "no board" result.
    def boom(*a, **k):
        raise RuntimeError("port stack exploded")

    monkeypatch.setattr(m, "_load_sibling", boom)
    with pytest.raises(RuntimeError):
        m._autodetect_dut_satellite()


def _run_without_port(monkeypatch, capsys, detected):
    """Real-hardware `run` with no --port, auto-detect stubbed to `detected`.
    Returns (exit code, envelope, whether any later stage was reached)."""
    monkeypatch.setattr(m, "_autodetect_dut_satellite", lambda: detected)
    reached = []
    monkeypatch.setattr(m, "_run", lambda cmd, **k: reached.append(cmd) or (0, "", ""))
    args = m.build_parser().parse_args(["--json", "run", str(C3), "-o", str(TMP)])
    rc = m.verb_run(args)
    return rc, json.loads(capsys.readouterr().out), reached


def test_real_run_without_port_refuses_and_names_the_candidate(monkeypatch, capsys):
    # A lone connected ESP32 may belong to another project: run flashes, so it
    # must not pick one. It refuses before validating, building or flashing,
    # and says which port it would have used so the user can pass it on purpose.
    rc, out, reached = _run_without_port(
        monkeypatch, capsys, ("COM13", None, 1, "one board found - treated as the DUT")
    )
    assert rc == m.EXIT_USAGE
    assert out["ok"] is False
    assert [s["stage"] for s in out["stages"]] == ["ports"]
    detail = out["stages"][0]["detail"]
    assert "--port" in detail and "COM13" in detail
    assert reached == []  # no subprocess: nothing validated, built or flashed


def test_real_run_without_port_and_no_board_is_a_usage_error(monkeypatch, capsys):
    rc, out, reached = _run_without_port(monkeypatch, capsys, (None, None, 0, "no board"))
    assert rc == m.EXIT_USAGE
    assert "--port" in out["stages"][0]["detail"]
    assert reached == []
