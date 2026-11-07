"""Shared test harness: a fresh SQLite file per test, the synthetic local
demo room with the canonical roster imported, and a `say` helper that
builds trusted envelopes the way the local demo adapter does."""
from __future__ import annotations

import itertools
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SHIFTPATCH_AI", "off")

from shiftpatch import engine, exporter, roster
from shiftpatch import intervals as iv
from shiftpatch.agent import Agent, TrustedEnvelope
from shiftpatch.db import Store

ROWS = [
    {"name": "지안", "date": "2026-11-09", "start": "09:00", "end": "13:00", "duty": "일반 문의"},
    {"name": "민수", "date": "2026-11-09", "start": "13:00", "end": "17:00", "duty": "일반 문의"},
    {"name": "태오", "date": "2026-11-09", "start": "17:00", "end": "18:00", "duty": "일반 문의"},
]
MAPPING = {"지안": "jian", "민수": "minsu", "태오": "taeo"}
T0 = iv.ms_for_local("2026-11-08", 21 * 60, "Asia/Seoul")
MIN = 60 * 1000


class Base(unittest.TestCase):
    ai = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir / "t.db")
        roster.ensure_local_demo_room(self.store)
        self.room = roster.LOCAL_ROOM
        self.ids = itertools.count(1)
        self.t = T0
        self.agent = Agent(self.store, self.ai,
                           exporter=lambda room_id, kind: exporter.export(self.store, room_id, kind, self.dir / "exports"))

    def tearDown(self):
        self.tmp.cleanup()

    def import_roster(self, rows=ROWS, mapping=MAPPING):
        return roster.import_roster(self.store, self.room, rows, mapping, set(mapping), True, "test")

    def env(self, who, body, at=None, received=None, mid=None, **kw):
        at = self.t if at is None else at
        return TrustedEnvelope(source="local_demo", room_id=self.room, message_id=mid or f"m{next(self.ids)}",
                               sender=f"local:{who}", sender_name=who, body=body, created_ms=at,
                               received_ms=at if received is None else received, **kw)

    def say(self, who, body, advance=1, **kw):
        self.t += advance * MIN
        return self.agent.handle(self.env(who, body, **kw))

    def cov(self):
        with self.store.snapshot() as c:
            return [(iv.fmt(s["start"]), iv.fmt(s["end"]), s["staff_id"], s["status"])
                    for s in engine.coverage(c, self.room)]

    def version(self):
        with self.store.snapshot() as c:
            return engine.room(c, self.room)["version"]

    def board(self):
        with self.store.snapshot() as c:
            return engine.board(c, self.room)

    def history_kinds(self):
        with self.store.snapshot() as c:
            return [r["kind"] for r in c.execute("SELECT kind FROM history WHERE room_id=? ORDER BY id", (self.room,))]

    def outbox(self):
        with self.store.snapshot() as c:
            return [dict(r) for r in c.execute("SELECT * FROM outbox WHERE room_id=? ORDER BY id", (self.room,))]

    def main_trace_to_confirm(self):
        """Canonical trace up to the manager's confirmation, exact commands."""
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 2026-11-09 13:00-17:00")
        self.say("jian", "@ShiftPatch 가능 2026-11-09 13:00-15:00")
        self.say("taeo", "@ShiftPatch 가능 2026-11-09 15:00-17:00")
        b = self.board()
        pid = b["proposal"]["proposal_id"]
        parts = {p["staff_id"]: p["part_id"] for p in b["proposal"]["parts"]}
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        return pid, parts, r


def dumps(x):
    return json.dumps(x, ensure_ascii=False, indent=1)
