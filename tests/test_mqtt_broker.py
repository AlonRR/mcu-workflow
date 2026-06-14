"""Regression for the embedded MQTT broker: a real client subscribes and
receives a fan-out publish. Stdlib only, no external broker."""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "mcuflow_mqtt_test", ROOT / "src" / "workbench" / "mqtt_broker.py"
)
mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mb)


def test_topic_matches():
    assert mb._topic_matches("test/#", "test/a/b")
    assert mb._topic_matches("test/+/x", "test/a/x")
    assert not mb._topic_matches("test/+/x", "test/a/y")
    assert not mb._topic_matches("test/a", "test/a/b")
    assert mb._topic_matches("a/b", "a/b")


def _free_tcp_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _str(b):
    return len(b).to_bytes(2, "big") + b


def test_subscribe_then_receive_publish():
    broker = mb.Broker()
    port = _free_tcp_port()
    threading.Thread(target=broker.serve, args=("127.0.0.1", port), daemon=True).start()
    time.sleep(0.2)

    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    # CONNECT
    var = _str(b"MQTT") + bytes([0x04, 0x02, 0x00, 0x00]) + _str(b"tester")
    c.sendall(bytes([0x10]) + mb._encode_len(len(var)) + var)
    assert c.recv(4)[0] >> 4 == mb.CONNACK
    # SUBSCRIBE test/#
    sub = b"\x00\x01" + _str(b"test/#") + b"\x00"
    c.sendall(bytes([0x82]) + mb._encode_len(len(sub)) + sub)
    assert c.recv(8)[0] >> 4 == mb.SUBACK

    # a publish (as /api/mqtt/publish would do) must reach the subscriber
    broker.publish("test/temp", b"23.5")
    hdr = c.recv(1)
    assert hdr[0] >> 4 == mb.PUBLISH
    length = mb._read_len(c)
    body = mb._recv_exact(c, length)
    tlen = int.from_bytes(body[0:2], "big")
    assert body[2 : 2 + tlen] == b"test/temp"
    assert body[2 + tlen :] == b"23.5"
    assert broker.recent[-1] == {"topic": "test/temp", "payload": "23.5"}
    c.close()
