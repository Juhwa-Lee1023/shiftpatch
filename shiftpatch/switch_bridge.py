"""Switch agent-protocol adapter (WebSocket transport; SSE is deprecated).

Built only from the published contract (docs.switchagents.ai, fetched
2026-11-07; the fetched copies are not part of this package):
  GET  /health                                   public probe
  WS   /agents/{id}/connection/ws?connection_id=…&rooms=…&filter=…&start_from=…&expected_generation=…
       Authorization: Bearer <agent API key>
       first frame connection_state; ping every 2 s → {"type":"pong","cursor":n}
       domain frames {"event","data":{type,room_id,payload,sequence},"id"}
       control frames gap / evicted / subscription_changed / room_released / refused
  POST /agents/{id}/message {room_id, content}   post a reply, no connection needed

The actor of every state change is payload.sender as delivered by Switch,
mapped through links the manager imported locally. Nothing from the web UI
or the message body can choose it.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from .agent import TrustedEnvelope
from .wsclient import HandshakeError, WebSocket, WsClosed

CONTROL = {"connection_state", "gap", "evicted", "subscription_changed", "room_released", "ping", "refused"}
DOMAIN = {"message", "command", "room_join"}
RECONNECT_EVICTIONS = {"heartbeat_lapsed", "no_stream", "unfenced", "connection_error"}
FINAL_CLOSE = {4400, 4401, 4403, 4409}
HANDLER_ATTEMPTS = 5
MARKER_KEYS = {"com.switch.auto_reply": "auto_reply", "com.switch.admin": "admin"}
# Switch pings every 2 s and drops a client that misses 6 s of pongs. If we
# hear nothing at all for this long the socket is treated as dead (half-open
# TCP, paused VM) and we reconnect from the processed cursor.
READ_TIMEOUT_S = 15.0


class BadFrame(Exception):
    """A frame we cannot trust: not JSON, not an object, or a sequence/cursor
    that is not a non-negative integer. The connection is dropped and reopened
    from the processed cursor; the frame never reaches the pipeline."""


def _seq(value, what):
    if isinstance(value, bool):
        raise BadFrame(f"{what} is not an integer")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise BadFrame(f"{what} is not an integer") from None
    if n < 0 or (isinstance(value, float) and n != value):
        raise BadFrame(f"{what} is not a non-negative integer")
    return n


def parse_frame(raw: str) -> dict:
    try:
        frame = json.loads(raw)
    except ValueError:
        raise BadFrame("not JSON") from None
    if not isinstance(frame, dict):
        raise BadFrame("not a JSON object")
    kind = frame.get("event") or frame.get("type")
    if kind in DOMAIN:
        if "id" not in frame:
            raise BadFrame("domain frame without id")
        frame["id"] = _seq(frame["id"], "frame id")
        if frame.get("data") is not None and not isinstance(frame["data"], dict):
            raise BadFrame("domain frame data is not an object")
    fields = frame.get("data") if isinstance(frame.get("data"), dict) else frame
    if kind == "connection_state" and fields.get("cursor") is not None:
        fields["cursor"] = _seq(fields["cursor"], "cursor")
    if kind == "gap" and fields.get("resumed_at") is not None:
        fields["resumed_at"] = _seq(fields["resumed_at"], "resumed_at")
    return frame


@dataclass
class SwitchConfig:
    base_url: str
    agent_id: str
    api_key: str
    room_id: str
    agent_name: str = "shiftpatch"

    @classmethod
    def load(cls, path: Path | None = None):
        """Environment first, then a local 0600 JSON file. Returns None when
        incomplete. The key is never logged or returned to the UI."""
        data = {}
        if path and path.exists():
            data = json.loads(path.read_text())
        get = lambda k, env: os.environ.get(env) or data.get(k)  # noqa: E731
        vals = {"base_url": get("base_url", "SHIFTPATCH_SWITCH_URL"), "agent_id": get("agent_id", "SHIFTPATCH_SWITCH_AGENT_ID"),
                "api_key": get("api_key", "SHIFTPATCH_SWITCH_API_KEY"), "room_id": get("room_id", "SHIFTPATCH_SWITCH_ROOM_ID"),
                "agent_name": get("agent_name", "SHIFTPATCH_SWITCH_AGENT_NAME") or "shiftpatch"}
        if not all(vals[k] for k in ("base_url", "agent_id", "api_key", "room_id")):
            return None, {k: bool(vals[k]) for k in ("base_url", "agent_id", "api_key", "room_id")}
        vals["base_url"] = vals["base_url"].rstrip("/")
        return cls(**vals), {k: True for k in ("base_url", "agent_id", "api_key", "room_id")}


def _markers(payload: dict) -> frozenset:
    found = set()
    for container in (payload, payload.get("content") if isinstance(payload.get("content"), dict) else {}):
        for k, v in MARKER_KEYS.items():
            if k in container:
                found.add(v)
    return frozenset(found)


class SwitchBridge:
    def __init__(self, store, agent, cfg: SwitchConfig, ping_answer=True, clock=lambda: int(time.time() * 1000),
                 read_timeout=READ_TIMEOUT_S):
        self.store, self.agent, self.cfg, self.clock = store, agent, cfg, clock
        self.ping_answer = ping_answer
        self.read_timeout = read_timeout
        self.state = "idle"
        self.detail = None
        self.halted = None
        self.generation = None
        self.rooms = []
        self.cursor = int(self._kv("cursor") or 0)
        self.connection_id = self._kv("connection_id") or str(uuid.uuid4())
        self._kv_set("connection_id", self.connection_id)
        self.generation = int(self._kv("generation")) if self._kv("generation") else None
        self.counters = {"frames": 0, "pings": 0, "pongs": 0, "messages": 0, "addressed": 0, "gaps": 0, "reconnects": 0,
                         "bad_frames": 0, "read_timeouts": 0}
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._ws = None
        self._gap_note = None
        self._threads = []

    # ------------------------------------------------------------ persistence
    def _kv(self, key):
        with self.store.snapshot() as c:
            r = c.execute("SELECT value FROM bridge_state WHERE key=?", (f"switch:{self.cfg.room_id}:{key}",)).fetchone()
        return r[0] if r else None

    def _kv_set(self, key, value):
        with self.store.tx() as c:
            c.execute("INSERT INTO bridge_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (f"switch:{self.cfg.room_id}:{key}", str(value)))

    # ------------------------------------------------------------ HTTP
    def _http(self, method, path, body=None, auth=True, timeout=10):
        req = urllib.request.Request(self.cfg.base_url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self.cfg.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            with e:                       # the error owns the response body and its socket
                return e.code, e.read().decode("utf-8", "replace")[:300]

    def probe(self):
        try:
            status, _ = self._http("GET", "/health", auth=False, timeout=5)
            return {"ok": status == 200, "status": status}
        except (OSError, urllib.error.URLError) as e:
            return {"ok": False, "error": type(e).__name__}

    def post_reply(self, content: str):
        status, body = self._http("POST", f"/agents/{self.cfg.agent_id}/message",
                                  {"room_id": self.cfg.room_id, "content": content})
        if not 200 <= status < 300:
            raise RuntimeError(f"post_message HTTP {status}")
        return status

    # ------------------------------------------------------------ connection
    def ws_url(self):
        q = {"connection_id": self.connection_id, "rooms": self.cfg.room_id, "filter": "addressed",
             "start_from": str(self.cursor) if self.cursor else "head", "client": "shiftpatch", "client_version": "0.1.0"}
        if self.generation is not None:
            q["expected_generation"] = str(self.generation)
        base = self.cfg.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{base}/agents/{self.cfg.agent_id}/connection/ws?{urlencode(q)}"

    def start(self):
        self._stop.clear()
        for target in (self._run, self._work):
            t = threading.Thread(target=target, daemon=True, name=f"switch-{target.__name__}")
            t.start()
            self._threads.append(t)

    def stop(self, timeout=5.0) -> bool:
        """Stop both threads and wait for them. Returns False if one is still
        running after `timeout` (e.g. a handler retry or a slow connect);
        it exits on its own once that call returns. The reader thread owns
        the socket and closes it; this only interrupts it."""
        self._stop.set()
        self._q.put(None)
        ws = self._ws
        if ws is not None:
            ws.interrupt()
        end = time.monotonic() + timeout
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(max(0.0, end - time.monotonic()))
        self._threads = [t for t in self._threads if t.is_alive()]
        return not self._threads

    def _run(self):
        """Reader thread. Every way out of _read_loop ends in a state other
        than "connected": reconnecting, stopped, error or halted."""
        backoff = 1
        while not self._stop.is_set():
            self.state = "connecting"
            try:
                self._ws = WebSocket.connect(self.ws_url(), {"Authorization": f"Bearer {self.cfg.api_key}"},
                                             read_timeout=self.read_timeout)
                backoff = 1
                self.state = "connected"
                self._read_loop()
            except HandshakeError as e:
                self.state, self.detail = "error", f"handshake HTTP {e.status}"
                if e.status in (401, 403, 404):
                    return
            except WsClosed as e:
                self.detail = f"closed {e.code} {e.reason}".strip()
                if e.code in FINAL_CLOSE:
                    self.state = "stopped"
                    return
                self.state = "reconnecting"
            except BadFrame as e:
                self.counters["bad_frames"] += 1
                self.state, self.detail = "reconnecting", f"bad frame: {e}; cursor kept at {self.cursor}"
            except TimeoutError:
                self.counters["read_timeouts"] += 1
                self.state, self.detail = "reconnecting", f"no frame for {self.read_timeout:g} s; reconnecting"
            except OSError as e:
                self.state, self.detail = "reconnecting", type(e).__name__
            except Exception as e:  # noqa: BLE001 - never leave a dead reader marked connected
                self.state, self.detail = "reconnecting", f"reader {type(e).__name__}"
            finally:
                ws, self._ws = self._ws, None     # this thread owns the socket: close it here
                if ws is not None:
                    ws.close()
                if self.state == "connected":
                    self.state = "reconnecting"
            if self.halted:
                self.state = "halted"
                return
            if self.state == "stopped":
                return
            self.counters["reconnects"] += 1
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30)

    def _read_loop(self):
        while not self._stop.is_set():
            frame = parse_frame(self._ws.recv())
            self.counters["frames"] += 1
            kind = frame.get("event") or frame.get("type")
            if kind == "ping":
                # Answer before anything else: liveness lapses after 6 s.
                self.counters["pings"] += 1
                if self.ping_answer:
                    self._ws.send_text(json.dumps({"type": "pong", "cursor": self.cursor}))
                    self.counters["pongs"] += 1
                continue
            if kind in DOMAIN and "id" in frame:
                self._q.put(frame)
                continue
            fields = frame.get("data") if isinstance(frame.get("data"), dict) else frame
            if kind == "connection_state":
                self.generation = fields.get("generation")
                self.rooms = fields.get("rooms") or []
                if fields.get("cursor") is not None:
                    self.cursor = max(self.cursor, fields["cursor"]) if self.cursor else fields["cursor"]
                    # Persist the head position too: without it a restart after a failed
                    # first message would open at "head" and skip that message.
                    self._kv_set("cursor", self.cursor)
                self._kv_set("generation", self.generation)
                self.detail = None if self.cfg.room_id in self.rooms else "room_not_covered"
            elif kind == "gap":
                self.counters["gaps"] += 1
                self.cursor = fields.get("resumed_at") or self.cursor
                self._kv_set("cursor", self.cursor)
                self._gap_note = ("(연결이 끊긴 동안 놓친 메시지가 있을 수 있습니다. 필요한 내용은 다시 보내 주세요. / "
                                  "Messages may have been missed while disconnected; please resend anything important.)")
            elif kind == "evicted":
                code = fields.get("code")
                self.detail = f"evicted {code}"
                if code in RECONNECT_EVICTIONS:
                    raise WsClosed(None, f"evicted {code}")
                self.state = "stopped"
                self._stop.set()
                raise WsClosed(4409, f"evicted {code}")
            elif kind == "refused":
                self.detail = f"refused {fields.get('status')}"
            elif kind == "subscription_changed":
                self.rooms = fields.get("rooms") or []

    def _work(self):
        while not self._stop.is_set():
            frame = self._q.get()
            if frame is None:
                return
            seq = int(frame["id"])
            if seq <= self.cursor:
                continue
            data = frame.get("data") or {}
            for attempt in range(HANDLER_ATTEMPTS):
                try:
                    self._handle_domain(data)
                    break
                except Exception as e:  # retriable: keep cursor, retry
                    error = type(e).__name__
                    self.detail = f"handler {error}"
                    time.sleep(0.2 * (attempt + 1))
            else:
                self._halt(seq, error)
                return
            self.cursor = seq
            self._kv_set("cursor", seq)

    def _halt(self, seq, error):
        """Fail closed. Taking any later sequence would move the persisted
        cursor past the failed one and Switch would never replay it, so stop
        consuming and leave the cursor where it is. Restarting ShiftPatch
        resumes from that cursor and retries the same message."""
        self.halted = {"sequence": seq, "error": error, "cursor": self.cursor}
        self.state = "halted"
        self._stop.set()
        ws = self._ws
        if ws is not None:
            ws.interrupt()                    # the reader closes it on its way out

    def _handle_domain(self, data):
        if data.get("type") != "message" or data.get("room_id") != self.cfg.room_id:
            return
        p = data.get("payload") or {}
        self.counters["messages"] += 1
        if not p.get("addressed"):
            return
        self.counters["addressed"] += 1
        if (p.get("sender_name") or "").lower() == self.cfg.agent_name.lower():
            return
        env = TrustedEnvelope(source="switch", room_id=data["room_id"], message_id=str(p.get("message_id")),
                              sender=str(p.get("sender")), sender_name=str(p.get("sender_name") or ""),
                              body=str(p.get("body") or ""), created_ms=int(p.get("timestamp") or 0),
                              received_ms=self.clock(), addressed=True, markers=_markers(p), note=self._gap_note)
        self._gap_note = None
        self.agent.handle(env)

    def status(self):
        if self.halted:
            h = self.halted
            state, detail = "halted", (f"message sequence {h['sequence']} failed {HANDLER_ATTEMPTS} times ({h['error']}); "
                                       f"cursor kept at {h['cursor']}, nothing later consumed. Restart ShiftPatch to retry it.")
        else:
            state, detail = self.state, self.detail
        return {"state": state, "detail": detail, "room_id": self.cfg.room_id, "base_url": self.cfg.base_url,
                "agent_id": self.cfg.agent_id, "rooms": self.rooms, "cursor": self.cursor, "generation": self.generation,
                "connection_id": self.connection_id, "counters": dict(self.counters)}
