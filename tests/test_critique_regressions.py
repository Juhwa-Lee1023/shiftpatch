"""Regressions for the defects found in the 2026-11-07 critique
(critique/20261107T0840Z). Each class names the finding it covers. Fault
injection here is synthetic: fake senders, a fake socket and the contract
double. None of it is a fault observed on a live Switch server."""
import threading
import time
from unittest.mock import patch

from fake_switch import FakeSwitch
from harness import MAPPING, MIN, ROWS, T0, Base
from test_switch_contract import ROOM, USERS, wait

from shiftpatch import engine, exporter, roster
from shiftpatch.agent import Agent, TrustedEnvelope, proposal_text
from shiftpatch.interpret import FakeInterpreter, Suggestion
from shiftpatch.messages import Names, josa
from shiftpatch.outbox import LEASE_MS, MAX_ATTEMPTS, Dispatcher, backoff_ms, delivery_view
from shiftpatch.switch_bridge import BadFrame, SwitchBridge, SwitchConfig, parse_frame


def sug(kind, start="", end="", part_id="", date="", lang="ko", question=""):
    return Suggestion(kind=kind, date=date, start=start, end=end, part_id=part_id, lang=lang, question=question)


class C01StrictClock(Base):
    """`13:60` used to be stored as 14:00 without any question."""

    def setUp(self):
        super().setUp()
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13:00-17:00")

    def test_invalid_minutes_and_past_midnight_change_nothing(self):
        for text in ["가능 13:60-15:00", "가능 13:90-16:00", "불가 13:00-14:75", "가능 13:00-15:60",
                     "가능 13:00-24:01", "가능 13:00-24:30", "가능 25:00-26:00", "available 13:60-15:00"]:
            before = (self.version(), self.board()["availability"], self.board()["proposal"], self.history_kinds())
            r = self.say("jian", f"@ShiftPatch {text}")
            after = (self.version(), self.board()["availability"], self.board()["proposal"], self.history_kinds())
            self.assertEqual(before, after, text)
            self.assertIn("00–59", r["reply"], text)

    def test_valid_half_hours_and_end_of_day_still_work(self):
        r = self.say("jian", "@ShiftPatch 가능 13:30-15:00")
        self.assertEqual(r["code"], "AVAILABILITY_RECORDED", r)
        self.assertEqual(self.board()["availability"][0]["pieces"], [(810, 900)])
        r = self.say("taeo", "@ShiftPatch 가능 15:00-24:00")      # 24:00 is a valid end
        self.assertEqual(r["code"], "AVAILABILITY_RECORDED", r)


class C02RangedWithdrawal(Base):
    """`가능 취소 13:00-14:00` used to withdraw the whole 13–17 row."""

    def setUp(self):
        super().setUp()
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13:00-17:00")
        self.say("jian", "@ShiftPatch 가능 13:00-17:00")

    def pieces(self, who="jian"):
        return sorted(p for a in self.board()["availability"] if a["staff_id"] == who for p in a["pieces"])

    def test_leading_middle_trailing(self):
        for cut, left in [("13:00-14:00", [(840, 1020)]), ("14:00-15:00", [(780, 840), (900, 1020)]),
                          ("16:00-17:00", [(780, 960)])]:
            with self.subTest(cut=cut):
                self.tearDown()
                self.setUp()
                v = self.version()
                r = self.say("jian", f"@ShiftPatch 가능 취소 {cut}")
                self.assertEqual(r["code"], "AVAILABILITY_WITHDRAWN", r)
                self.assertEqual(self.version(), v + 1)
                self.assertEqual(self.pieces(), left)
                parts = sorted((p["start"], p["end"]) for p in self.board()["proposal"]["parts"])
                self.assertEqual(parts, left)   # the new proposal never reaches into the withdrawn hour

    def test_disjoint_range_changes_nothing(self):
        v, before = self.version(), self.pieces()
        r = self.say("jian", "@ShiftPatch 가능 취소 09:00-10:00")
        self.assertEqual(r["code"], "NOTHING_TO_WITHDRAW", r)
        self.assertIn("09:00–10:00", r["reply"])
        self.assertEqual((self.version(), self.pieces()), (v, before))

    def test_bare_withdraw_still_removes_everything(self):
        r = self.say("jian", "@ShiftPatch 가능 취소")
        self.assertEqual(r["code"], "AVAILABILITY_WITHDRAWN")
        self.assertEqual(self.pieces(), [])

    def test_earlier_inability_still_cuts_the_remainder(self):
        self.say("jian", "@ShiftPatch 불가 13:00-14:00")          # Jian's 13–17 now effective 14–17
        self.assertEqual(self.pieces(), [(840, 1020)])
        self.say("jian", "@ShiftPatch 가능 취소 16:00-17:00")
        self.assertEqual(self.pieces(), [(840, 960)])            # not 13–16: the inability is not undone

    def test_reply_names_what_was_removed_and_what_is_left(self):
        r = self.say("jian", "@ShiftPatch withdraw 14:00-15:00")
        self.assertIn("14:00–15:00", r["reply"])
        self.assertIn("Still available: 13:00–14:00, 15:00–17:00", r["reply"])


class C02NaturalLanguageWithdrawal(Base):
    ai = FakeInterpreter({"13~14시는 빼 주세요": sug("withdraw", "13:00", "14:00")})

    def test_confirmed_ai_withdrawal_uses_the_same_rule(self):
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13:00-17:00")
        self.say("jian", "@ShiftPatch 가능 13:00-17:00")
        v = self.version()
        r = self.say("jian", "@ShiftPatch 13~14시는 빼 주세요")
        self.assertEqual(r["status"], "pending", r)
        self.assertEqual(self.version(), v)
        r = self.say("jian", "@ShiftPatch 네")
        self.assertEqual(r["code"], "AVAILABILITY_WITHDRAWN", r)
        self.assertEqual([p for a in self.board()["availability"] for p in a["pieces"]], [(840, 1020)])


class KS1ConfirmationLifetime(Base):
    """An 11-minute-late message used to create a question that was already closed."""

    def setUp(self):
        super().setUp()
        self.import_roster()

    def delayed(self, minutes, ack_after_ms):
        created = T0 + 30 * MIN
        received = created + minutes * MIN
        first = self.agent.handle(self.env("minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", at=created, received=received))
        ack_at = received + ack_after_ms
        second = self.agent.handle(self.env("minsu", f"@ShiftPatch 네 {first.get('pending')}", at=ack_at, received=ack_at))
        return first, second

    def test_11_and_14_minute_delay_can_be_confirmed_right_away(self):
        for minutes in (11, 14):
            with self.subTest(minutes=minutes):
                self.tearDown()
                self.setUp()
                v = self.version()
                first, second = self.delayed(minutes, 1000)
                self.assertEqual(first["status"], "pending", first)
                self.assertEqual(second["code"], "INABILITY_RECORDED", second)
                self.assertEqual(self.version(), v + 1)
                self.assertEqual(self.board()["gaps"], [(780, 1020)])

    def test_question_closes_ten_minutes_after_receipt(self):
        v = self.version()
        first, second = self.delayed(11, engine.PENDING_TTL_MS + 1000)
        self.assertEqual(second["code"], "CONFIRMATION_NOT_OPEN", second)
        self.assertEqual(self.version(), v)
        self.assertEqual(self.board()["gaps"], [])

    def test_until_label_uses_receive_time(self):
        created = iv_ms("2026-11-08", 21 * 60)
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", at=created,
                                       received=created + 11 * MIN))
        self.assertIn("21:21까지", r["reply"])                  # received 21:11 + 10 min

    def test_older_than_fifteen_minutes_still_refused(self):
        created = T0 + 30 * MIN
        r = self.agent.handle(self.env("minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", at=created,
                                       received=created + 16 * MIN))
        self.assertEqual(r["status"], "too_old")
        with self.store.snapshot() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pending").fetchone()[0], 0)

    def test_ordering_still_uses_message_time(self):
        """The receive clock only sets the question's lifetime. Which message
        came first is still decided by the platform timestamp."""
        created = T0 + 30 * MIN
        first = self.agent.handle(self.env("minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", at=created,
                                           received=created + 11 * MIN))
        ack_at = created + 11 * MIN + 1000
        r = self.agent.handle(self.env("minsu", f"@ShiftPatch 네 {first['pending']}", at=ack_at, received=ack_at))
        self.assertEqual(r["code"], "INABILITY_RECORDED")
        with self.store.snapshot() as c:
            self.assertEqual(c.execute("SELECT last_created_ms FROM watermarks WHERE staff_id='minsu'").fetchone()[0],
                             ack_at)
        v = self.version()
        older = self.env("minsu", "@ShiftPatch 가능 17:00-18:00", at=ack_at - 500, received=ack_at + MIN)
        self.assertEqual(self.agent.handle(older)["code"], "OLDER_THAN_LATEST")
        self.assertEqual(self.version(), v)


def iv_ms(date, minute):
    from shiftpatch import intervals as iv
    return iv.ms_for_local(date, minute, "Asia/Seoul")


class KS4RelinkDuringQuestion(Base):
    """A local admin relinking Minsu A→B used to let B approve A's question.
    Needs local admin access; this is not a remote privilege escalation."""

    OLD = {"opaque-manager": "seoyeon", "opaque-old-minsu": "minsu", "opaque-jian": "jian", "opaque-taeo": "taeo"}

    def setUp(self):
        super().setUp()
        self.room = "review-switch-room"
        roster.create_room(self.store, self.room, "switch", "isolated synthetic review")
        roster.import_switch_links(self.store, self.room, self.OLD)
        roster.import_roster(self.store, self.room, ROWS, MAPPING, set(MAPPING), True, "test")

    def msg(self, sender, text, mid, at):
        return TrustedEnvelope("switch", self.room, mid, sender, sender, text, at, at)

    def revs(self):
        with self.store.snapshot() as c:
            return {r["staff_id"]: r["link_rev"] for r in c.execute("SELECT * FROM links WHERE room_id=?", (self.room,))}

    def test_relink_closes_question_and_new_account_cannot_answer(self):
        first = self.agent.handle(self.msg("opaque-old-minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", "old", T0))
        self.assertEqual(first["status"], "pending")
        before = self.revs()
        new = {k: v for k, v in self.OLD.items() if v != "minsu"}
        new["opaque-new-minsu"] = "minsu"
        res = roster.import_switch_links(self.store, self.room, new)
        self.assertEqual(res["closed_questions"], [first["pending"]])
        after = self.revs()
        self.assertGreater(after["minsu"], max(before.values()))   # monotonic, never reused
        self.assertEqual({k: after[k] for k in ("seoyeon", "jian", "taeo")},
                         {k: before[k] for k in ("seoyeon", "jian", "taeo")})
        v = self.version()
        for i, text in enumerate([f"@ShiftPatch 네 {first['pending']}", "@ShiftPatch 네"]):
            r = self.agent.handle(self.msg("opaque-new-minsu", text, f"new-{i}", T0 + (i + 1) * MIN))
            self.assertNotEqual(r.get("status"), "applied", r)
        self.assertEqual(self.version(), v)
        self.assertEqual(self.board()["gaps"], [])

    def test_question_is_bound_to_the_account_it_was_asked_to(self):
        """Defence in depth: even if a link row were swapped without the
        relink function, the question still refuses the other account."""
        first = self.agent.handle(self.msg("opaque-old-minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", "old", T0))
        with self.store.tx() as c:
            c.execute("UPDATE links SET platform_user_id='opaque-new-minsu' WHERE room_id=? AND staff_id='minsu'",
                      (self.room,))
        v = self.version()
        r = self.agent.handle(self.msg("opaque-new-minsu", f"@ShiftPatch 네 {first['pending']}", "new", T0 + MIN))
        self.assertEqual(r["code"], "CONFIRMATION_OTHER_ACCOUNT", r)
        self.assertEqual(self.version(), v)

    def test_unchanged_relink_keeps_question_open(self):
        first = self.agent.handle(self.msg("opaque-old-minsu", "@ShiftPatch 내일 13~17시 못 할 것 같아요", "old", T0))
        res = roster.import_switch_links(self.store, self.room, dict(self.OLD))
        self.assertEqual(res["closed_questions"], [])
        r = self.agent.handle(self.msg("opaque-old-minsu", f"@ShiftPatch 네 {first['pending']}", "ack", T0 + MIN))
        self.assertEqual(r["code"], "INABILITY_RECORDED", r)


class C08Outbox(Base):
    """Replies used to overtake a failing one, be sent twice by overlapping
    dispatchers, and give up after five tries within ~1.5 s."""

    def setUp(self):
        super().setUp()
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13:00-17:00")
        self.say("jian", "@ShiftPatch 가능 13:00-15:00")
        self.now = {"t": 10_000_000}
        self.ids = [o["id"] for o in self.outbox()]

    def clock(self):
        return self.now["t"]

    def test_order_kept_while_first_reply_is_retried_with_backoff(self):
        attempts, delivered = [], []
        fails = {"left": 3}

        def sender(room, row):
            attempts.append(row["id"])
            if row["id"] == self.ids[0] and fails["left"]:
                fails["left"] -= 1
                raise OSError("synthetic 503")
            delivered.append(row["id"])
        d = Dispatcher(self.store, {"local_demo": sender}, clock=self.clock)
        for _ in range(3):
            d.run_once()                                   # same instant: only one attempt, no fast burn
        self.assertEqual(attempts, [self.ids[0]])
        for step in (1000, 2000, 4000):
            self.now["t"] += step
            d.run_once()
        self.assertEqual(delivered, self.ids)              # row 1 then row 2
        self.assertEqual(attempts, [self.ids[0]] * 4 + [self.ids[1]])
        self.assertEqual([backoff_ms(n) for n in (1, 2, 3)], [1000, 2000, 4000])

    def test_overlapping_passes_send_each_row_once(self):
        sent = []
        gate = threading.Event()

        def slow(room, row):
            sent.append(row["id"])
            gate.wait(0.3)
        d = Dispatcher(self.store, {"local_demo": slow}, clock=self.clock)
        counts = []
        threads = [threading.Thread(target=lambda: counts.append(d.run_once())) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(sorted(counts), [0, len(self.ids)])
        self.assertEqual(sent, self.ids)

    def test_two_dispatchers_on_one_file_do_not_double_send(self):
        sent = []
        lock = threading.Lock()

        def slow(room, row):
            with lock:
                sent.append(row["id"])
            time.sleep(0.2)
        a = Dispatcher(self.store, {"local_demo": slow}, clock=self.clock)
        b = Dispatcher(self.store, {"local_demo": slow}, clock=self.clock)
        threads = [threading.Thread(target=x.run_once) for x in (a, b, a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        a.run_once()
        b.run_once()
        self.assertEqual(sorted(sent), sorted(set(sent)))
        self.assertEqual(sorted(sent), self.ids)

    def test_exhausted_reply_is_visible_and_retry_sends_it_once_without_redoing_state(self):
        def down(room, row):
            if row["id"] == self.ids[0]:
                raise OSError("synthetic outage")
        d = Dispatcher(self.store, {"local_demo": down}, clock=self.clock)
        for _ in range(MAX_ATTEMPTS + 2):
            d.run_once()
            self.now["t"] += 60_000
        rows = {o["id"]: o for o in self.outbox()}
        self.assertEqual(rows[self.ids[0]]["state"], "failed")
        self.assertEqual(rows[self.ids[0]]["attempts"], MAX_ATTEMPTS)
        self.assertEqual(rows[self.ids[1]]["state"], "sent")     # later replies are not held forever
        with self.store.snapshot() as c:
            view = delivery_view(c, self.room, self.clock())
        self.assertEqual([x["id"] for x in view], [self.ids[0]])
        self.assertIn("synthetic outage", view[0]["last_error"])
        v, hist = self.version(), self.history_kinds()
        sent = []
        d2 = Dispatcher(self.store, {"local_demo": lambda room, row: sent.append(row)}, clock=self.clock)
        self.assertEqual(d2.retry_failed(self.room), 1)
        d2.run_once()
        d2.run_once()
        self.assertEqual([r["id"] for r in sent], [self.ids[0]])
        self.assertTrue(sent[0]["body"].startswith("(늦게 전달되는 답장입니다)"))
        self.assertEqual((self.version(), self.history_kinds()), (v, hist))

    def test_crash_after_send_means_at_least_once(self):
        """Honest limit: a send that succeeded but was never marked sent is
        sent again once its lease expires. Not exactly-once."""
        sent = []
        d = Dispatcher(self.store, {"local_demo": lambda room, row: sent.append(row["id"])}, clock=self.clock)
        self.assertTrue(d._claim(self.ids[0], self.clock()))      # claimed, then the process "dies"
        sent.append(self.ids[0])                                  # ...after the chat server accepted it
        d2 = Dispatcher(self.store, {"local_demo": lambda room, row: sent.append(row["id"])}, clock=self.clock)
        d2.run_once()
        self.assertEqual(sent, [self.ids[0]])                     # lease still held: nothing sent
        self.now["t"] += LEASE_MS + 1
        d2.run_once()
        self.assertEqual(sent.count(self.ids[0]), 2)


class C03Export(Base):
    """An exporter failure used to leave only "Creating…" in the room."""

    def setUp(self):
        super().setUp()
        self.import_roster()

    def test_raising_exporter_gets_failure_reply_and_new_request_works(self):
        calls = []

        def broken(room, kind):
            calls.append(kind)
            raise OSError("synthetic export directory unavailable")
        real = self.agent.exporter
        self.agent.exporter = broken
        env = self.env("seoyeon", "@ShiftPatch export", mid="same-export-event")
        v = self.version()
        first = self.agent.handle(env)
        self.assertFalse(first["export_result"]["ok"])
        bodies = [o["body"] for o in self.outbox()]
        self.assertTrue(any(b.startswith("Creating") for b in bodies))
        self.assertTrue(any("Export failed (OSError)" in b and "Send `export` again" in b for b in bodies))
        self.assertEqual(self.agent.handle(env)["status"], "duplicate")   # redelivery does not re-run
        self.assertEqual(len(calls), 1)
        self.agent.exporter = real
        second = self.say("seoyeon", "@ShiftPatch export")
        self.assertTrue(second["export_result"]["ok"], second)
        self.assertIn(f"-v{v}-", second["export_result"]["file"])           # same version, nothing changed
        self.assertEqual(self.version(), v)

    def test_folder_creation_failure_is_reported_not_raised(self):
        blocker = self.dir / "not-a-dir"
        blocker.write_text("x")
        res = exporter.export(self.store, self.room, "csv", blocker)
        self.assertFalse(res["ok"])
        self.assertEqual(res["version"], self.version())
        with self.store.snapshot() as c:
            row = c.execute("SELECT * FROM exports WHERE export_id=?", (res["export_id"],)).fetchone()
        self.assertEqual((row["state"], row["version"]), ("failed", self.version()))

    def test_snapshot_failure_is_reported(self):
        def fault(point):
            if point == "export_mkdir":
                raise PermissionError("synthetic")
        self.store.fault = fault
        res = exporter.export(self.store, self.room, "ics", self.dir / "exports")
        self.store.fault = None
        self.assertEqual((res["ok"], res["error"]), (False, "PermissionError"))

    def test_restart_closes_an_export_that_never_finished(self):
        self.agent.exporter = None                     # stands in for "process stopped mid-export"
        self.say("seoyeon", "@ShiftPatch 내보내기")
        self.assertFalse(any(o["idem_key"].endswith(":export") for o in self.outbox()))
        fresh = Agent(self.store, None)
        self.assertEqual(fresh.recover_unfinished_exports(), 1)
        self.assertEqual(fresh.recover_unfinished_exports(), 0)
        last = self.outbox()[-1]
        self.assertTrue(last["idem_key"].endswith(":export"))
        self.assertIn("다시 시작되면서 끝나지 않았습니다", last["body"])


class C09BridgeLifecycle(Base):
    """A malformed frame used to kill the reader while status stayed "connected"."""

    def setUp(self):
        super().setUp()
        self.fake = FakeSwitch(room_id=ROOM)
        self.room = ROOM
        roster.create_room(self.store, ROOM, "switch", "switch")
        roster.import_switch_links(self.store, ROOM, USERS)
        roster.import_roster(self.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")
        self.cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="test-key", room_id=ROOM)
        self.bridge = SwitchBridge(self.store, self.agent, self.cfg, read_timeout=0.8)

    def tearDown(self):
        self.bridge.stop()
        self.fake.close()
        super().tearDown()

    def start(self):
        self.bridge.start()
        self.assertTrue(wait(lambda: self.bridge.state == "connected" and self.bridge.generation is not None))

    def test_malformed_json_reconnects_from_processed_cursor(self):
        self.start()
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 2026-11-09 13:00-17:00",
                               timestamp=int(time.time() * 1000))
        self.assertTrue(wait(lambda: self.bridge.cursor == 1))
        v = self.version()
        self.fake.push_raw("{malformed JSON")
        self.assertTrue(wait(lambda: self.bridge.counters["bad_frames"] == 1))
        self.assertTrue(wait(lambda: len(self.fake.opens) >= 2, 8))
        self.assertEqual(self.fake.opens[-1]["start_from"], "1")
        self.assertTrue(wait(lambda: self.bridge.state == "connected"))
        self.assertEqual((self.bridge.cursor, self.version()), (1, v))
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 가능 13-15", timestamp=int(time.time() * 1000))
        self.assertTrue(wait(lambda: self.bridge.cursor == 2))      # still processing after the reconnect

    def test_non_integer_sequence_is_rejected_before_the_pipeline(self):
        self.start()
        v = self.version()
        self.fake.push_control({"event": "message", "id": "abc", "data": {"type": "message", "room_id": ROOM,
                                "payload": {"addressed": True, "sender": "@switch-user-jian:localhost",
                                            "message_id": "$x", "body": "@shiftpatch 가능 13-15",
                                            "timestamp": int(time.time() * 1000)}}})
        self.assertTrue(wait(lambda: self.bridge.counters["bad_frames"] == 1))
        self.assertEqual((self.bridge.cursor, self.version()), (0, v))

    def test_silent_socket_is_not_left_connected(self):
        self.start()
        opens = len(self.fake.opens)
        self.fake.silent = True                      # no pings, no FIN: half-open stand-in
        self.assertTrue(wait(lambda: self.bridge.counters["read_timeouts"] >= 1, 5))
        self.assertNotEqual(self.bridge.state, "connected")
        self.fake.silent = False
        self.assertTrue(wait(lambda: len(self.fake.opens) > opens and self.bridge.state == "connected", 8))

    def test_mocked_socket_from_the_critique_no_longer_stays_connected(self):
        class BadSocket:
            sock = None

            def recv(self):
                return "{malformed JSON"

            def close(self):
                pass
        with patch("shiftpatch.switch_bridge.WebSocket.connect", return_value=BadSocket()):
            t = threading.Thread(target=self.bridge._run, daemon=True)
            t.start()
            self.assertTrue(wait(lambda: self.bridge.counters["bad_frames"] >= 1))
            self.bridge._stop.set()
            t.join(5)
        self.assertNotEqual(self.bridge.state, "connected")
        self.assertIn("bad frame", self.bridge.detail)

    def test_parse_frame_rules(self):
        for raw in ["{", "[]", '"x"', '{"event":"message"}', '{"event":"message","id":-1}',
                    '{"event":"message","id":1.5}', '{"event":"message","id":true}',
                    '{"type":"connection_state","cursor":"x"}', '{"type":"gap","resumed_at":"soon"}']:
            with self.assertRaises(BadFrame, msg=raw):
                parse_frame(raw)
        self.assertEqual(parse_frame('{"event":"message","id":"7","data":{}}')["id"], 7)
        self.assertEqual(parse_frame('{"type":"ping"}'), {"type": "ping"})


class AccountsOnReview(Base):
    """KimiS5: the review screen showed `local:<staff_id>` for every room."""

    def test_switch_room_shows_linked_ids_and_blocks_unlinked_staff(self):
        room = "!acct:localhost"
        roster.create_room(self.store, room, "switch", "switch")
        roster.import_switch_links(self.store, room, {"@sw-minsu:x": "minsu", "@sw-jian:x": "jian",
                                                      "@sw-seoyeon:x": "seoyeon"})
        acc = {a["staff_id"]: a for a in roster.room_accounts(self.store, room)["accounts"]}
        self.assertEqual(acc["minsu"]["account"], "@sw-minsu:x")
        self.assertIsNone(acc["taeo"]["account"])
        self.assertFalse(any(str(a["account"]).startswith("local:") for a in acc.values()))
        ri, _ = roster.validate(ROWS, MAPPING, set(MAPPING), unlinked={"taeo"})
        self.assertIn("STAFF_HAS_NO_SWITCH_ACCOUNT", ri[2])
        with self.assertRaises(engine.Rejected) as e:
            roster.import_roster(self.store, room, ROWS, MAPPING, set(MAPPING), True, "test")
        self.assertIn("STAFF_HAS_NO_SWITCH_ACCOUNT", e.exception.info["issues"])

    def test_local_room_keeps_synthetic_accounts(self):
        acc = roster.room_accounts(self.store, roster.LOCAL_ROOM)
        self.assertEqual(acc["room_kind"], "local_demo")
        self.assertTrue(all(a["account"].startswith("local:") for a in acc["accounts"]))


class C06BoardAndReplyText(Base):
    """Placeholders, "again" on a first notice and a vague old-plan refusal."""

    def test_new_proposal_reply_lists_real_part_ids(self):
        self.import_roster()
        self.say("minsu", "@ShiftPatch unavailable 2026-11-09 13:00-17:00")
        self.say("jian", "@ShiftPatch available 13:00-15:00")
        r = self.say("taeo", "@ShiftPatch available 15:00-17:00")
        pid = self.board()["proposal"]["proposal_id"]
        self.assertIn(f"New proposal {pid}: Jian 13:00–15:00, Taeo 15:00–17:00.", r["reply"])
        self.assertIn(f"Jian: `accept {pid}-a` · Taeo: `accept {pid}-b`", r["reply"])
        self.assertIn(f"Then Seoyeon sends `confirm {pid}`.", r["reply"])
        with self.store.snapshot() as c:
            rm = engine.room(c, self.room)
            text = proposal_text(c, rm, "en", Names(engine.staff_rows(c, self.room), "en"))
        self.assertNotIn("?", text)
        self.assertIn(f"`accept {pid}-a`", text)

    def test_reopened_after_confirm_says_again_and_old_plan_refusal_is_specific(self):
        pid, parts, _ = self.main_trace_to_confirm()
        r = self.say("jian", "@ShiftPatch 불가 2026-11-09 13:00-15:00")
        self.assertIn("13:00–15:00이 다시 비었습니다", r["reply"])
        v = self.version()
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "ALREADY_CONFIRMED_CHANGED")
        self.assertIn(f"{josa(pid, '은/는')} 앞서 확정됐습니다", r["reply"])
        self.assertIn("지안님의 13:00–15:00이 빠져서", r["reply"])
        self.assertEqual(self.version(), v)
        view = next(p for p in self.board_proposals() if p["proposal_id"] == pid)
        self.assertEqual(view["state"], "confirmed")                    # history is not rewritten
        self.assertEqual(view["cuts"], [{"staff_id": "jian", "start": 780, "end": 900}])

    def board_proposals(self):
        with self.store.snapshot() as c:
            return [engine.proposal_view(c, self.room, r["proposal_id"])
                    for r in c.execute("SELECT proposal_id FROM proposals WHERE room_id=?", (self.room,))]

    def test_korean_particles_follow_the_last_sound(self):
        self.assertEqual([josa(w, "은/는") for w in ("P1", "P2", "P3", "P2-a", "P2-l", "지안", "태오")],
                         ["P1은", "P2는", "P3은", "P2-a는", "P2-l은", "지안은", "태오는"])
        self.assertEqual(josa("`확정 P2`", "을/를"), "`확정 P2`를")

    def test_english_am_pm_hint_uses_the_senders_verb(self):
        self.import_roster()
        r = self.say("jian", "@ShiftPatch unavailable 1-3")
        self.assertIn("`unavailable 13-15`", r["reply"])
