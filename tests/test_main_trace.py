from harness import Base


class MainTrace(Base):
    def test_d01_main_trace_only_affected_hours_reopen(self):
        pid, parts, r = self.main_trace_to_confirm()
        self.assertEqual(r["code"], "CONFIRMED", r)
        self.assertEqual(self.cov(), [("09:00", "13:00", "jian", "original"), ("13:00", "15:00", "jian", "confirmed"),
                                      ("15:00", "17:00", "taeo", "confirmed"), ("17:00", "18:00", "taeo", "original")])
        r = self.say("jian", "@ShiftPatch 불가 2026-11-09 13:00-15:00")
        self.assertEqual(r["code"], "INABILITY_RECORDED", r)
        self.assertIn("13:00–15:00이 다시 비었습니다", r["reply"])
        self.assertIn("태오님의 15:00–17:00은 유지됩니다", r["reply"])
        self.assertEqual(self.cov(), [("09:00", "13:00", "jian", "original"), ("13:00", "15:00", None, "uncovered"),
                                      ("15:00", "17:00", "taeo", "confirmed"), ("17:00", "18:00", "taeo", "original")])
        # history keeps the acceptances and the confirmation
        kinds = self.history_kinds()
        for k in ("accepted", "confirmed", "inability"):
            self.assertIn(k, kinds)
        # old proposal cannot be re-confirmed over the new gap
        v = self.version()
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "ALREADY_CONFIRMED_CHANGED", r)
        self.assertEqual(self.version(), v)
        self.assertIn("confirm_rejected", self.history_kinds())

    def test_d02_acceptance_does_not_invalidate_proposal(self):
        pid, parts, r = self.main_trace_to_confirm()
        self.assertEqual(r["code"], "CONFIRMED")
        self.assertEqual(r["status"], "applied")
