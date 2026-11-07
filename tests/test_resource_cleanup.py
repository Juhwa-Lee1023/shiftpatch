"""Who closes what. Each test checks the resource itself (socket fd, error
body, thread) rather than only that no exception was raised. Background:
unittest runs printed ResourceWarnings for HTTPError bodies and for the fake
Switch's listening socket; a trace showed the owners (test helper, fixture),
and the same patterns in production code are covered here too."""
import gc
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from unittest.mock import patch

import harness  # noqa: F401  (sys.path, AI off)
from fake_switch import FakeSwitch
from harness import MAPPING, ROWS, Base
from test_switch_contract import ROOM, USERS, wait

from shiftpatch import roster
from shiftpatch.interpret import Interpreter
from shiftpatch.outbox import Dispatcher
from shiftpatch.server import App
from shiftpatch.switch_bridge import SwitchBridge, SwitchConfig
from shiftpatch.wsclient import HandshakeError, WebSocket

APP_DIR = Path(__file__).resolve().parent.parent
REAL_URLOPEN = urllib.request.urlopen
REAL_CREATE = socket.create_connection


def resource_warnings(fn):
    """Run fn, collect garbage, return (result, ResourceWarnings seen)."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", ResourceWarning)
        out = fn()
        gc.collect()
    return out, [str(w.message) for w in seen if issubclass(w.category, ResourceWarning)]


def recording_urlopen(errors):
    def opener(*a, **k):
        try:
            return REAL_URLOPEN(*a, **k)
        except urllib.error.HTTPError as e:
            errors.append(e)
            raise
    return opener


def recording_connect(socks):
    def create(*a, **k):
        s = REAL_CREATE(*a, **k)
        socks.append(s)
        return s
    return create


class OneShotServer:
    """Accepts one TCP connection, reads the request head, answers with
    `reply` (or closes at once when None), then waits for the client."""

    def __init__(self, reply):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.reply = reply
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            conn.settimeout(5)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            if self.reply is None:
                return
            conn.sendall(self.reply)
            try:
                while conn.recv(4096):
                    pass
            except OSError:
                pass

    def close(self):
        self.sock.close()
        self.t.join(5)


class WebSocketHandshakeFailureClosesSocket(unittest.TestCase):
    def attempt(self, url):
        socks = []
        with patch("socket.create_connection", recording_connect(socks)):
            with self.assertRaises(HandshakeError) as cm:
                WebSocket.connect(url, {"Authorization": "Bearer x"}, timeout=5)
        self.assertEqual(len(socks), 1)
        self.assertEqual(socks[0].fileno(), -1, "socket left open after a failed handshake")
        return cm.exception

    def test_refused_upgrade(self):
        fake = FakeSwitch(room_id=ROOM)
        try:                                   # unknown agent id: plain HTTP 404, no upgrade
            e = self.attempt(fake.url.replace("http://", "ws://") + "/agents/nobody/connection/ws?connection_id=c")
        finally:
            fake.close()
        self.assertEqual(e.status, 404)

    def test_wrong_accept_header(self):
        srv = OneShotServer(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                            b"Sec-WebSocket-Accept: not-the-right-value\r\n\r\n")
        try:
            e = self.attempt(f"ws://127.0.0.1:{srv.port}/x")
        finally:
            srv.close()
        self.assertIn("Accept", str(e.body))

    def test_server_closes_during_handshake(self):
        srv = OneShotServer(None)
        try:
            e = self.attempt(f"ws://127.0.0.1:{srv.port}/x")
        finally:
            srv.close()
        self.assertEqual(e.status, 0)


class HttpErrorBodiesAreClosed(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSwitch(room_id=ROOM)

    def tearDown(self):
        self.fake.close()

    def test_bridge_post_reply_failure_closes_error_body(self):
        cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="wrong-key", room_id=ROOM)
        bridge = SwitchBridge(_store(self), None, cfg)
        errors = []
        with patch("urllib.request.urlopen", recording_urlopen(errors)):
            def send():
                with self.assertRaises(RuntimeError) as cm:
                    bridge.post_reply("hello")
                return str(cm.exception)
            msg, warned = resource_warnings(send)
        self.assertEqual(msg, "post_message HTTP 401")
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].fp.closed, "HTTPError body not closed")
        self.assertEqual(warned, [])

    def test_manage_post_failure_closes_error_body(self):
        spec = importlib.util.spec_from_file_location("manage_under_test", APP_DIR / "manage.py")
        manage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manage)
        errors = []
        with patch("urllib.request.urlopen", recording_urlopen(errors)):
            (code, body), warned = resource_warnings(
                lambda: manage.post(self.fake.url + "/agents/agent-1/message", {"room_id": ROOM, "content": "x"}, "wrong"))
        self.assertEqual(code, 401)
        self.assertIn("unauthorized", body["error"])
        self.assertTrue(errors[0].fp.closed)
        self.assertEqual(warned, [])


class FakeSwitchFixtureCloses(unittest.TestCase):
    def test_close_releases_listening_socket(self):
        fake = FakeSwitch(room_id=ROOM)
        listener, port = fake.httpd.socket, fake.port
        fake.close()
        self.assertEqual(listener.fileno(), -1)
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=2).close()


def _store(test):
    from shiftpatch.db import Store
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Store(Path(tmp.name) / "t.db")


class ShutdownJoinsThreads(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeSwitch(room_id=ROOM)
        self.addCleanup(self.fake.close)
        roster.create_room(self.store, ROOM, "switch", "switch")
        roster.import_switch_links(self.store, ROOM, USERS)
        roster.import_roster(self.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")
        self.cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="test-key", room_id=ROOM)

    def test_bridge_stop_closes_socket_and_joins(self):
        bridge = SwitchBridge(self.store, self.agent, self.cfg)
        bridge.start()
        self.assertTrue(wait(lambda: bridge.state == "connected"))
        ws, threads = bridge._ws, list(bridge._threads)
        self.assertTrue(bridge.stop())
        self.assertEqual(ws.sock.fileno(), -1)
        self.assertEqual([t.name for t in threads if t.is_alive()], [])

    def test_stop_wakes_a_reader_blocked_without_read_timeout(self):
        bridge = SwitchBridge(self.store, self.agent, self.cfg, read_timeout=None)
        bridge.start()
        self.assertTrue(wait(lambda: bridge.state == "connected"))
        self.fake.silent = True                      # reader now sits in recv() with no deadline
        time.sleep(0.3)
        t0 = time.monotonic()
        self.assertTrue(bridge.stop(timeout=3))
        self.assertLess(time.monotonic() - t0, 2.5)

    def test_dispatcher_stop_joins_loop(self):
        d = Dispatcher(self.store, {})
        d.start()
        t = d._thread
        self.assertTrue(d.stop())
        self.assertFalse(t.is_alive())

    def test_app_close_stops_everything(self):
        cfg = self.dir / "switch.local.json"
        cfg.write_text(json.dumps({"base_url": self.fake.url, "agent_id": "agent-1", "api_key": "test-key", "room_id": ROOM}))
        app = App(self.dir / "data", 0, ai=Interpreter(enabled=False), switch_config=cfg)
        app.start_background()
        self.assertTrue(wait(lambda: app.bridge.state == "connected"))
        threads = list(app.bridge._threads) + [app.dispatcher._thread]
        self.assertTrue(app.close())
        self.assertEqual([t.name for t in threads if t.is_alive()], [])


class ProcessShutdown(unittest.TestCase):
    """The README's `python3 run.py`, connected to the fake Switch, stopped
    with SIGTERM: exit 0, a 'stopped' line, and nothing on stderr but the
    request log, even with ResourceWarnings forced on."""

    def test_sigterm_with_switch_connected(self):
        fake = FakeSwitch(room_id=ROOM)
        self.addCleanup(fake.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "switch.local.json"
        cfg.write_text(json.dumps({"base_url": fake.url, "agent_id": "agent-1", "api_key": "test-key", "room_id": ROOM}))
        with socket.create_server(("127.0.0.1", 0)) as s:
            port = s.getsockname()[1]
        env = {**os.environ, "SHIFTPATCH_AI": "off", "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen([sys.executable, "-X", "dev", "-W", "always::ResourceWarning", str(APP_DIR / "run.py"),
                              "--port", str(port), "--data", str(Path(tmp.name) / "data"), "--switch-config", str(cfg)],
                             cwd=APP_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            first = p.stdout.readline()
            self.assertIn(f"ShiftPatch on http://127.0.0.1:{port}/", first)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                self.assertEqual(r.status, 200)
            self.assertTrue(wait(lambda: len(fake.opens) >= 1, 8), "app never connected to the fake Switch")
            p.send_signal(signal.SIGTERM)
            out, err = p.communicate(timeout=20)
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("ShiftPatch stopped", out)
        self.assertNotIn("still running", out)
        # The request log ("GET /") goes to stderr; anything else is a warning or traceback.
        self.assertEqual([ln for ln in err.splitlines() if ln.strip() and ln != "GET /"], [])


if __name__ == "__main__":
    unittest.main()
