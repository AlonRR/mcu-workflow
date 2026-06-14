"""Unit regression for the launcher (src/launcher/up.py).

Covers the argument-handling and doctor-probe bugs fixed alongside this file:
the flat parser must accept globals on either side of the subcommand, the image
probe must not read a daemon-down error as "present", and a --dry-run must
preview without requiring an in-cage agent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_launcher_test", ROOT / "src" / "launcher" / "up.py"
)
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)


# --- flat parser: every option works in any position vs. the subcommand -------

PARSE_CASES = [
    # documented form: globals on BOTH sides of the subcommand
    (["--project", "X", "up", "--busid", "1-1", "--dry-run"], dict(cmd="up", dry_run=True)),
    (["--dry-run", "--project", "X", "up", "--busid", "1-1"], dict(cmd="up", dry_run=True)),
    # a global after the subcommand must not reset a value given before it
    (["--project", "X", "up"], dict(project=Path("X"))),
    # default subcommand + untouched defaults
    ([], dict(cmd="up", dry_run=False, project=Path("."))),
    (["doctor", "--fix"], dict(cmd="doctor", fix=True)),
    (["--dry-run", "doctor"], dict(cmd="doctor", dry_run=True)),
]


@pytest.mark.parametrize(
    ("argv", "expect"), PARSE_CASES, ids=[" ".join(a) or "(empty)" for a, _ in PARSE_CASES]
)
def test_parser_orderings(argv, expect):
    ns = up.build_parser().parse_args(argv)
    for key, val in expect.items():
        assert getattr(ns, key) == val


def test_busid_repeats_collect_two_boards():
    ns = up.build_parser().parse_args(["--busid", "1-1", "--busid", "1-2", "up"])
    assert ns.busid == ["1-1", "1-2"]


# --- image_status: daemon-down must never read as "present" -------------------


def test_image_status_daemon_down():
    # non-zero rc means the probe failed (daemon down); the captured stderr text
    # must not be mistaken for an image id.
    assert "not reachable" in up.image_status(1, "failed to connect to the docker API ...")


def test_image_status_present_and_absent():
    assert up.image_status(0, "a1b2c3d4\n") == "present"
    assert "not pulled" in up.image_status(0, "")


# --- dry-run previews without an agent; real entry still requires one ---------


def test_dry_run_previews_without_agent():
    argv = ["--os", "linux", "--dry-run", "up", "--device", "/dev/ttyACM0"]
    assert up.main(argv) == up.EXIT_OK


# --- doctor readiness reflects a stopped docker daemon -----------------------


class _FakeRunner:
    dry_run = False

    def __init__(self, rc, out):
        self._rc, self._out = rc, out

    def run(self, cmd, **kw):
        return self._rc, self._out


def test_doctor_warns_when_daemon_down(monkeypatch, capsys):
    monkeypatch.setattr(up, "have", lambda tool: True)  # all tools installed
    args = up.build_parser().parse_args(["doctor"])
    rc = up.cmd_doctor(args, {"image": "img"}, "linux", _FakeRunner(1, "cannot connect"))
    out = capsys.readouterr().out
    assert "start Docker" in out and rc == up.EXIT_OK  # installed, but not "yes"


def test_doctor_ready_when_daemon_up(monkeypatch, capsys):
    monkeypatch.setattr(up, "have", lambda tool: True)
    args = up.build_parser().parse_args(["doctor"])
    rc = up.cmd_doctor(args, {"image": "img"}, "linux", _FakeRunner(0, "abc123\n"))
    out = capsys.readouterr().out
    assert "ready: yes" in out and rc == up.EXIT_OK


# --- misplaced single-subcommand flags are rejected, not silently ignored ----


def test_reject_misplaced_flags():
    p = up.build_parser()
    # --fix belongs to doctor; with the default `up` it must be rejected
    with pytest.raises(SystemExit):
        up._reject_misplaced_flags(p, p.parse_args(["--fix"]))
    # --busid belongs to up; on `usb` it must be rejected
    with pytest.raises(SystemExit):
        up._reject_misplaced_flags(p, p.parse_args(["usb", "--busid", "1-1"]))


def test_accept_correct_flag_placement():
    p = up.build_parser()
    # these must NOT raise
    up._reject_misplaced_flags(p, p.parse_args(["doctor", "--fix"]))
    up._reject_misplaced_flags(p, p.parse_args(["--busid", "1-1", "up"]))
    up._reject_misplaced_flags(p, p.parse_args(["--dry-run", "--project", "X", "up"]))


def test_real_entry_without_agent_is_usage_error(tmp_path):
    # No cage.yaml in tmp_path -> no agent -> a non-dry-run entry must refuse.
    # --os windows skips the "docker not found" guard (which precedes the agent
    # check) so this hits the agent-required path deterministically on any host.
    argv = ["--os", "windows", "--project", str(tmp_path), "up"]
    assert up.main(argv) == up.EXIT_USAGE
