"""CONTRACT DOUBLE — not Switch. A tiny local server that speaks the parts
of the documented agent protocol ShiftPatch uses (docs.switchagents.ai,
fetched 2026-11-07; the fetched copies are not part of this package), so
the adapter can be exercised without Docker. Passing these tests says the
adapter matches our reading of the docs; it says nothing about a live
Switch deployment."""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _send(sock, opcode, payload: bytes):
    n = len(payload)
    head = bytes([0x80 | opcode])
    head += bytes([n]) if n < 126 else (bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n))
    sock.sendall(head + payload)


def _recv_frame(sock):
    def read(n):
        b = b""
        while len(b) < n:
            c = sock.recv(n - len(b))
            if not c:
                raise ConnectionError("eof")
            b += c
        return b
    b1, b2 = read(2)
    ln = b2 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", read(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", read(8))[0]
    mask = read(4) if b2 & 0x80 else b"\0\0\0\0"
    data = bytes(x ^ mask[i % 4] for i, x in enumerate(read(ln)))
    return b1 & 0x0F, data


class FakeSwitch:
    def __init__(self, agent_id="agent-1", api_key="test-key", room_id="!room:localhost", ping_interval=0.2):
        self.agent_id, self.api_key, self.room_id, self.ping_interval = agent_id, api_key, room_id, ping_interval
        self.posted = []          # (room_id, content)
        self.opens = []           # query dicts of each socket open
        self.pongs = []           # cursors seen in pongs
        self.queue = []           # frames to push to the live socket
        self.seq = 0
        self.generation = 0
        self.live = None
        self.silent = False       # True: keep the socket open but send nothing (half-open stand-in)
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlsplit(self.path)
                if u.path == "/health":
                    body = b'{"status":"ok"}'
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if u.path == f"/agents/{fake.agent_id}/connection/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                    return fake._ws(self, parse_qs(u.query))
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == f"/agents/{fake.agent_id}/message" and self.headers.get("Authorization") == f"Bearer {fake.api_key}":
                    fake.posted.append((body.get("room_id"), body.get("content")))
                    out = b'{"ok":true}'
                    self.send_response(200)
                else:
                    out = b'{"error":"unauthorized"}'
                    self.send_response(401)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._serve = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._serve.start()

    def close(self):
        """Drop the live socket, stop accepting, and close the listening
        socket. shutdown() alone leaves the listener open until GC."""
        self.drop(1001)
        self.httpd.shutdown()
        self.httpd.server_close()
        self._serve.join(5)

    # --------------------------------------------------------------- socket
    def _ws(self, h, q):
        key = h.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        h.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        h.wfile.flush()
        sock = h.connection
        q1 = {k: v[0] for k, v in q.items()}
        self.opens.append(q1)
        if h.headers.get("Authorization") != f"Bearer {self.api_key}":
            _send(sock, 0x8, struct.pack(">H", 4401))
            return
        if "connection_id" not in q1:
            _send(sock, 0x8, struct.pack(">H", 4400))
            return
        self.generation += 1
        _send(sock, 0x1, json.dumps({"type": "connection_state", "connection_id": q1["connection_id"], "agent_id": self.agent_id,
                                     "generation": self.generation, "scope": "single", "filter": q1.get("filter", "all"),
                                     "rooms": [r for r in q1.get("rooms", "").split(",") if r],
                                     "cursor": int(q1["start_from"]) if q1.get("start_from", "head").isdigit() else self.seq,
                                     "heartbeat_interval_seconds": self.ping_interval}).encode())
        self.live = sock
        stop = threading.Event()

        def reader():
            try:
                while not stop.is_set():
                    op, data = _recv_frame(sock)
                    if op == 0x8:
                        break
                    if op == 0x1:
                        msg = json.loads(data)
                        if msg.get("type") == "pong":
                            self.pongs.append(msg.get("cursor"))
            except (OSError, ConnectionError, ValueError):
                pass
            stop.set()
        threading.Thread(target=reader, daemon=True).start()
        last_ping = 0
        try:
            while not stop.is_set() and self.live is sock:
                if self.silent:
                    time.sleep(0.02)
                    continue
                with self.lock:
                    frames, self.queue = self.queue, []
                for f in frames:
                    if f == "__close__":
                        raise ConnectionAbortedError
                    if isinstance(f, tuple) and f[0] == "__raw__":
                        _send(sock, 0x1, f[1].encode())
                        continue
                    _send(sock, 0x1, json.dumps(f).encode())
                if time.monotonic() - last_ping > self.ping_interval:
                    _send(sock, 0x1, b'{"type":"ping"}')
                    last_ping = time.monotonic()
                time.sleep(0.02)
        except (OSError, ConnectionAbortedError):
            pass
        stop.set()

    # --------------------------------------------------------------- drivers
    def push_message(self, sender, body, addressed=True, room_id=None, message_id=None, timestamp=None, sender_name="", extra=None, seq=None):
        if seq is None:
            self.seq += 1
            seq = self.seq
        payload = {"addressed": addressed, "sender": sender, "sender_name": sender_name, "message_id": message_id or f"$ev{seq}",
                   "body": body, "timestamp": timestamp or int(time.time() * 1000), "thread_id": None, "attachments": []}
        payload.update(extra or {})
        frame = {"event": "message", "data": {"type": "message", "room_id": room_id or self.room_id, "bridge_id": None,
                                              "channel_type": "channel_public", "payload": payload, "sequence": seq}, "id": seq}
        with self.lock:
            self.queue.append(frame)
        return frame

    def push_control(self, frame):
        with self.lock:
            self.queue.append(frame)

    def push_raw(self, text: str):
        """Send text exactly as given (e.g. malformed JSON). Synthetic fault,
        not something a real Switch server was observed to send."""
        with self.lock:
            self.queue.append(("__raw__", text))

    def drop(self, code=1012):
        sock, self.live = self.live, None
        if sock is not None:
            try:
                _send(sock, 0x8, struct.pack(">H", code))
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
