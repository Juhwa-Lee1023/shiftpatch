"""Real HTTP against an in-process server on an ephemeral port: access
scope (B05), local token, demo-only actor picker, roster flow via HTTP."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SHIFTPATCH_AI", "off")

from shiftpatch.interpret import Interpreter  # noqa: E402
from shiftpatch.server import App, make_handler  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent.parent / "fixtures" / "roster_sample.csv").read_bytes()


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = srv.server_address[1]
        self.app = App(Path(self.tmp.name), self.port, ai=Interpreter(enabled=False),
                       switch_config=Path(self.tmp.name) / "none.json")
        srv.RequestHandlerClass = make_handler(self.app)
        self.srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        try:
            self.srv.shutdown()
            self.srv.server_close()
            self.assertTrue(self.app.close())
        finally:
            self.tmp.cleanup()

    def req(self, method, path, body=None, token=True, host=None, ctype="application/json", origin=None):
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, method=method)
        if token:
            r.add_header("X-ShiftPatch-Token", self.app.token)
        if host:
            r.add_header("Host", host)
        if origin:
            r.add_header("Origin", origin)
        r.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def j(self, *a, **k):
        code, body = self.req(*a, **k)
        return code, json.loads(body or b"{}")

    def import_sample(self):
        code, d = self.j("POST", "/api/roster/csv?room=local-demo", SAMPLE, ctype="text/csv")
        self.assertEqual(code, 200)
        names = sorted({r["name"] for r in d["rows"]})
        return self.j("POST", f"/api/roster/draft/{d['draft_id']}/approve",
                      {"rows": d["rows"], "mapping": d["mapping"], "confirmed": names, "approved": True})

    def test_index_injects_token_and_sets_csp(self):
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(self.app.token.encode(), body)

    def test_b05_wrong_host_rejected(self):
        code, d = self.j("GET", "/api/state", host="evil.example:80")
        self.assertEqual((code, d["error"]), (403, "HOST_NOT_ALLOWED"))

    def test_write_requires_token_and_same_origin(self):
        code, d = self.j("POST", "/api/demo/reset", {}, token=False)
        self.assertEqual((code, d["error"]), (403, "MISSING_LOCAL_TOKEN"))
        code, d = self.j("POST", "/api/demo/reset", {}, origin="http://evil.example")
        self.assertEqual((code, d["error"]), (403, "ORIGIN_NOT_ALLOWED"))

    def test_unknown_room_404(self):
        code, d = self.j("GET", "/api/state?room=nope")
        self.assertEqual(code, 404)

    def test_import_needs_explicit_approval_over_http(self):
        code, d = self.j("POST", "/api/roster/csv?room=local-demo", SAMPLE, ctype="text/csv")
        names = sorted({r["name"] for r in d["rows"]})
        code, r = self.j("POST", f"/api/roster/draft/{d['draft_id']}/approve",
                         {"rows": d["rows"], "mapping": d["mapping"], "confirmed": names, "approved": "yes"})
        self.assertEqual((code, r["error"]), (409, "MANAGER_APPROVAL_REQUIRED"))
        code, r = self.j("POST", f"/api/roster/draft/{d['draft_id']}/approve",
                         {"rows": d["rows"], "mapping": d["mapping"], "confirmed": [], "approved": True})
        self.assertEqual((code, r["error"]), (409, "DRAFT_HAS_BLOCKING_ISSUES"))
        code, r = self.j("POST", f"/api/roster/draft/{d['draft_id']}/approve",
                         {"rows": d["rows"], "mapping": {**d["mapping"], "지안": "evil"}, "confirmed": names, "approved": True})
        self.assertEqual(code, 409)
        code, s = self.j("GET", "/api/state")
        self.assertEqual(s["room"]["roster_version"], 0)

    def test_demo_flow_and_export_download(self):
        self.assertEqual(self.import_sample()[0], 200)
        for actor, body in (("minsu", "@ShiftPatch 불가 2026-11-09 13:00-17:00"), ("taeo", "@ShiftPatch 가능 13-17")):
            code, r = self.j("POST", "/api/demo/message", {"actor": actor, "body": body})
            self.assertEqual(code, 200, r)
        code, s = self.j("GET", "/api/state")
        part = s["proposal"]["parts"][0]["part_id"]
        self.j("POST", "/api/demo/message", {"actor": "taeo", "body": f"@ShiftPatch 수락 {part}"})
        self.j("POST", "/api/demo/message", {"actor": "seoyeon", "body": f"@ShiftPatch 확정 {s['proposal']['proposal_id']}"})
        code, e = self.j("POST", "/api/export", {"kind": "csv"})
        self.assertTrue(e["ok"])
        code, body = self.req("GET", f"/exports/{e['file']}")
        self.assertEqual(code, 200)
        self.assertIn("대체 확정".encode(), body)
        code, _ = self.req("GET", "/exports/../shiftpatch.db")
        self.assertEqual(code, 404)
        code, _ = self.req("GET", "/exports/not-recorded.csv")
        self.assertEqual(code, 404)
        code, s = self.j("GET", "/api/state")
        self.assertTrue(any(m["kind"] == "agent" for m in s["transcript"]))
        self.assertEqual(s["switch"]["state"], "BLOCKED")

    def test_demo_actor_must_be_synthetic(self):
        self.import_sample()
        code, d = self.j("POST", "/api/demo/message", {"actor": "@switch-user-jian:localhost", "body": "@ShiftPatch 표"})
        self.assertEqual((code, d["error"]), (403, "LOCAL_DEMO_ONLY"))

    def test_upload_bounds_over_http(self):
        code, d = self.j("POST", "/api/roster/image?room=local-demo", b"GIF89a....", ctype="image/gif")
        self.assertEqual((code, d["error"]), (422, "UNSUPPORTED_TYPE"))
        code, d = self.j("POST", "/api/roster/csv?room=local-demo", b"x" * 70000, ctype="text/csv")
        self.assertEqual(code, 400)
