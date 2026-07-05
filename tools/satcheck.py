#!/usr/bin/env python3
"""One-shot satellite check: start the workbench in-process, run one command,
print the result, and exit. No server is left running - nothing to Ctrl+C.

Run with the project's venv python so pyserial is available:

  .venv\\Scripts\\python.exe tools\\satcheck.py --satellite COM9 ping
  .venv\\Scripts\\python.exe tools\\satcheck.py --satellite COM9 caps
  .venv\\Scripts\\python.exe tools\\satcheck.py --satellite COM9 siggen
  .venv\\Scripts\\python.exe tools\\satcheck.py --satellite COM9 ble     # the scan under test

Use --satellite sim to try it with no hardware.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in tools/)
_spec = importlib.util.spec_from_file_location("wb", ROOT / "src" / "workbench" / "workbench.py")
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def call(base_url, path, data=None, timeout=40):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(
        base_url + path,
        data=body,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--satellite", default="sim", help="serial port (e.g. COM9) or 'sim'")
    ap.add_argument(
        "check",
        nargs="?",
        default="ping",
        choices=["ping", "caps", "wifi", "siggen", "ble"],
    )
    a = ap.parse_args()

    base_url, srv = wb.serve_inprocess(a.satellite)
    print(f"satellite backend: {wb.Handler.sat_info['backend']}  ({a.satellite})")
    try:
        if a.check == "ping":
            print("ping:", call(base_url, "/api/satellite/ping", {}))
        elif a.check == "caps":
            print("capabilities:", json.dumps(call(base_url, "/api/capabilities"), indent=2))
        elif a.check == "wifi":
            print("wifi scan:", call(base_url, "/api/wifi/scan", {}))
        elif a.check == "siggen":
            print(
                "start:", call(base_url, "/api/siggen/start", {"pin": 4, "freq": 2000, "duty": 25})
            )
            print("stop :", call(base_url, "/api/siggen/stop", {}))
        elif a.check == "ble":
            print("scanning ~5s (this is the command that may reset the board)...")
            print(
                "ble scan:", json.dumps(call(base_url, "/api/ble/scan", {"timeout": 5}), indent=2)
            )
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
