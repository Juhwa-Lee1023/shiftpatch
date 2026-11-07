"""Snapshot exports (B01–B06)."""
import csv
import io
import threading

from harness import Base

from shiftpatch import engine, exporter


class Export(Base):
    def setUp(self):
        super().setUp()
        self.out = self.dir / "exports"

    def rows(self, res):
        data = (self.out / self.room / res["file"]).read_bytes().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(data)))

    def test_b01_csv_matches_board_and_version(self):
        self.main_trace_to_confirm()
        res = exporter.export(self.store, self.room, "csv", self.out)
        rows = self.rows(res)
        self.assertEqual([(r["start"], r["end"], r["status"]) for r in rows],
                         [(a, b, s) for a, b, _, s in self.cov()])
        self.assertTrue(all(int(r["version"]) == res["version"] == self.version() for r in rows))

    def test_b02_concurrent_confirm_cannot_mix_versions(self):
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13-17")
        self.say("taeo", "@ShiftPatch 가능 13-17")
        part = self.board()["proposal"]["parts"][0]["part_id"]
        self.say("taeo", f"@ShiftPatch 수락 {part}")
        pid = self.board()["proposal"]["proposal_id"]
        started, go = threading.Event(), threading.Event()
        orig = exporter.take_snapshot

        def slow_snapshot(store, room_id):
            with store.snapshot() as c:
                rm = dict(engine.room(c, room_id))
                started.set()
                go.wait(5)                       # confirm commits while we hold the read txn
                cov = engine.coverage(c, room_id)
                names = {k: (v["display_name"], v["display_name_en"]) for k, v in engine.staff_rows(c, room_id).items()}
            return {"room": rm, "version": rm["version"], "coverage": cov, "names": names}
        exporter.take_snapshot = slow_snapshot
        try:
            box = {}
            th = threading.Thread(target=lambda: box.update(r=exporter.export(self.store, self.room, "csv", self.out)))
            th.start()
            started.wait(5)
            r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
            self.assertEqual(r["code"], "CONFIRMED")
            go.set()
            th.join(10)
        finally:
            exporter.take_snapshot = orig
        rows = self.rows(box["r"])
        self.assertTrue(all(r["status"] != "confirmed" for r in rows))        # pre-confirm snapshot
        self.assertTrue(any(r["status"] == "uncovered" for r in rows))
        self.assertEqual({r["version"] for r in rows}, {str(box["r"]["version"])})
        self.assertLess(box["r"]["version"], self.version())

    def test_b03_failure_keeps_state_and_publishes_nothing(self):
        self.main_trace_to_confirm()
        v = self.version()

        def fault(point):
            if point == "export_publish":
                raise OSError("disk full (injected)")
        self.store.fault = fault
        res = exporter.export(self.store, self.room, "csv", self.out)
        self.store.fault = None
        self.assertFalse(res["ok"])
        self.assertEqual(self.version(), v)
        self.assertEqual(list((self.out / self.room).glob("*")), [])
        res2 = exporter.export(self.store, self.room, "csv", self.out)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["version"], v)

    def test_export_failure_reply_through_chat(self):
        self.main_trace_to_confirm()
        self.store.fault = lambda p: (_ for _ in ()).throw(OSError("x")) if p == "export_write" else None
        r = self.say("seoyeon", "@ShiftPatch 내보내기")
        self.store.fault = None
        self.assertFalse(r["export_result"]["ok"])
        self.assertIn("확정된 내용은 그대로입니다", self.outbox()[-1]["body"])

    def test_b04_formula_cells_neutralised(self):
        for s in ("=1+1", "+cmd", "-2", "@SUM(A1)", "\tx"):
            self.assertTrue(exporter.neutralize(s).startswith("'"))
        self.assertEqual(exporter.neutralize("지안"), "지안")
        self.import_roster()
        with self.store.tx() as c:
            c.execute("UPDATE staff SET display_name='=HYPERLINK(\"x\")' WHERE staff_id='jian'")
        res = exporter.export(self.store, self.room, "csv", self.out)
        self.assertEqual(self.rows(res)[0]["assignee"], "'=HYPERLINK(\"x\")")

    def test_b06_previous_versions_kept_and_ics_confirmed_only(self):
        self.main_trace_to_confirm()
        a = exporter.export(self.store, self.room, "csv", self.out)
        self.say("jian", "@ShiftPatch 불가 13-15")
        b = exporter.export(self.store, self.room, "csv", self.out)
        self.assertNotEqual(a["file"], b["file"])
        self.assertTrue((self.out / self.room / a["file"]).exists())
        ics = exporter.export(self.store, self.room, "ics", self.out)
        text = (self.out / self.room / ics["file"]).read_text()
        self.assertEqual(text.count("BEGIN:VEVENT"), 3)   # 09-13 Jian, 15-17 Taeo, 17-18 Taeo; gap left out
        self.assertNotIn("DTSTART;TZID=Asia/Seoul:20261109T130000", text)
        self.assertNotIn("미해결", text)
