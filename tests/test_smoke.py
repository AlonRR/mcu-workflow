"""Hardware-free regression for the whole mcuflow interface.

Drives the deterministic + simulated paths end to end (no toolchain, no boards)
through the CLI as a subprocess, and checks each exits with the contract's code.
Run with `pytest`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MCUFLOW = [sys.executable, str(ROOT / "src" / "mcuflow" / "mcuflow.py")]
C3 = str(ROOT / "examples" / "board-c3.yml")
BROKEN = str(ROOT / "examples" / "broken.yml")
TMP = str(ROOT / "build-out" / "_smoke")

# (id, mcuflow args, expected exit code)
CASES = [
    ("validate_c3", ["validate", C3], 0),
    ("validate_broken_is_nonzero", ["validate", BROKEN], 1),
    ("sim_build", ["--sim", "build"], 0),
    ("sim_flash", ["--sim", "flash", "--port", "COM5"], 0),
    ("hil_c3_sim", ["hil", C3], 0),
    ("run_c3_sim", ["--sim", "run", C3, "-o", TMP], 0),
    (
        "up_dry_two_board",
        [
            "up",
            "--os",
            "linux",
            "--dry-run",
            "--project",
            str(ROOT),
            "up",
            "--device",
            "/dev/ttyACM0",
            "--device",
            "/dev/ttyACM1",
        ],
        0,
    ),
]


@pytest.mark.parametrize(
    ("args", "want"),
    [(args, want) for _id, args, want in CASES],
    ids=[case_id for case_id, _args, _want in CASES],
)
def test_cli(args, want):
    rc = subprocess.run(
        MCUFLOW + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    assert rc == want
