#!/usr/bin/env python3
"""
workbench.py - host-agnostic networked test instrument (deliverable #9).

A minimal HTTP service that turns any Python+USB host (Pi, mini-PC, laptop)
into a shared test instrument. This core uses only the Python standard library
so it runs anywhere; the radio/GPIO instruments (WiFi/BLE/GPIO/siggen) are
provided by a pluggable backend - by default the ESP32 satellite over USB-serial
(deliverable #8), or its in-process simulator so the whole thing runs with no
hardware at all.

Read endpoints (GET, JSON):
  /api/health             {"ok": true}
  /api/info               host name, platform, slot count, uptime
  /api/capabilities       which instruments this host provides
  /api/devices            discovered serial slots (chip, port, url)
  /api/satellite/caps     capabilities reported by the attached satellite
  /api/udplog?source&n    device logs received over UDP (newest n; filter by ip)
  /api/firmware           list OTA images available to serve
  /firmware/<name>        download an OTA image (point the DUT's OTA URL here)

Instrument endpoints (POST, JSON body) - driven through the satellite backend:
  /api/satellite/ping     -> {"ok": true, "fw": ...}
  /api/wifi/ap_start      {ssid, password?, channel?} -> {"ok": true, "ip": ...}
  /api/wifi/ap_stop       -> {"ok": true}
  /api/wifi/scan          -> {"ok": true, "networks": [...]}
  /api/gpio/set           {pin, value}                -> {"ok": true}
  /api/gpio/get           {pin}                       -> {"ok": true, "value": ...}
  /api/siggen/start       {pin, freq?, duty?}         -> {"ok": true, "freq", "duty"}
  /api/siggen/stop        -> {"ok": true}
  /api/firmware/upload    {name, data_b64}            -> {"ok": true, "url", ...}

Run:  python workbench.py --port 6283                       # binds 0.0.0.0
      python workbench.py --satellite sim                   # emulated radios
      python workbench.py --satellite /dev/ttyACM1          # real satellite
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import platform
import shutil
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Make the repo root importable so `satellite.host...` resolves when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START = time.time()

# Device logs received over UDP (read at /api/udplog). A board can ship its log
# lines to the workbench when its USB serial is busy (HID gadget, mid-OTA); the
# firmware just sends UDP datagrams to <workbench-ip>:<udp_port>.
UDP_LOG = deque(maxlen=2000)

# Directory of firmware images served for OTA (GET /firmware/<name>); set in
# main() from --firmware-dir. A DUT points its OTA URL at
# http://<workbench>:<port>/firmware/<name>.
FIRMWARE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_firmware")


def _safe_name(name):
    """A bare filename (no path traversal) for the firmware store, or None."""
    base = os.path.basename(name or "")
    return base if base and base not in (".", "..") else None


def _udp_log_listener(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except OSError:
            break
        for line in data.decode("utf-8", "replace").splitlines():
            if line:
                UDP_LOG.append({"t": round(time.time() - START, 1), "src": addr[0], "line": line})


def open_satellite(spec):
    """spec is None, 'sim', or a serial port/url. Returns (Satellite|None, info)."""
    if not spec:
        return None, {"backend": "none"}
    from satellite.host.satellite_driver import Satellite

    if spec == "sim":
        from satellite.host.sim import SimSatelliteTransport

        return Satellite(SimSatelliteTransport()), {"backend": "sim"}
    return Satellite.open_serial(spec), {"backend": "serial", "port": spec}


def detect_capabilities(enabled_extra, satellite):
    """serial is always on; gdb/mqtt auto-detected; radios from the satellite."""
    caps = {
        "serial": True,
        "gdb": shutil.which("openocd") is not None,
        "wifi": False,
        "ble": False,
        "gpio": False,
        "siggen": False,
        "udp_log": True,
        "ota": True,
        "mqtt": shutil.which("mosquitto") is not None,
    }
    if satellite is not None:
        try:
            r = satellite.caps()
            for c in r.get("capabilities") or []:
                if c in caps:
                    caps[c] = True
        except Exception:
            pass
    for k in enabled_extra:
        if k in caps:
            caps[k] = True
    return caps


def list_serial():
    """Discover serial ports cross-platform (Windows COM* and POSIX /dev/tty*)."""
    if os.name == "nt":
        try:
            from serial.tools import list_ports  # pyserial

            return sorted(p.device for p in list_ports.comports())
        except Exception:
            return []
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def discover_slots(host):
    slots = []
    for i, dev in enumerate(list_serial(), start=1):
        slots.append(
            {
                "label": "SLOT" + str(i),
                "devnode": dev,
                "tcp_port": 4000 + i,
                "url": "rfc2217://" + host + ":" + str(4000 + i),
                "detected_chip": None,
                "state": "idle",
            }
        )
    return slots


class Handler(BaseHTTPRequestHandler):
    server_version = "mcuflow-workbench/0.2"
    caps = {}
    satellite = None
    sat_info = {"backend": "none"}
    sat_lock = threading.Lock()

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type="application/octet-stream", code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def _need_sat(self):
        if self.satellite is None:
            self._send(
                {
                    "ok": False,
                    "error": "no satellite backend "
                    "(start the workbench with --satellite sim|<port>)",
                },
                code=503,
            )
            return False
        return True

    def _sat_call(self, fn):
        with self.sat_lock:
            try:
                return fn(self.satellite)
            except Exception as e:
                return {"ok": False, "error": "satellite error: " + str(e)}

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        host = self.headers.get("Host", "localhost").split(":")[0]
        if self.path == "/api/health":
            self._send({"ok": True})
        elif self.path == "/api/info":
            self._send(
                {
                    "ok": True,
                    "hostname": socket.gethostname(),
                    "platform": platform.platform(),
                    "slots": len(list_serial()),
                    "satellite": self.sat_info,
                    "uptime_s": round(time.time() - START, 1),
                }
            )
        elif self.path == "/api/capabilities":
            self._send({"ok": True, "capabilities": self.caps})
        elif self.path == "/api/devices":
            self._send({"ok": True, "slots": discover_slots(host)})
        elif self.path == "/api/satellite/caps":
            if not self._need_sat():
                return
            self._send(self._sat_call(lambda s: s.caps()))
        elif self.path.startswith("/api/udplog"):
            q = parse_qs(urlparse(self.path).query)
            src = q.get("source", [None])[0]
            try:
                n = int(q.get("n", ["100"])[0])
            except ValueError:
                n = 100
            rows = [r for r in UDP_LOG if src is None or r["src"] == src]
            self._send({"ok": True, "lines": rows[-n:]})
        elif self.path == "/api/firmware":
            try:
                names = sorted(os.listdir(FIRMWARE_DIR))
            except OSError:
                names = []
            self._send({"ok": True, "firmware": names})
        elif self.path.startswith("/firmware/"):
            name = _safe_name(self.path[len("/firmware/") :])
            path = os.path.join(FIRMWARE_DIR, name) if name else None
            if not path or not os.path.isfile(path):
                self._send({"ok": False, "error": "no such firmware"}, code=404)
                return
            with open(path, "rb") as f:
                self._send_bytes(f.read())
        else:
            self._send({"ok": False, "error": "not found: " + self.path}, code=404)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self._send({"ok": False, "error": "not found: " + self.path}, code=404)
            return
        body = self._read_body()
        if body is None:
            self._send({"ok": False, "error": "bad json body"}, code=400)
            return
        # Firmware upload needs no satellite (OTA is host-served); handle first.
        if self.path == "/api/firmware/upload":
            name = _safe_name(body.get("name"))
            if not name or "data_b64" not in body:
                self._send({"ok": False, "error": "name and data_b64 required"}, code=400)
                return
            try:
                blob = base64.b64decode(body["data_b64"])
            except (ValueError, TypeError):
                self._send({"ok": False, "error": "data_b64 not valid base64"}, code=400)
                return
            os.makedirs(FIRMWARE_DIR, exist_ok=True)
            with open(os.path.join(FIRMWARE_DIR, name), "wb") as f:
                f.write(blob)
            host = self.headers.get("Host", "localhost")
            self._send(
                {
                    "ok": True,
                    "name": name,
                    "bytes": len(blob),
                    "url": "http://" + host + "/firmware/" + name,
                }
            )
            return
        if not self._need_sat():
            return
        p = self.path
        if p == "/api/satellite/ping":
            self._send(self._sat_call(lambda s: s.ping()))
        elif p == "/api/wifi/ap_start":
            ssid = body.get("ssid")
            if not ssid:
                self._send({"ok": False, "error": "ssid required"}, code=400)
                return
            self._send(
                self._sat_call(
                    lambda s: s.wifi_ap_start(ssid, body.get("password", ""), body.get("channel"))
                )
            )
        elif p == "/api/wifi/ap_stop":
            self._send(self._sat_call(lambda s: s.wifi_ap_stop()))
        elif p == "/api/wifi/scan":
            self._send(self._sat_call(lambda s: s.wifi_scan()))
        elif p == "/api/gpio/set":
            if "pin" not in body or "value" not in body:
                self._send({"ok": False, "error": "pin and value required"}, code=400)
                return
            self._send(self._sat_call(lambda s: s.gpio_set(body["pin"], body["value"])))
        elif p == "/api/gpio/get":
            if "pin" not in body:
                self._send({"ok": False, "error": "pin required"}, code=400)
                return
            self._send(self._sat_call(lambda s: s.gpio_get(body["pin"])))
        elif p == "/api/siggen/start":
            if "pin" not in body:
                self._send({"ok": False, "error": "pin required"}, code=400)
                return
            self._send(
                self._sat_call(
                    lambda s: s.siggen_start(
                        body["pin"], body.get("freq", 1000), body.get("duty", 50)
                    )
                )
            )
        elif p == "/api/siggen/stop":
            self._send(self._sat_call(lambda s: s.siggen_stop()))
        else:
            self._send({"ok": False, "error": "not found: " + p}, code=404)


def main(argv=None):
    global FIRMWARE_DIR
    ap = argparse.ArgumentParser(prog="mcuflow workbench", description="mcuflow workbench service")
    # 6283: an uncommon default (8080 collides with too many other dev tools).
    ap.add_argument("--port", type=int, default=6283)
    ap.add_argument(
        "--host",
        default="0.0.0.0",
        help="bind address (default 0.0.0.0 for LAN; use 127.0.0.1 locally)",
    )
    ap.add_argument(
        "--satellite",
        default=os.environ.get("WORKBENCH_SATELLITE", ""),
        help="radio/GPIO backend: 'sim' for the emulator, or a serial "
        "port/url like /dev/ttyACM1 for a real ESP32 satellite",
    )
    ap.add_argument(
        "--enable",
        default=os.environ.get("WORKBENCH_CAPS", ""),
        help="force-advertise extra capabilities (comma list)",
    )
    ap.add_argument(
        "--udp-port",
        type=int,
        default=6284,
        help="UDP port to collect device logs on (read at /api/udplog)",
    )
    ap.add_argument(
        "--firmware-dir",
        default=FIRMWARE_DIR,
        help="directory of OTA firmware images served at /firmware/<name>",
    )
    args = ap.parse_args(argv)

    FIRMWARE_DIR = args.firmware_dir
    os.makedirs(FIRMWARE_DIR, exist_ok=True)

    threading.Thread(target=_udp_log_listener, args=(args.host, args.udp_port), daemon=True).start()

    satellite, sat_info = open_satellite(args.satellite.strip() or None)
    extra = [c.strip() for c in args.enable.split(",") if c.strip()]
    Handler.satellite = satellite
    Handler.sat_info = sat_info
    Handler.caps = detect_capabilities(extra, satellite)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        "workbench listening on "
        + args.host
        + ":"
        + str(args.port)
        + "  satellite: "
        + sat_info["backend"]
        + "  capabilities: "
        + ",".join(k for k, v in Handler.caps.items() if v)
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
