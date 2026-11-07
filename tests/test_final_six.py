"""Regressions for the six fixes from the final three-model critique
(Kimi 3.1 Pro, Opus 5.5, Fable). Each class names the finding it covers.
Everything here is synthetic: TrustedEnvelopes built in the test, a slow
fake interpreter, the local HTTP server, and the Switch contract double
(tests/fake_switch.py). None of it is a live Switch run."""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from fake_switch import FakeSwitch
from harness import MAPPING, MIN, ROWS, T0, Base

from shiftpatch import engine, exporter, roster
from shiftpatch import intervals as iv
from shiftpatch.agent import Agent
from shiftpatch.interpret import Interpreter, Suggestion
from shiftpatch.local_demo import DemoRoomBusy, LocalDemoRoom
from shiftpatch.server import App, make_handler
from shiftpatch.switch_bridge import SwitchBridge, SwitchConfig

APP_DIR = Path(__file__).resolve().parent.parent


def wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------- 1
class LateReplyAttribution(Base):
    """Fix 1. Q1 (13–14 unavailable) is replaced by Q2 (15–16 unavailable).
    A bare yes/no written between the two messages but received after Q2
    used to approve or close Q2 (ROOT_FINAL_CHECK LATE_ACK_YES/NO)."""

    def setUp(self):
        super().setUp()
        self.import_roster()
        t = self.t
        self.q1 = self.agent.handle(self.env("minsu", "@ShiftPatch 13~14시 못 할 것 같아요", at=t, received=t, mid="A"))
        self.q2 = self.agent.handle(self.env("minsu", "@ShiftPatch 15~16시 못 할 것 같아요",
                                             at=t + 2 * MIN, received=t + 2 * MIN, mid="B"))
        self.assertEqual((self.q1["pending"], self.q2["pending"]), ("Q1", "Q2"))
        self.t0 = t

    def pending_states(self):
        with self.store.snapshot() as c:
            return {r["q_id"]: r["state"] for r in c.execute("SELECT q_id, state FROM pending")}

    def late(self, body, mid="old-ack"):
        return self.agent.handle(self.env("minsu", body, at=self.t0 + MIN, received=self.t0 + 3 * MIN, mid=mid))

    def test_late_bare_yes_does_not_approve_the_newer_question(self):
        v = self.version()
        r = self.late("@ShiftPatch yes")
        self.assertEqual(r["status"], "rejected", r)
        self.assertEqual(r["code"], "CONFIRMATION_NEWER_THAN_REPLY")
        self.assertIn("Q2", r["reply"])
        self.assertEqual(self.version(), v)
        self.assertEqual(self.board()["gaps"], [])
        self.assertEqual(self.pending_states(), {"Q1": "superseded", "Q2": "open"})

    def test_late_bare_no_does_not_close_the_newer_question(self):
        r = self.late("@ShiftPatch no")
        self.assertEqual(r.get("code"), "CONFIRMATION_NEWER_THAN_REPLY", r)
        self.assertEqual(self.pending_states()["Q2"], "open")

    def test_late_korean_bare_yes_and_no(self):
        for i, body in enumerate(("@ShiftPatch 네", "@ShiftPatch 아니요")):
            with self.subTest(body=body):
                r = self.late(body, mid=f"old-ko-{i}")
                self.assertEqual(r.get("code"), "CONFIRMATION_NEWER_THAN_REPLY", r)
                self.assertIn("먼저 쓴 것이라", r["reply"])
        self.assertEqual(self.pending_states()["Q2"], "open")

    def test_late_reply_with_the_newer_q_id_is_refused_too(self):
        for i, body in enumerate(("@ShiftPatch 네 Q2", "@ShiftPatch 아니요 Q2")):
            with self.subTest(body=body):
                r = self.late(body, mid=f"old-q2-{i}")
                self.assertEqual(r.get("code"), "CONFIRMATION_NEWER_THAN_REPLY", r)
        self.assertEqual(self.pending_states()["Q2"], "open")

    def test_late_reply_naming_the_superseded_question_stays_closed(self):
        r = self.late("@ShiftPatch 네 Q1")
        self.assertEqual(r.get("code"), "CONFIRMATION_NOT_OPEN", r)
        self.assertEqual(self.board()["gaps"], [])

    def test_a_reply_written_after_q2_still_applies_it(self):
        self.late("@ShiftPatch yes")
        at = self.t0 + 4 * MIN
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 네", at=at, received=at, mid="fresh"))
        self.assertEqual(r["code"], "INABILITY_RECORDED", r)
        self.assertEqual(r["via"], "Q2")
        self.assertEqual(self.board()["gaps"], [(900, 960)])

    def test_refused_late_reply_does_not_move_the_watermark(self):
        self.late("@ShiftPatch yes")
        with self.store.snapshot() as c:
            self.assertIsNone(c.execute("SELECT * FROM watermarks WHERE staff_id='minsu'").fetchone())


class OutOfOrderQuestions(Base):
    """Fix 1, the other direction: an older message processed after a newer
    one must not replace the newer open question."""

    def setUp(self):
        super().setUp()
        self.import_roster()

    def test_older_message_arriving_late_does_not_replace_newer_question(self):
        t = self.t
        newer = self.agent.handle(self.env("minsu", "@ShiftPatch 15~16시 못 할 것 같아요", at=t + 2 * MIN,
                                           received=t + 2 * MIN, mid="B"))
        self.assertEqual(newer["pending"], "Q1")
        older = self.agent.handle(self.env("minsu", "@ShiftPatch 13~14시 못 할 것 같아요", at=t,
                                           received=t + 3 * MIN, mid="A"))
        self.assertEqual(older.get("code"), "NEWER_QUESTION_OPEN", older)
        self.assertIn("Q1", older["reply"])
        with self.store.snapshot() as c:
            self.assertEqual({r["q_id"]: r["state"] for r in c.execute("SELECT q_id, state FROM pending")}, {"Q1": "open"})
        at = t + 4 * MIN
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 네", at=at, received=at, mid="ack"))
        self.assertEqual(r["code"], "INABILITY_RECORDED", r)
        self.assertEqual(self.board()["gaps"], [(900, 960)])

    def test_bare_yes_picks_the_only_question_written_before_it(self):
        """Two questions of different kinds are open; a yes written between
        them can only mean the first one, so it is not ambiguous."""
        t = self.t
        self.agent.handle(self.env("minsu", "@ShiftPatch 13~17시 못 할 것 같아요", at=t, received=t, mid="A"))
        self.agent.handle(self.env("taeo", "@ShiftPatch noop", at=t, received=t, mid="noise"))
        q_av = self.agent.handle(self.env("minsu", "@ShiftPatch 17~18시는 할 수 있을 것 같아요", at=t + 2 * MIN,
                                          received=t + 2 * MIN, mid="B"))
        self.assertEqual(q_av.get("status"), "pending", q_av)
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 네", at=t + MIN, received=t + 3 * MIN, mid="ack"))
        self.assertEqual(r.get("code"), "INABILITY_RECORDED", r)
        self.assertEqual(r["via"], "Q1")

    def test_question_rows_from_before_the_upgrade_are_still_answerable(self):
        """Rows written before source_created_ms existed have NULL there and
        keep the old behaviour (answerable by a later yes)."""
        t = self.t
        q = self.agent.handle(self.env("minsu", "@ShiftPatch 13~17시 못 할 것 같아요", at=t, received=t, mid="A"))
        with self.store.tx() as c:
            c.execute("UPDATE pending SET source_created_ms=NULL WHERE q_id=?", (q["pending"],))
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 네", at=t + MIN, received=t + MIN, mid="ack"))
        self.assertEqual(r["code"], "INABILITY_RECORDED")

    def test_lifetime_still_runs_on_receive_time_and_order_on_message_time(self):
        created = T0 + 30 * MIN
        q = self.agent.handle(self.env("minsu", "@ShiftPatch 13~17시 못 할 것 같아요", at=created,
                                       received=created + 14 * MIN, mid="A"))
        with self.store.snapshot() as c:
            row = c.execute("SELECT created_ms, source_created_ms, expires_ms FROM pending WHERE q_id=?",
                            (q["pending"],)).fetchone()
        self.assertEqual(row["source_created_ms"], created)
        self.assertEqual(row["created_ms"], created + 14 * MIN)
        self.assertEqual(row["expires_ms"], created + 14 * MIN + engine.PENDING_TTL_MS)


# --------------------------------------------------------------------- 2
class SlowAI:
    """Synthetic interpreter that blocks until released (stands in for a
    slow model call). Not a real AI."""
    enabled = True

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def interpret(self, text, ctx):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(8):
            raise TimeoutError("synthetic gate")
        return Suggestion(kind="availability", date="2026-11-09", start="13:00", end="15:00", part_id="",
                          lang="en", question="")

    def status(self):
        return {"enabled": True, "engine": "synthetic-slow", "model_alias": "none", "status": "test"}


class LocalDemoConcurrency(Base):
    """Fix 2 (ROOT_FINAL_CHECK LOCAL_CONCURRENT_POST): a second message
    while the first is still being read used to void the first one."""

    def test_two_overlapping_posts_are_both_processed_in_arrival_order(self):
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 2026-11-09 13:00-17:00")
        slow = SlowAI()
        local = LocalDemoRoom(self.store, Agent(self.store, slow))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(local.post, self.room, "jian", "@ShiftPatch I can work after lunch for two hours")
            self.assertTrue(slow.entered.wait(5))
            f2 = pool.submit(local.post, self.room, "taeo", "@ShiftPatch available 2026-11-09 15:00-17:00")
            time.sleep(0.3)
            self.assertFalse(f2.done(), "second message must wait for the first")
            slow.release.set()
            r1, r2 = f1.result(timeout=10), f2.result(timeout=10)
        self.assertEqual(r1["status"], "pending", r1)
        self.assertEqual(r2["code"], "AVAILABILITY_RECORDED", r2)
        humans = [m["id"] for m in local.messages(self.room) if m["kind"] == "human"]
        self.assertEqual(humans, [r1["message_id"], r2["message_id"]])
        with self.store.snapshot() as c:
            replies = [r["reply_to"] for r in c.execute("SELECT reply_to FROM outbox WHERE room_id=? ORDER BY id",
                                                        (self.room,)) if r["reply_to"] in humans]
            ctx = [r["state"] for r in c.execute("SELECT state FROM exec_ctx")]
        self.assertEqual(replies, humans)
        self.assertNotIn("expired", ctx)

    def test_message_times_never_repeat_so_watermark_keeps_order(self):
        self.import_roster()
        local = LocalDemoRoom(self.store, self.agent)
        a = local.post(self.room, "jian", "@ShiftPatch 가능 2026-11-09 13:00-15:00")
        b = local.post(self.room, "jian", "@ShiftPatch 가능 취소 13:00-14:00")
        self.assertEqual(a["code"], "AVAILABILITY_RECORDED")
        self.assertNotEqual(b.get("code"), "OLDER_THAN_LATEST", b)
        ats = [m["at"] for m in local.messages(self.room) if m["kind"] == "human"]
        self.assertLess(ats[0], ats[1])

    def test_queue_limit_refuses_instead_of_piling_up(self):
        import shiftpatch.local_demo as ld
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 2026-11-09 13:00-17:00")
        slow = SlowAI()
        local = LocalDemoRoom(self.store, Agent(self.store, slow))
        old = ld.MAX_WAITING
        ld.MAX_WAITING = 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                f1 = pool.submit(local.post, self.room, "jian", "@ShiftPatch after lunch maybe")
                self.assertTrue(slow.entered.wait(5))
                with self.assertRaises(DemoRoomBusy):
                    local.post(self.room, "taeo", "@ShiftPatch available 2026-11-09 15:00-17:00")
                slow.release.set()
                f1.result(timeout=10)
        finally:
            ld.MAX_WAITING = old
        r = local.post(self.room, "taeo", "@ShiftPatch available 2026-11-09 15:00-17:00")
        self.assertEqual(r["code"], "AVAILABILITY_RECORDED")


class LocalDemoConcurrencyHttp(unittest.TestCase):
    """Fix 2 over real local HTTP: two POST /api/demo/message at once while
    the (synthetic, slow) interpreter is reading the first."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = srv.server_address[1]
        self.slow = SlowAI()
        self.app = App(Path(self.tmp.name), self.port, ai=self.slow, switch_config=Path(self.tmp.name) / "none.json")
        self.app.start_background()          # the reply loop, as run.py starts it
        srv.RequestHandlerClass = make_handler(self.app)
        self.srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def tearDown(self):
        try:
            self.slow.release.set()
            self.srv.shutdown()
            self.srv.server_close()
            self.assertTrue(self.app.close())
        finally:
            self.tmp.cleanup()

    def post(self, path, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        r.add_header("X-ShiftPatch-Token", self.app.token)
        r.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def test_two_simultaneous_posts_both_get_200_and_replies_in_order(self):
        sample = (APP_DIR / "fixtures" / "roster_sample.csv").read_bytes()
        code, d = self.post("/api/roster/csv?room=local-demo", sample, "text/csv")
        names = sorted({r["name"] for r in d["rows"]})
        code, _ = self.post(f"/api/roster/draft/{d['draft_id']}/approve",
                            {"rows": d["rows"], "mapping": d["mapping"], "confirmed": names, "approved": True})
        self.assertEqual(code, 200)
        code, r = self.post("/api/demo/message?room=local-demo",
                            {"actor": "minsu", "body": "@ShiftPatch 불가 2026-11-09 13:00-17:00"})
        self.assertEqual(code, 200, r)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self.post, "/api/demo/message?room=local-demo",
                             {"actor": "jian", "body": "@ShiftPatch I can work after lunch for two hours"})
            self.assertTrue(self.slow.entered.wait(5))
            f2 = pool.submit(self.post, "/api/demo/message?room=local-demo",
                             {"actor": "taeo", "body": "@ShiftPatch available 2026-11-09 15:00-17:00"})
            time.sleep(0.3)
            self.slow.release.set()
            (c1, r1), (c2, r2) = f1.result(timeout=20), f2.result(timeout=20)
        self.assertEqual((c1, c2), (200, 200), (r1, r2))
        self.assertEqual(r1["status"], "pending")
        self.assertEqual(r2["code"], "AVAILABILITY_RECORDED")
        self.assertTrue(wait(lambda: len([m for m in self.app.local.messages("local-demo") if m["kind"] == "agent"]) >= 3))
        tx = self.app.local.messages("local-demo")
        humans = [m["id"] for m in tx if m["kind"] == "human"]
        replies = [m["reply_to"] for m in tx if m["kind"] == "agent"]
        self.assertEqual(humans[-2:], [r1["message_id"], r2["message_id"]])
        self.assertEqual(replies[-2:], humans[-2:])

    def test_switch_room_through_actor_picker_is_still_403(self):
        roster.create_room(self.app.store, "!x:localhost", "switch", "x")
        code, r = self.post("/api/demo/message?room=" + urllib.request.quote("!x:localhost"),
                            {"actor": "seoyeon", "body": "@ShiftPatch 확정 P1"})
        self.assertEqual((code, r["error"]), (403, "LOCAL_DEMO_ONLY"))


# --------------------------------------------------------------------- 4
ROOM = "!final-six:localhost"
LINKED = {"@observed-seoyeon:localhost": "seoyeon", "@observed-minsu:localhost": "minsu",
          "@observed-jian:localhost": "jian"}
TAEO_REAL = "@switch-mattermost-0f3c-unrelated-shape:localhost"


class ObservedSenderIds(Base):
    """Fix 4: the real sender id comes from a received Switch event (contract
    double here), is shown to the local admin, and only an observed id can be
    linked with `link`. No id is constructed from another one."""

    def setUp(self):
        super().setUp()
        self.fake = FakeSwitch(room_id=ROOM)
        self.room = ROOM
        roster.create_room(self.store, ROOM, "switch", "switch")
        roster.import_switch_links(self.store, ROOM, LINKED)
        # No roster yet: the import refuses while Taeo has no linked account,
        # which is exactly the setup moment this path is for.
        self.cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="test-key", room_id=ROOM)
        self.bridge = SwitchBridge(self.store, self.agent, self.cfg)

    def tearDown(self):
        try:
            self.assertTrue(self.bridge.stop())
        finally:
            self.fake.close()
            super().tearDown()

    def probe(self, body="@ShiftPatch status secret-words-not-to-keep"):
        self.bridge.start()
        self.assertTrue(wait(lambda: self.bridge.state == "connected"))
        before = self.version()
        self.fake.push_message(TAEO_REAL, body, sender_name="taeo")
        self.assertTrue(wait(lambda: self.seen()))
        return before

    def seen(self):
        with self.store.snapshot() as c:
            return engine.unlinked_seen(c, ROOM, self.bridge.clock())

    def test_roster_import_is_refused_until_the_observed_sender_is_linked(self):
        with self.assertRaises(engine.Rejected) as e:
            roster.import_roster(self.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")
        self.assertEqual(e.exception.info.get("issues"), ["STAFF_HAS_NO_SWITCH_ACCOUNT"])

    def test_unlinked_probe_is_recorded_without_text_and_without_a_version_change(self):
        before = self.probe()
        self.assertEqual(self.version(), before)
        rows = self.seen()
        self.assertEqual([(r["platform_user_id"], r["display_name"], r["seen_count"]) for r in rows],
                         [(TAEO_REAL, "taeo", 1)])
        with self.store.snapshot() as c:
            dump = "\n".join(str(tuple(r)) for t in ("unlinked_seen", "processed", "history", "pending")
                             for r in c.execute(f"SELECT * FROM {t}"))
        self.assertNotIn("secret-words-not-to-keep", dump)

    def test_only_an_observed_sender_can_be_linked(self):
        with self.assertRaises(engine.Rejected) as e:
            roster.link_observed_sender(self.store, ROOM, "@observed-taeo:localhost", "taeo", now_ms=self.bridge.clock())
        self.assertEqual(e.exception.code, "SENDER_NOT_OBSERVED")
        self.probe()
        res = roster.link_observed_sender(self.store, ROOM, TAEO_REAL, "taeo", now_ms=self.bridge.clock())
        self.assertEqual(res["linked"], 4)
        self.assertEqual(self.seen(), [])
        with self.store.snapshot() as c:
            links = {r["platform_user_id"]: r["staff_id"] for r in c.execute("SELECT * FROM links WHERE room_id=?", (ROOM,))}
        self.assertEqual(links, {**LINKED, TAEO_REAL: "taeo"})
        roster.import_roster(self.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")
        self.fake.push_message(TAEO_REAL, "@ShiftPatch 가능 2026-11-09 15:00-17:00", sender_name="taeo",
                               timestamp=self.bridge.clock())
        self.assertTrue(wait(lambda: any(a["staff_id"] == "taeo" for a in self.board()["availability"])))

    def test_seen_rows_expire_after_an_hour(self):
        self.probe()
        self.assertEqual(len(self.seen()), 1)
        with self.store.snapshot() as c:
            later = engine.unlinked_seen(c, ROOM, self.bridge.clock() + engine.UNLINKED_SEEN_TTL_MS + 1000)
        self.assertEqual(later, [])

    def test_status_api_lists_the_observed_sender(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            cfgp = Path(tmp.name) / "switch.local.json"
            cfgp.write_text(json.dumps({"base_url": self.fake.url, "agent_id": "agent-1", "api_key": "test-key",
                                        "room_id": ROOM, "agent_name": "shiftpatch"}))
            app = App(Path(tmp.name) / "data", 0, ai=Interpreter(enabled=False), switch_config=cfgp)
            try:
                roster.import_switch_links(app.store, ROOM, LINKED)
                app.start_background()
                self.assertTrue(wait(lambda: app.bridge.state == "connected"))
                self.fake.push_message(TAEO_REAL, "@ShiftPatch 표", sender_name="taeo")
                self.assertTrue(wait(lambda: app.switch_status().get("unlinked_seen")))
                st = app.switch_status()
                self.assertEqual([(r["sender"], r["display_name"]) for r in st["unlinked_seen"]], [(TAEO_REAL, "taeo")])
                self.assertEqual(sorted(x["staff_id"] for x in st["linked"]), ["jian", "minsu", "seoyeon"])
                self.assertNotIn("api_key", json.dumps(st))
            finally:
                self.assertTrue(app.close())
        finally:
            tmp.cleanup()


class ManageSendersCli(unittest.TestCase):
    """Fix 4: `manage.py senders` / `link` against a temp data dir and temp
    config (never the private config/switch.local.json)."""

    def test_senders_then_link(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = d / "switch.local.json"
            cfg.write_text(json.dumps({"base_url": "http://127.0.0.1:9", "agent_id": "a", "api_key": "k",
                                       "room_id": ROOM, "agent_name": "shiftpatch"}))
            from shiftpatch.db import Store
            store = Store(d / "data" / "shiftpatch.db")
            roster.create_room(store, ROOM, "switch", "switch")
            now = int(time.time() * 1000)
            with store.tx() as c:
                engine.note_unlinked(c, ROOM, TAEO_REAL, "taeo", now)

            def run(*args):
                return subprocess.run([sys.executable, str(APP_DIR / "manage.py"), "--data", str(d / "data"),
                                       "--config", str(cfg), *args], capture_output=True, text=True, timeout=60)
            out = run("senders")
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(out.stdout)
            self.assertEqual([r["sender"] for r in data["unlinked_seen"]], [TAEO_REAL])
            self.assertNotIn('"k"', out.stdout)
            bad = run("link", "@guessed-taeo:localhost", "taeo")
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("SENDER_NOT_OBSERVED", bad.stderr)
            ok = run("link", TAEO_REAL, "taeo")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("linked", ok.stdout)
            self.assertEqual(json.loads(run("senders").stdout)["linked"],
                             [{"platform_user_id": TAEO_REAL, "staff_id": "taeo"}])


# --------------------------------------------------------------------- 5
class MidnightAndClockTimes(Base):
    """Fix 5 (ROOT_FINAL_CHECK ICS_MIDNIGHT): 24:00 is written as 00:00 of
    the next day in ICS; impossible clock times are row issues, not 400."""

    def snap(self, date, end=1440):
        return {"room": {"room_id": "synthetic", "date": date, "timezone": "Asia/Seoul", "duty": "test"},
                "version": 1, "names": {"taeo": ("Taeo", "Taeo")},
                "coverage": [{"start": 1020, "end": end, "staff_id": "taeo", "status": "original"}]}

    def lines(self, ics, key):
        return [x for x in ics.decode().splitlines() if x.startswith(key)]

    def test_end_of_day_rolls_to_next_day_including_month_and_year_end(self):
        for date, want in (("2026-11-09", "20261110T000000"), ("2026-11-30", "20261201T000000"),
                           ("2026-12-31", "20270101T000000"), ("2028-02-28", "20280229T000000")):
            with self.subTest(date=date):
                ics = exporter.render_ics(self.snap(date), T0)
                self.assertEqual(self.lines(ics, "DTEND"), [f"DTEND;TZID=Asia/Seoul:{want}"])
                self.assertEqual(self.lines(ics, "DTSTART"), [f"DTSTART;TZID=Asia/Seoul:{date.replace('-', '')}T170000"])
                self.assertNotIn("T24", ics.decode())

    def test_ordinary_end_stays_on_the_same_day(self):
        ics = exporter.render_ics(self.snap("2026-11-09", end=1080), T0)
        self.assertEqual(self.lines(ics, "DTEND"), ["DTEND;TZID=Asia/Seoul:20261109T180000"])

    def test_exported_files_for_a_roster_ending_at_24(self):
        rows = [{"name": "지안", "date": "2026-11-09", "start": "09:00", "end": "17:00", "duty": "일반 문의"},
                {"name": "태오", "date": "2026-11-09", "start": "17:00", "end": "24:00", "duty": "일반 문의"}]
        self.import_roster(rows, {"지안": "jian", "태오": "taeo"})
        out = self.dir / "exports"
        ics = exporter.export(self.store, self.room, "ics", out)
        csvr = exporter.export(self.store, self.room, "csv", out)
        self.assertTrue(ics["ok"] and csvr["ok"], (ics, csvr))
        files = {p.suffix: p for p in (out / exporter.room_dir(self.room)).iterdir()}
        text = files[".ics"].read_text()
        self.assertIn("DTEND;TZID=Asia/Seoul:20261110T000000", text)
        self.assertNotIn("T240000", text)
        csv_rows = files[".csv"].read_text(encoding="utf-8-sig").splitlines()
        self.assertTrue(any(",17:00,24:00," in r for r in csv_rows), csv_rows)   # CSV keeps 24:00

    def test_impossible_clock_times_are_row_issues(self):
        base = {"name": "태오", "date": "2026-11-09", "duty": "일반 문의"}
        cases = {("17:00", "24:30"): "END_NOT_A_CLOCK_TIME", ("24:30", "24:00"): "START_NOT_A_CLOCK_TIME",
                 ("17:00", "24:01"): "END_NOT_A_CLOCK_TIME", ("13:60", "15:00"): "START_NOT_A_CLOCK_TIME",
                 ("17:00", "25:00"): "END_NOT_A_CLOCK_TIME"}
        for (s, e), code in cases.items():
            with self.subTest(start=s, end=e):
                ri, gi = roster.validate([{**base, "start": s, "end": e}], {"태오": "taeo"}, {"태오"})
                self.assertIn(code, ri[0])
                self.assertIn(code, roster.BLOCKING)
        ri, _ = roster.validate([{**base, "start": "17:00", "end": "24:00"}], {"태오": "taeo"}, {"태오"})
        self.assertEqual(ri, [[]])
        ri, _ = roster.validate([{**base, "start": "5pm", "end": "24:00"}], {"태오": "taeo"}, {"태오"})
        self.assertIn("START_NEEDS_EXPLICIT_24H_TIME", ri[0])

    def test_csv_upload_with_24_30_returns_row_issues_over_http(self):
        tmp = tempfile.TemporaryDirectory()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = srv.server_address[1]
        app = App(Path(tmp.name), port, ai=Interpreter(enabled=False), switch_config=Path(tmp.name) / "none.json")
        srv.RequestHandlerClass = make_handler(app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            body = "name,date,start,end,duty\n태오,2026-11-09,17:00,24:30,일반 문의\n지안,2026-11-09,09:00,17:00,일반 문의\n"
            r = urllib.request.Request(f"http://127.0.0.1:{port}/api/roster/csv?room=local-demo", data=body.encode(),
                                       method="POST", headers={"X-ShiftPatch-Token": app.token, "Content-Type": "text/csv"})
            with urllib.request.urlopen(r, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                d = json.loads(resp.read())
            self.assertIn("END_NOT_A_CLOCK_TIME", d["row_issues"][0])
            self.assertIn("END_NOT_A_CLOCK_TIME", d["blocking"])
            self.assertEqual(d["row_issues"][1], ["MAPPING_NOT_CONFIRMED"])
        finally:
            srv.shutdown()
            srv.server_close()
            self.assertTrue(app.close())
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
