#!/usr/bin/env python3
"""One-shot satellite check: start the workbench in-process, run one command,
print the result, and exit. No server is left running - nothing to Ctrl+C.

Run with the project's venv python so pyserial is available:

  .venv\\Scripts\\python.exe satcheck.py --satellite COM9 ping
  .venv\\Scripts\\python.exe satcheck.py --satellite COM9 caps
  .venv\\Scripts\\python.exe satcheck.py --satellite COM9 siggen
  .venv\\Scripts\\python.exe satcheck.py --satellite COM9 ble     # the scan under test

Use --satellite sim to try it with no hardware.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("wb", ROOT / "src" / "workbench" / "workbench.py")
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def call(port, path, data=None, timeout=40):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
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

    sat, info = wb.open_satellite(a.satellite)
    wb.Handler.satellite = sat
    wb.Handler.sat_info = info
    wb.Handler.caps = wb.detect_capabilities([], sat)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"satellite backend: {info['backend']}  ({a.satellite})")
    try:
        if a.check == "ping":
            print("ping:", call(port, "/api/satellite/ping", {}))
        elif a.check == "caps":
            print("capabilities:", json.dumps(call(port, "/api/capabilities"), indent=2))
        elif a.check == "wifi":
            print("wifi scan:", call(port, "/api/wifi/scan", {}))
        elif a.check == "siggen":
            print("start:", call(port, "/api/siggen/start", {"pin": 4, "freq": 2000, "duty": 25}))
            print("stop :", call(port, "/api/siggen/stop", {}))
        elif a.check == "ble":
            print("scanning ~5s (this is the command that may reset the board)...")
            print("ble scan:", json.dumps(call(port, "/api/ble/scan", {"timeout": 5}), indent=2))
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
