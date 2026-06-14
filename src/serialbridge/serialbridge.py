#!/usr/bin/env python3
"""mcuflow bridge - serve a local serial port over the network (RFC2217).

Wraps esptool's esp_rfc2217_server so a board on this host's COM port can be
flashed or monitored from another machine on the LAN:

    # on the host with the board:
    mcuflow bridge --port COM6 --tcp 4000
    # on another machine:
    mcuflow flash examples/board-c3.yml --port rfc2217://<host>:4000

esptool/idf.py (and pyserial) accept rfc2217:// URLs natively, so no other
change is needed on the flashing side. The server is single-connection; it
serves one board and waits for the next client when a connection ends.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def build_cmd(serial_port, tcp_port, python=sys.executable):
    """argv that serves `serial_port` over RFC2217 on `tcp_port`."""
    return [python, "-m", "esp_rfc2217_server", "-p", str(tcp_port), serial_port]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mcuflow bridge", description="serve a serial port over the network (RFC2217)"
    )
    ap.add_argument(
        "--port", required=True, help="local serial port to share (e.g. COM6, /dev/ttyACM0)"
    )
    ap.add_argument("--tcp", type=int, default=4000, help="TCP port to listen on (default 4000)")
    args = ap.parse_args(argv)
    print("serving " + args.port + " over rfc2217://0.0.0.0:" + str(args.tcp))
    print("flash from another host with: --port rfc2217://<this-host>:" + str(args.tcp))
    try:
        return subprocess.run(build_cmd(args.port, args.tcp)).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
