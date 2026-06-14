#!/usr/bin/env python3
"""A minimal embedded MQTT v3.1.1 broker (QoS 0) for the workbench.

Just enough to let a DUT and the test host exchange messages without installing
mosquitto: CONNECT/CONNACK, SUBSCRIBE/SUBACK, PUBLISH fan-out (with + and #
wildcards), PINGREQ/PINGRESP, DISCONNECT. QoS is treated as 0 (fire-and-forget).
Stdlib only. Not a hardened broker - no auth, no retained messages, no QoS 1/2.
"""

from __future__ import annotations

import socket
import threading
from collections import deque

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = (
    1,
    2,
    3,
    8,
    9,
    12,
    13,
    14,
)


def _encode_len(n):
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            return bytes(out)


def _read_len(sock):
    mult, value = 1, 0
    while True:
        b = sock.recv(1)
        if not b:
            return None
        value += (b[0] & 0x7F) * mult
        if not (b[0] & 0x80):
            return value
        mult *= 128


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def _topic_matches(filt, topic):
    fp, tp = filt.split("/"), topic.split("/")
    for i, f in enumerate(fp):
        if f == "#":
            return True
        if i >= len(tp):
            return False
        if f != "+" and f != tp[i]:
            return False
    return len(fp) == len(tp)


def _publish_packet(topic, payload):
    tb = topic.encode("utf-8")
    var = len(tb).to_bytes(2, "big") + tb + payload
    return bytes([PUBLISH << 4]) + _encode_len(len(var)) + var


class Broker:
    def __init__(self):
        self._subs = {}  # client socket -> set of topic filters
        self._lock = threading.Lock()
        self.recent = deque(maxlen=500)  # (topic, payload_str) seen

    def publish(self, topic, payload):
        """Fan a message out to matching subscribers (also used by the API)."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.recent.append({"topic": topic, "payload": payload.decode("utf-8", "replace")})
        pkt = _publish_packet(topic, payload)
        with self._lock:
            targets = [
                s for s, filts in self._subs.items() if any(_topic_matches(f, topic) for f in filts)
            ]
        for s in targets:
            try:
                s.sendall(pkt)
            except OSError:
                pass

    def serve(self, host, port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(8)
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        with self._lock:
            self._subs[conn] = set()
        try:
            while True:
                hdr = conn.recv(1)
                if not hdr:
                    break
                ptype = hdr[0] >> 4
                length = _read_len(conn)
                if length is None:
                    break
                body = _recv_exact(conn, length) if length else b""
                if body is None:
                    break
                if ptype == CONNECT:
                    conn.sendall(bytes([CONNACK << 4, 0x02, 0x00, 0x00]))
                elif ptype == PINGREQ:
                    conn.sendall(bytes([PINGRESP << 4, 0x00]))
                elif ptype == SUBSCRIBE:
                    self._handle_subscribe(conn, body)
                elif ptype == PUBLISH:
                    self._handle_publish(hdr[0], body)
                elif ptype == DISCONNECT:
                    break
        finally:
            with self._lock:
                self._subs.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass

    def _handle_subscribe(self, conn, body):
        pid = body[0:2]
        i, granted = 2, []
        while i + 2 <= len(body):
            tlen = int.from_bytes(body[i : i + 2], "big")
            i += 2
            topic = body[i : i + tlen].decode("utf-8", "replace")
            i += tlen
            i += 1  # requested QoS byte
            with self._lock:
                self._subs[conn].add(topic)
            granted.append(0)  # we grant QoS 0
        conn.sendall(bytes([SUBACK << 4]) + _encode_len(2 + len(granted)) + pid + bytes(granted))

    def _handle_publish(self, flags, body):
        qos = (flags >> 1) & 0x03
        tlen = int.from_bytes(body[0:2], "big")
        topic = body[2 : 2 + tlen].decode("utf-8", "replace")
        i = 2 + tlen
        if qos > 0:
            i += 2  # skip packet id (we don't ack QoS>0)
        self.publish(topic, body[i:])
