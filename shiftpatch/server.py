"""Local web app: coverage board, roster import (CSV or image), the local
synthetic demo room and Switch connection status. Binds 127.0.0.1 only.

Run: python3 -m shiftpatch.server --port 8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import engine, exporter, ocr, roster
from . import intervals as iv
from .agent import Agent
from .db import Store
from .interpret import Interpreter
from .local_demo import LocalDemoRoom
from .outbox import Dispatcher
from .switch_bridge import SwitchBridge, SwitchConfig

APP = Path(__file__).resolve().parent.parent
WEB = APP / "web"
MAX_JSON = 64 * 1024
MAX_UPLOAD = ocr.MAX_BYTES + 1024


class App:
    def __init__(self, data_dir: Path, port: int, ai: Interpreter | None = None, switch_config: Path | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.store = Store(self.data_dir / "shiftpatch.db")
        self.exports_dir = self.data_dir / "exports"
        self.token = secrets.token_urlsafe(24)
        self.ai = ai if ai is not None else Interpreter()
        self.agent = Agent(self.store, self.ai, exporter=self.export, board_url=f"http://127.0.0.1:{port}/#/board")
        self.local = LocalDemoRoom(self.store, self.agent)
        self.drafts = ocr.DraftStore()
        ocr.purge_stale_temp()
        roster.ensure_local_demo_room(self.store)
        cfg, self.switch_fields = SwitchConfig.load(switch_config)
        self.bridge = None
        senders = {"local_demo": self.local.deliver}
        if cfg is not None:
            roster.create_room(self.store, cfg.room_id, "switch", "Switch room")
            self.bridge = SwitchBridge(self.store, self.agent, cfg)
            senders["switch"] = lambda room_id, row: self.bridge.post_reply(row["body"])
        self.dispatcher = Dispatcher(self.store, senders)

    def start_background(self):
        self.dispatcher.start()
        if self.bridge is not None:
            self.bridge.start()

    def export(self, room_id, kind):
        with self.store.snapshot() as c:
            now = roster.room_now_ms(engine.room(c, room_id))  # demo room runs on its synthetic clock
        return exporter.export(self.store, room_id, kind, self.exports_dir, now_ms=now)

    # ---------------------------------------------------------------- views
    def state(self, room_id):
        with self.store.snapshot() as c:
            b = engine.board(c, room_id)
            hist = [dict(r) for r in c.execute("SELECT * FROM history WHERE room_id=? ORDER BY id DESC LIMIT 80", (room_id,))]
            exps = [dict(r) for r in c.execute("SELECT * FROM exports WHERE room_id=? ORDER BY created_ms DESC LIMIT 20", (room_id,))]
            props = [engine.proposal_view(c, room_id, r["proposal_id"]) for r in
                     c.execute("SELECT proposal_id FROM proposals WHERE room_id=? ORDER BY created_version DESC, proposal_id DESC LIMIT 10", (room_id,))]
            outbox = c.execute("SELECT state, COUNT(*) n FROM outbox WHERE room_id=? GROUP BY state", (room_id,)).fetchall()
            pend = [dict(r) for r in c.execute("SELECT q_id, staff_id, action_json, expires_ms, state FROM pending "
                                               "WHERE room_id=? AND state='open' ORDER BY created_ms", (room_id,))]
        for h in hist:
            h["detail"] = json.loads(h.pop("detail_json"))
        rm = b["room"]
        now = roster.room_now_ms(rm)
        return {**b, "history": hist, "exports": exps, "proposals": props, "pending": pend,
                "outbox": {r["state"]: r["n"] for r in outbox},
                "clock": {"now_ms": now, "label": iv.local_label(now, rm["timezone"]),
                          "synthetic": rm["kind"] == "local_demo"},
                "transcript": self.local.messages(room_id) if rm["kind"] == "local_demo" else None,
                "ai": self.ai.status(), "switch": self.switch_status()}

    def switch_status(self):
        if self.bridge is None:
            return {"state": "BLOCKED", "configured": self.switch_fields,
                    "reasons": [r for r, ok in (("docker_not_found" if not _which("docker") else "docker_unverified", False),
                                                ("no_server_url", self.switch_fields.get("base_url")),
                                                ("no_agent_credential", self.switch_fields.get("api_key") and self.switch_fields.get("agent_id")),
                                                ("no_room_id", self.switch_fields.get("room_id"))) if not ok]}
        return self.bridge.status()


def _which(name):
    from shutil import which
    return which(name) is not None


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


def make_handler(app: App):
    allowed_hosts = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "ShiftPatch/0.1"

        def log_message(self, fmt, *args):  # ids and status only, never bodies
            sys.stderr.write("%s %s\n" % (self.command, urlsplit(self.path).path))

        # ---------------- plumbing
        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def ok(self, obj, code=200):
            self._send(code, _json(obj))

        def err(self, code, error, **info):
            self._send(code, _json({"error": error, **info}))

        def _guard(self, write: bool) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self.err(403, "HOST_NOT_ALLOWED")
                return False
            if write:
                if self.headers.get("X-ShiftPatch-Token") != app.token:
                    self.err(403, "MISSING_LOCAL_TOKEN")
                    return False
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{h}" for h in allowed_hosts}:
                    self.err(403, "ORIGIN_NOT_ALLOWED")
                    return False
            return True

        def _body(self, limit):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("BODY_TOO_LARGE")
            return self.rfile.read(n) if n else b""

        def _room(self, q):
            room_id = (q.get("room") or [roster.LOCAL_ROOM])[0]
            with app.store.snapshot() as c:
                if c.execute("SELECT 1 FROM rooms WHERE room_id=?", (room_id,)).fetchone() is None:
                    return None
            return room_id

        # ---------------- GET
        def do_GET(self):
            if not self._guard(False):
                return
            u = urlsplit(self.path)
            q = parse_qs(u.query)
            p = u.path
            try:
                if p == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if p == "/" or p == "/index.html":
                    html = (WEB / "index.html").read_text().replace("__TOKEN__", app.token)
                    return self._send(200, html.encode(), "text/html; charset=utf-8")
                if p.startswith("/static/"):
                    f = (WEB / p[len("/static/"):]).resolve()
                    if WEB.resolve() not in f.parents or not f.is_file():
                        return self.err(404, "NOT_FOUND")
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    if ctype.startswith("text/") or ctype.endswith("javascript"):
                        ctype += "; charset=utf-8"
                    return self._send(200, f.read_bytes(), ctype)
                if p == "/api/state":
                    room_id = self._room(q)
                    if room_id is None:
                        return self.err(404, "ROOM_NOT_FOUND")
                    return self.ok(app.state(room_id))
                if p == "/api/rooms":
                    with app.store.snapshot() as c:
                        rows = [dict(r) for r in c.execute("SELECT room_id, kind, label, roster_version, events_started FROM rooms")]
                    return self.ok({"rooms": rows})
                m = re.fullmatch(r"/api/roster/draft/([0-9a-f]{10})", p)
                if m:
                    d = app.drafts.get(m.group(1))
                    return self.ok(draft_view(d)) if d else self.err(404, "DRAFT_NOT_FOUND")
                m = re.fullmatch(r"/api/roster/draft/([0-9a-f]{10})/image", p)
                if m:
                    d = app.drafts.get(m.group(1))
                    if not d or not d.get("image") or not os.path.exists(d["image"]):
                        return self.err(404, "IMAGE_NOT_FOUND")
                    return self._send(200, Path(d["image"]).read_bytes(), d["mime"])
                m = re.fullmatch(r"/exports/([\w\-.]+\.(csv|ics))", p)
                if m:
                    with app.store.snapshot() as c:
                        hit = c.execute("SELECT room_id FROM exports WHERE file_name=? AND state='published'",
                                        (m.group(1),)).fetchone()
                    f = app.exports_dir / exporter.room_dir(hit["room_id"]) / m.group(1) if hit else None
                    if f is None or not f.exists():
                        return self.err(404, "EXPORT_NOT_FOUND")
                    ctype = "text/csv; charset=utf-8" if m.group(2) == "csv" else "text/calendar; charset=utf-8"
                    return self._send(200, f.read_bytes(), ctype,
                                      {"Content-Disposition": f'attachment; filename="{m.group(1)}"'})
                if p == "/api/switch/status":
                    return self.ok(app.switch_status())
                return self.err(404, "NOT_FOUND")
            except engine.Rejected as r:
                return self.err(400, r.code, **r.info)

        # ---------------- POST
        def do_POST(self):
            if not self._guard(True):
                return
            u = urlsplit(self.path)
            q = parse_qs(u.query)
            p = u.path
            try:
                if p == "/api/roster/image":
                    room_id = self._room(q)
                    if room_id is None:
                        return self.err(404, "ROOM_NOT_FOUND")
                    data = self._body(MAX_UPLOAD)
                    try:
                        d = app.drafts.create_from_image(data, room_id)
                    except ocr.OcrError as e:
                        return self.err(422, str(e))
                    return self.ok(draft_view(d))
                body = self._body(MAX_JSON)
                if p == "/api/roster/csv":
                    room_id = self._room(q)
                    if room_id is None:
                        return self.err(404, "ROOM_NOT_FOUND")
                    try:
                        rows = roster.parse_csv(body)
                    except ValueError as e:
                        return self.err(422, str(e))
                    return self.ok(draft_view(app.drafts.create_from_rows(rows, room_id, "csv")))
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    return self.err(400, "BAD_JSON")
                if p == "/api/roster/sample":
                    rows = roster.parse_csv((APP / "fixtures" / "roster_sample.csv").read_bytes())
                    return self.ok(draft_view(app.drafts.create_from_rows(rows, roster.LOCAL_ROOM, "sample_csv")))
                m = re.fullmatch(r"/api/roster/draft/([0-9a-f]{10})/(validate|approve|discard)", p)
                if m:
                    d = app.drafts.get(m.group(1))
                    if not d:
                        return self.err(404, "DRAFT_NOT_FOUND")
                    if m.group(2) == "discard":
                        app.drafts.discard(d["draft_id"])
                        return self.ok({"discarded": True})
                    rows = clean_rows(data.get("rows"), d)
                    mapping = {k: v for k, v in (data.get("mapping") or {}).items()
                               if isinstance(k, str) and (v is None or v in roster.BY_ID)}
                    confirmed = {n for n in (data.get("confirmed") or []) if isinstance(n, str)}
                    if m.group(2) == "validate":
                        d["rows"] = rows
                        return self.ok(draft_view(d, mapping, confirmed))
                    res = roster.import_roster(app.store, d["room_id"], rows, mapping, confirmed,
                                               data.get("approved") is True, d["source"])
                    app.drafts.discard(d["draft_id"])
                    return self.ok({"imported": res})
                if p == "/api/demo/message":
                    room_id = self._room(q)
                    if room_id is None:
                        return self.err(404, "ROOM_NOT_FOUND")
                    try:
                        res = app.local.post(room_id, str(data.get("actor", "")), str(data.get("body", "")))
                    except PermissionError as e:
                        return self.err(403, "LOCAL_DEMO_ONLY", detail=str(e))
                    app.dispatcher.run_once()
                    return self.ok(res)
                if p == "/api/demo/reset":
                    roster.reset_local_demo(app.store)
                    app.local.clear(roster.LOCAL_ROOM)
                    app.drafts.discard_all()
                    return self.ok({"reset": True})
                if p == "/api/export":
                    room_id = self._room(q)
                    if room_id is None:
                        return self.err(404, "ROOM_NOT_FOUND")
                    kind = data.get("kind", "csv")
                    if kind not in ("csv", "ics"):
                        return self.err(400, "BAD_KIND")
                    return self.ok(app.export(room_id, kind))
                if p == "/api/outbox/retry":
                    room_id = self._room(q)
                    return self.ok({"retried": app.dispatcher.retry_failed(room_id)})
                if p == "/api/switch/probe":
                    if app.bridge is None:
                        return self.ok(app.switch_status())
                    return self.ok(app.bridge.probe())
                return self.err(404, "NOT_FOUND")
            except engine.Rejected as r:
                return self.err(409, r.code, **r.info)
            except ValueError as e:
                return self.err(400, str(e) if str(e).isupper() else "BAD_REQUEST")

    return H


def clean_rows(rows, draft):
    if not isinstance(rows, list) or len(rows) > roster.MAX_ROWS:
        raise ValueError("BAD_ROWS")
    out = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise ValueError("BAD_ROWS")
        row = {f: ocr.normalize_cell(f, str(r.get(f, ""))[:80]) for f in roster.CSV_HEADERS}
        orig = draft["rows"][i] if i < len(draft["rows"]) else {}
        row["ocr_issues"] = [x for x in orig.get("ocr_issues", []) if x == "OCR_SCORE_REVIEW_SIGNAL_NOT_ACCURACY"] \
            if all(orig.get(f) == row[f] for f in roster.CSV_HEADERS) else []
        if orig.get("cells"):
            row["cells"] = orig["cells"]
        out.append(row)
    return out


def draft_view(d, mapping=None, confirmed=None):
    rows = d["rows"]
    mapping = mapping if mapping is not None else roster.suggest_mapping(rows)
    confirmed = confirmed or set()
    ri, gi = roster.validate(rows, mapping, confirmed) if rows else ([], ["NO_ROWS"])
    return {"draft_id": d["draft_id"], "room_id": d["room_id"], "source": d["source"], "status": d["status"],
            "has_image": bool(d.get("image")), "width": d.get("width"), "height": d.get("height"),
            "engine": d.get("engine"), "seconds": d.get("seconds"), "detail": d.get("detail"),
            "rows": [{k: v for k, v in r.items()} for r in rows], "row_issues": ri, "global_issues": gi,
            "blocking": roster.blocking(ri, gi), "mapping": mapping, "confirmed": sorted(confirmed),
            "directory": [{k: x[k] for k in ("staff_id", "name", "name_en", "role")} for x in roster.DIRECTORY]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", default=str(APP / "data"))
    ap.add_argument("--switch-config", default=str(APP / "config" / "switch.local.json"))
    a = ap.parse_args(argv)
    app = App(Path(a.data), a.port, switch_config=Path(a.switch_config))
    app.start_background()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app))
    signal.signal(signal.SIGTERM, lambda *_: (app.drafts.discard_all(), sys.exit(0)))
    print(f"ShiftPatch on http://127.0.0.1:{a.port}/  (data: {a.data}; AI: {app.ai.status()['status']}; "
          f"Switch: {app.switch_status()['state']})", flush=True)
    try:
        srv.serve_forever()
    finally:
        app.drafts.discard_all()


if __name__ == "__main__":
    main()
