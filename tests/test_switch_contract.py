"""Switch adapter against the local CONTRACT DOUBLE (tests/fake_switch.py).
This is not a live Switch run."""
import sqlite3
import time
import types

from fake_switch import FakeSwitch
from harness import ROWS, MAPPING, Base

from shiftpatch import roster
from shiftpatch.outbox import Dispatcher
from shiftpatch.switch_bridge import SwitchBridge, SwitchConfig

ROOM = "!room:localhost"
USERS = {"@switch-user-seoyeon:localhost": "seoyeon", "@switch-user-minsu:localhost": "minsu",
         "@switch-user-jian:localhost": "jian", "@switch-user-taeo:localhost": "taeo"}


def wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class SwitchContract(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeSwitch(room_id=ROOM)
        self.room = ROOM
        roster.create_room(self.store, ROOM, "switch", "switch")
        roster.import_switch_links(self.store, ROOM, USERS)
        roster.import_roster(self.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")
        self.cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="test-key", room_id=ROOM)
        self.bridge = SwitchBridge(self.store, self.agent, self.cfg)
        self.dispatch = Dispatcher(self.store, {"switch": lambda room_id, row: self.bridge.post_reply(row["body"])})

    def tearDown(self):
        self.bridge.stop()
        self.fake.close()
        super().tearDown()

    def start(self):
        self.bridge.start()
        self.assertTrue(wait(lambda: self.bridge.state == "connected" and self.bridge.generation is not None))

    def test_probe_connect_and_pong_with_cursor(self):
        self.assertEqual(self.bridge.probe(), {"ok": True, "status": 200})
        self.start()
        q = self.fake.opens[0]
        self.assertEqual(q["rooms"], ROOM)
        self.assertEqual(q["filter"], "addressed")
        self.assertEqual(q["start_from"], "head")
        self.assertTrue(wait(lambda: len(self.fake.pongs) >= 2))
        self.assertEqual(self.bridge.rooms, [ROOM])

    def test_addressed_message_changes_state_and_reply_is_posted(self):
        self.start()
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 2026-11-09 13:00-17:00",
                               timestamp=int(time.time() * 1000))
        self.assertTrue(wait(lambda: self.bridge.cursor == 1))
        self.assertEqual(self.board()["gaps"], [(780, 1020)])
        self.dispatch.run_once()
        self.assertEqual(len(self.fake.posted), 1)
        self.assertEqual(self.fake.posted[0][0], ROOM)
        self.assertIn("13:00–17:00이 비었습니다", self.fake.posted[0][1])
        self.assertTrue(wait(lambda: 1 in self.fake.pongs))   # pong carries processed cursor

    def test_safeguards_unaddressed_unlinked_marker_self_other_room(self):
        self.start()
        now = int(time.time() * 1000)
        self.fake.push_message("@switch-user-jian:localhost", "가능 13-15", addressed=False, timestamp=now)
        self.fake.push_message("@switch-agent-other:localhost", "@shiftpatch 가능 13-15", timestamp=now)
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 가능 13-15", timestamp=now,
                               extra={"com.switch.auto_reply": True})
        self.fake.push_message("@switch-agent-sp:localhost", "@shiftpatch 가능 13-15", sender_name="shiftpatch", timestamp=now)
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 가능 13-15", room_id="!other:localhost", timestamp=now)
        v = self.version()
        self.assertTrue(wait(lambda: self.bridge.cursor == 5))
        self.assertEqual(self.version(), v)
        self.dispatch.run_once()
        self.assertEqual(len(self.fake.posted), 1)                 # only the unlinked notice
        self.assertIn("연결되지 않아", self.fake.posted[0][1])

    def test_reconnect_resumes_from_cursor_with_generation_and_dedups_replay(self):
        self.start()
        now = int(time.time() * 1000)
        f = self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 13-17", timestamp=now)
        self.assertTrue(wait(lambda: self.bridge.cursor == 1))
        v = self.version()
        gen = self.bridge.generation
        self.fake.drop(1012)
        self.assertTrue(wait(lambda: len(self.fake.opens) >= 2, 8))
        q = self.fake.opens[-1]
        self.assertEqual(q["start_from"], "1")
        self.assertEqual(q["expected_generation"], str(gen))
        self.assertEqual(q["connection_id"], self.fake.opens[0]["connection_id"])
        self.assertTrue(wait(lambda: self.bridge.state == "connected"))
        # server replays the same event under a new sequence (e.g. restored buffer): processed once
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 13-17", timestamp=now,
                               message_id=f["data"]["payload"]["message_id"])
        self.assertTrue(wait(lambda: self.bridge.cursor == 2))
        self.assertEqual(self.version(), v)

    def test_restart_keeps_connection_id_and_cursor(self):
        self.start()
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 13-17", timestamp=int(time.time() * 1000))
        self.assertTrue(wait(lambda: self.bridge.cursor == 1))
        cid = self.bridge.connection_id
        self.bridge.stop()
        b2 = SwitchBridge(self.store, self.agent, self.cfg)
        self.assertEqual((b2.connection_id, b2.cursor), (cid, 1))

    def test_gap_frame_moves_cursor_and_flags_next_reply(self):
        self.start()
        self.fake.push_control({"type": "gap", "from_sequence": 0, "resumed_at": 7, "resumed_position": 7,
                                "rooms": [ROOM], "all_rooms": False, "reason": "retention"})
        self.assertTrue(wait(lambda: self.bridge.cursor == 7))
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 표", timestamp=int(time.time() * 1000), seq=8)
        self.assertTrue(wait(lambda: self.bridge.cursor == 8))
        self.dispatch.run_once()
        self.assertIn("놓친 메시지", self.fake.posted[-1][1])

    def test_persistent_handler_failure_halts_before_later_sequences(self):
        """R01: a later good message must not move the cursor past a failed one."""
        real = self.agent.handle

        def broken(env):
            if "13:00-17:00" in env.body:
                raise sqlite3.OperationalError("disk I/O error")
            return real(env)
        self.bridge.agent = types.SimpleNamespace(handle=broken)
        self.fake.seq = 10                                  # head is 10 when we first connect
        self.start()
        self.assertTrue(wait(lambda: self.bridge.cursor == 10))
        now = int(time.time() * 1000)
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 2026-11-09 13:00-17:00", timestamp=now)
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 불가 2026-11-09 09:00-13:00", timestamp=now)
        v = self.version()
        self.assertTrue(wait(lambda: self.bridge.status()["state"] == "halted", 8))
        st = self.bridge.status()
        self.assertIn("sequence 11", st["detail"])
        self.assertEqual(st["cursor"], 10)
        time.sleep(0.5)                                     # sequence 12 stays unconsumed
        self.assertEqual(self.bridge.cursor, 10)
        self.assertEqual(self.version(), v)
        self.assertEqual(self.bridge._kv("cursor"), "10")
        self.assertNotIn(11, self.fake.pongs)
        self.assertNotIn(12, self.fake.pongs)
        opens = len(self.fake.opens)
        time.sleep(1.2)
        self.assertEqual(len(self.fake.opens), opens)       # no silent reconnect

        # Explicit recovery: restart resumes from 10, Switch replays 11 and 12, both apply once.
        self.bridge.stop()
        self.bridge = SwitchBridge(self.store, self.agent, self.cfg)
        self.assertIn("start_from=10", self.bridge.ws_url())
        self.start()
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 2026-11-09 13:00-17:00", timestamp=now, seq=11)
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 불가 2026-11-09 09:00-13:00", timestamp=now, seq=12)
        self.assertTrue(wait(lambda: self.bridge.cursor == 12, 8))
        self.assertEqual(self.version(), v + 2)
        self.assertEqual(self.board()["gaps"], [(540, 1020)])

    def test_taken_over_is_final(self):
        self.start()
        n = len(self.fake.opens)
        self.fake.push_control({"type": "evicted", "code": "taken_over", "reason": "another open"})
        self.assertTrue(wait(lambda: self.bridge.state == "stopped"))
        time.sleep(1.5)
        self.assertEqual(len(self.fake.opens), n)

    def test_bad_key_stops(self):
        self.bridge.cfg = SwitchConfig(base_url=self.fake.url, agent_id="agent-1", api_key="wrong", room_id=ROOM)
        self.bridge.start()
        self.assertTrue(wait(lambda: self.bridge.state == "stopped"))
        self.assertIn("4401", self.bridge.detail)

    def test_status_never_contains_key(self):
        self.start()
        self.assertNotIn("test-key", str(self.bridge.status()))
