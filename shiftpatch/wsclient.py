"""Minimal RFC 6455 WebSocket client (stdlib only). Text frames, ping/pong,
close and fragmentation. Enough for the Switch agent connection, which
sends one JSON text message per frame and needs an Authorization header
(browsers cannot set it, so this runs server-side)."""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WsClosed(Exception):
    def __init__(self, code: int | None, reason: str = ""):
        super().__init__(f"closed {code} {reason}")
        self.code, self.reason = code, reason


class HandshakeError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"handshake status {status}")
        self.status, self.body = status, body


class WebSocket:
    def __init__(self, sock):
        self.sock = sock
        self._send_lock = threading.Lock()
        self._buf = b""

    @classmethod
    def connect(cls, url: str, headers: dict, timeout: float = 10.0):
        u = urlsplit(url)
        secure = u.scheme == "wss"
        port = u.port or (443 if secure else 80)
        raw = socket.create_connection((u.hostname, port), timeout=timeout)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname) if secure else raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        host = u.hostname + (f":{u.port}" if u.port else "")
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                raise HandshakeError(0, "connection closed during handshake")
            resp += chunk
            if len(resp) > 65536:
                raise HandshakeError(0, "handshake too large")
        head, _, rest = resp.partition(b"\r\n\r\n")
        status_line, *hdrs = head.decode("latin-1").split("\r\n")
        status = int(status_line.split(" ")[1])
        h = {k.strip().lower(): v.strip() for k, v in (x.split(":", 1) for x in hdrs if ":" in x)}
        if status != 101:
            raise HandshakeError(status, rest.decode("utf-8", "replace")[:300])
        expect = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if h.get("sec-websocket-accept") != expect:
            raise HandshakeError(status, "bad Sec-WebSocket-Accept")
        ws = cls(sock)
        ws._buf = rest
        sock.settimeout(None)
        return ws

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WsClosed(1006, "eof")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _frame(self):
        b1, b2 = self._read(2)
        fin, opcode = b1 & 0x80, b1 & 0x0F
        masked, ln = b2 & 0x80, b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        if ln > 16 * 1024 * 1024:
            raise WsClosed(1009, "frame too large")
        mask = self._read(4) if masked else None
        data = self._read(ln)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return bool(fin), opcode, data

    def recv(self) -> str:
        """Next text message. Answers protocol-level pings itself."""
        parts, op0 = [], None
        while True:
            fin, op, data = self._frame()
            if op == 0x8:
                code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else None
                try:
                    self._send(0x8, data[:2])
                except OSError:
                    pass
                raise WsClosed(code, data[2:].decode("utf-8", "replace"))
            if op == 0x9:
                self._send(0xA, data)
                continue
            if op == 0xA:
                continue
            if op in (0x1, 0x2):
                op0, parts = op, [data]
            elif op == 0x0:
                parts.append(data)
            if fin and op0 is not None:
                return b"".join(parts).decode("utf-8")

    def _send(self, opcode: int, payload: bytes):
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self.sock.sendall(head + mask + body)

    def send_text(self, text: str):
        self._send(0x1, text.encode("utf-8"))

    def close(self, code: int = 1000):
        try:
            self._send(0x8, struct.pack(">H", code))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
