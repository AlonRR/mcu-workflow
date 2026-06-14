"""Unit regression for mcuflow CLI internals that don't need a subprocess."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_cli_test", ROOT / "src" / "mcuflow" / "mcuflow.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


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
