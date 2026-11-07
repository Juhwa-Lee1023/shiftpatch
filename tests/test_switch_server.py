"""Whole app wiring (config file → bridge → pipeline → outbox → POST reply)
against the CONTRACT DOUBLE. Still not a live Switch run."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import harness  # noqa: F401  (sys.path, AI off)
from fake_switch import FakeSwitch
from harness import MAPPING, ROWS
from test_switch_contract import ROOM, USERS, wait

from shiftpatch import roster
from shiftpatch.agent import board_link
from shiftpatch.interpret import Interpreter
from shiftpatch.server import App


class SwitchThroughApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeSwitch(room_id=ROOM)
        cfg = Path(self.tmp.name) / "switch.local.json"
        cfg.write_text(json.dumps({"base_url": self.fake.url, "agent_id": "agent-1", "api_key": "test-key", "room_id": ROOM}))
        self.app = App(Path(self.tmp.name) / "data", 0, ai=Interpreter(enabled=False), switch_config=cfg)
        roster.import_switch_links(self.app.store, ROOM, USERS)
        roster.import_roster(self.app.store, ROOM, ROWS, MAPPING, set(MAPPING), True, "test")

    def tearDown(self):
        try:
            self.assertTrue(self.app.close())    # threads joined before the data dir goes away
        finally:
            self.fake.close()
            self.tmp.cleanup()

    def test_message_in_switch_room_round_trips(self):
        self.app.start_background()
        self.assertTrue(wait(lambda: self.app.bridge.state == "connected"))
        self.assertEqual(self.app.switch_status()["state"], "connected")
        now = int(time.time() * 1000)
        self.fake.push_message("@switch-user-minsu:localhost", "@shiftpatch 불가 2026-11-09 13:00-17:00", timestamp=now)
        self.assertTrue(wait(lambda: len(self.fake.posted) == 1, 8))
        self.assertIn("13:00–17:00이 비었습니다", self.fake.posted[0][1])
        st = self.app.state(ROOM)
        self.assertEqual(st["gaps"], [(780, 1020)])
        self.assertIsNone(st["transcript"])            # no local transcript for a Switch room
        with self.assertRaises(PermissionError):       # the web actor picker cannot reach it
            self.app.local.post(ROOM, "seoyeon", "@ShiftPatch 표")

    def test_status_reply_links_the_same_switch_room(self):
        """R02: the board link in a Switch reply must open that room, not local-demo."""
        self.app.start_background()
        self.assertTrue(wait(lambda: self.app.bridge.state == "connected"))
        self.fake.push_message("@switch-user-jian:localhost", "@shiftpatch 표", timestamp=int(time.time() * 1000))
        self.assertTrue(wait(lambda: len(self.fake.posted) == 1, 8))
        link = next(w for w in self.fake.posted[0][1].split() if w.startswith("http://"))
        self.assertEqual(link, "http://127.0.0.1:0/?room=%21room%3Alocalhost#/board")
        u = urlsplit(link)
        self.assertEqual(parse_qs(u.query)["room"], [ROOM])
        self.assertEqual(u.fragment, "/board")

    def test_board_link_replaces_room_and_keeps_fragment(self):
        self.assertEqual(board_link("http://127.0.0.1:8765/?room=local-demo&x=1#/board", "a b/c"),
                         "http://127.0.0.1:8765/?x=1&room=a+b%2Fc#/board")
