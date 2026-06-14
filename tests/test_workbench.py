"""Regression for host-side workbench pieces that need no serial hardware."""

from __future__ import annotations

import base64
import importlib.util
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_workbench_test", ROOT / "src" / "workbench" / "workbench.py"
)
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_udp_log_listener_collects_lines():
    wb.UDP_LOG.clear()
    port = _free_udp_port()
    threading.Thread(target=wb._udp_log_listener, args=("127.0.0.1", port), daemon=True).start()
    time.sleep(0.2)
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.sendto(b"boot: hi\nwifi: connected\n", ("127.0.0.1", port))
    for _ in range(60):
        if len(wb.UDP_LOG) >= 2:
            break
        time.sleep(0.05)
    lines = [r["line"] for r in wb.UDP_LOG]
    assert "boot: hi" in lines and "wifi: connected" in lines
    assert all("src" in r and "t" in r for r in wb.UDP_LOG)


def test_detect_capabilities_marks_udp_log_available():
    caps = wb.detect_capabilities([], satellite=None)
    assert caps["udp_log"] is True


def test_safe_name_rejects_traversal():
    assert wb._safe_name("app.bin") == "app.bin"
    assert wb._safe_name("../../etc/passwd") == "passwd"  # basename only
    assert wb._safe_name("") is None
    assert wb._safe_name("..") is None


def test_ota_upload_then_download_roundtrip(tmp_path):
    wb.FIRMWARE_DIR = str(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        blob = bytes(range(256)) * 4

        def post(path, obj):
            r = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(obj).encode(),
                headers={"Content-Type": "application/json"},
            )
            return json.loads(urllib.request.urlopen(r, timeout=5).read())

        up = post(
            "/api/firmware/upload", {"name": "fw.bin", "data_b64": base64.b64encode(blob).decode()}
        )
        assert up["ok"] and up["bytes"] == len(blob)
        got = urllib.request.urlopen(f"http://127.0.0.1:{port}/firmware/fw.bin", timeout=5).read()
        assert got == blob
        # an unknown image 404s
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/firmware/nope.bin", timeout=5)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
