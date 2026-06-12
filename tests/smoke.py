#!/usr/bin/env python3
"""
smoke.py - hardware-free regression check for the whole interface.

Runs the deterministic + simulated paths end to end (no toolchain, no boards)
and exits non-zero if anything regresses. Cross-platform: `python tests/smoke.py`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
M = [PY, str(ROOT / "mcuflow" / "mcuflow.py")]
C3 = str(ROOT / "board-schema" / "examples" / "board-c3.yml")
BROKEN = str(ROOT / "board-schema" / "examples" / "broken.yml")
TMP = ROOT / "build-out" / "_smoke"

CASES = [
    ("validate c3",        M + ["validate", C3],                 0),
    ("validate broken!=0", M + ["validate", BROKEN],             1),
    ("sim build",          M + ["--sim", "build"],               0),
    ("sim flash",          M + ["--sim", "flash", "--port", "COM5"], 0),
    ("hil c3 sim",         M + ["hil", C3],                       0),
    ("run c3 sim",         M + ["--sim", "run", C3, "-o", str(TMP)], 0),
    ("up dry two-board",   M + ["up", "--os", "linux", "--dry-run", "--project",
                                str(ROOT), "up", "--device", "/dev/ttyACM0",
                                "--device", "/dev/ttyACM1"],      0),
]


def main():
    npass = nfail = 0
    for name, cmd, want in CASES:
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        ok = (rc == want)
        print(("  ok   " if ok else "  FAIL ") + name
              + ("" if ok else " (rc=" + str(rc) + " want " + str(want) + ")"))
        npass += ok
        nfail += not ok
    print("\nRESULT: " + str(npass) + " passed, " + str(nfail) + " failed")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
