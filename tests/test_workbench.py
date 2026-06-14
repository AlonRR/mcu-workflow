"""Regression for host-side workbench pieces that need no serial hardware."""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
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
