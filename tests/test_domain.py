"""Domain counterexamples (plan IDs D03–D26 where they apply)."""
import random

from harness import MIN, Base


class Domain(Base):
    def setUp(self):
        super().setUp()
        self.import_roster()

    def open_parts(self):
        b = self.board()
        p = b["proposal"]
        return (p["proposal_id"], {x["staff_id"]: x["part_id"] for x in p["parts"]}) if p else (None, {})

    def gap_13_17(self):
        self.say("minsu", "@ShiftPatch 불가 2026-11-09 13:00-17:00")

    def test_d03_withdrawal_before_confirm_rejects_old_plan_keeps_others(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        self.say("taeo", "@ShiftPatch 가능 15-17")
        pid, parts = self.open_parts()
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        r = self.say("taeo", "@ShiftPatch 가능 취소")
        self.assertEqual(r["code"], "AVAILABILITY_WITHDRAWN")
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "PROPOSAL_STALE", r)
        new_pid, new_parts = self.open_parts()
        self.assertNotEqual(new_pid, pid)
        self.assertEqual(set(new_parts), {"jian"})               # Jian's response survives
        view = self.board()["proposal"]["parts"][0]
        self.assertTrue(view["accepted"])                         # carried, identical component
        self.assertEqual(view["carried_from"], parts["jian"])     # D04: visible link
        # partial proposal confirms only 13-15; 15-17 stays a gap (partial preservation)
        r = self.say("seoyeon", f"@ShiftPatch 확정 {new_pid}")
        self.assertEqual(r["code"], "CONFIRMED", r)
        self.assertEqual(self.board()["gaps"], [(900, 1020)])

    def test_d05_widened_interval_needs_fresh_acceptance(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 15-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        self.say("taeo", "@ShiftPatch 가능 14-17")   # newer, wider availability
        pid2, parts2 = self.open_parts()
        self.assertNotEqual(pid2, pid)
        p = self.board()["proposal"]["parts"][0]
        self.assertEqual((p["start"], p["end"]), (840, 1020))
        self.assertFalse(p["accepted"])                # 15-17 acceptance never stretched to 14-17
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid2}")
        self.assertEqual(r["code"], "ACCEPTANCE_MISSING")

    def test_d06_changed_facts_block_carry_forward(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        pid, parts = self.open_parts()
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        # Jian narrows: inability on 14-15 bumps the availability revision
        self.say("jian", "@ShiftPatch 불가 14:00-15:00")
        p = self.board()["proposal"]["parts"][0]
        self.assertEqual((p["start"], p["end"]), (780, 840))
        self.assertFalse(p["accepted"])
        self.assertIsNone(p["carried_from"])

    def test_d07_d08_confirm_then_partial_inability(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 13-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.say("taeo", "@ShiftPatch 불가 14:00-15:00")
        self.assertEqual(self.cov()[1:4], [("13:00", "14:00", "taeo", "confirmed"), ("14:00", "15:00", None, "uncovered"),
                                           ("15:00", "17:00", "taeo", "confirmed")])
        self.assertIn("confirmed", self.history_kinds())

    def test_d09_inability_before_confirm_rejects_old_confirm(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        self.say("taeo", "@ShiftPatch 가능 15-17")
        pid, parts = self.open_parts()
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        self.say("jian", "@ShiftPatch 불가 13-15")
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "PROPOSAL_STALE")
        self.assertNotIn(("13:00", "15:00", "jian", "confirmed"), self.cov())
        pid2, parts2 = self.open_parts()
        self.assertEqual(set(parts2), {"taeo"})
        self.assertTrue(self.board()["proposal"]["parts"][0]["accepted"])  # Taeo's identical component carried

    def test_d10_d16_duplicate_confirm_and_duplicate_source(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 13-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        env = self.env("seoyeon", f"@ShiftPatch 확정 {pid}", at=self.t + MIN, mid="dup-1")
        r1 = self.agent.handle(env)
        v = self.version()
        r2 = self.agent.handle(env)
        self.assertEqual(r1["code"], "CONFIRMED")
        self.assertEqual(r2["status"], "duplicate")
        self.assertEqual(self.version(), v)
        r3 = self.say("seoyeon", f"@ShiftPatch 확정 {pid}", advance=2)
        self.assertEqual(r3["code"], "ALREADY_CONFIRMED")
        with self.store.snapshot() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0], 1)

    def test_d11_adjacent_intervals_allowed(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        pid, parts = self.open_parts()
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "CONFIRMED")
        self.assertEqual(self.cov()[:2], [("09:00", "13:00", "jian", "original"), ("13:00", "15:00", "jian", "confirmed")])

    def test_d12_candidate_clipped_to_gap_never_extended(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 10-15")  # 10-13 she already holds; only 13-15 is in the gap
        p = self.board()["proposal"]["parts"]
        self.assertEqual([(x["staff_id"], x["start"], x["end"]) for x in p], [("jian", 780, 900)])

    def test_d13_no_candidate_keeps_gap(self):
        self.gap_13_17()
        self.assertIsNone(self.board()["proposal"])
        self.assertEqual(self.board()["gaps"], [(780, 1020)])

    def test_d14_partial_availability_leaves_remainder(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 14-16")
        p = self.board()["proposal"]["parts"]
        self.assertEqual([(x["start"], x["end"]) for x in p], [(840, 960)])

    def test_d17_proxy_and_other_persons_part_rejected(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        pid, parts = self.open_parts()
        v = self.version()
        r = self.say("seoyeon", f"@ShiftPatch 수락 {parts['jian']}")
        self.assertEqual(r["code"], "NOT_YOUR_PART")
        r = self.say("taeo", f"@ShiftPatch 수락 {parts['jian']}")
        self.assertEqual(r["code"], "NOT_YOUR_PART")
        self.assertEqual(self.version(), v)

    def test_staff_cannot_confirm(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 13-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        r = self.say("taeo", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "NOT_MANAGER")

    def test_d20_revoke_before_confirm_only_that_acceptance(self):
        self.gap_13_17()
        self.say("jian", "@ShiftPatch 가능 13-15")
        self.say("taeo", "@ShiftPatch 가능 15-17")
        pid, parts = self.open_parts()
        self.say("jian", f"@ShiftPatch 수락 {parts['jian']}")
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        r = self.say("taeo", f"@ShiftPatch 수락 취소 {parts['taeo']}")
        self.assertEqual(r["code"], "REVOKED")
        acc = {x["staff_id"]: x["accepted"] for x in self.board()["proposal"]["parts"]}
        self.assertEqual(acc, {"jian": True, "taeo": False})
        r = self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        self.assertEqual(r["code"], "ACCEPTANCE_MISSING")

    def test_revoked_consent_is_not_carried_into_a_new_proposal(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 15-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        self.say("taeo", f"@ShiftPatch 수락 취소 {parts['taeo']}")
        self.say("jian", "@ShiftPatch 가능 13-15")   # regenerates; Taeo's part identical
        tp = [x for x in self.board()["proposal"]["parts"] if x["staff_id"] == "taeo"][0]
        self.assertFalse(tp["accepted"])

    def test_revoke_after_confirm_is_distinct_from_inability(self):
        self.gap_13_17()
        self.say("taeo", "@ShiftPatch 가능 13-17")
        pid, parts = self.open_parts()
        self.say("taeo", f"@ShiftPatch 수락 {parts['taeo']}")
        self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
        v = self.version()
        r = self.say("taeo", f"@ShiftPatch 수락 취소 {parts['taeo']}")
        self.assertEqual(r["code"], "REVOKE_AFTER_CONFIRM")
        self.assertIn("불가 13:00-17:00", r["reply"])
        self.assertEqual(self.version(), v)

    def test_d24_unknown_or_cross_room_reference(self):
        r = self.say("jian", "@ShiftPatch 수락 P9-a")
        self.assertEqual(r["code"], "PART_NOT_FOUND")
        r = self.say("seoyeon", "@ShiftPatch 확정 P42")
        self.assertEqual(r["code"], "PROPOSAL_NOT_FOUND")

    def test_d25_reversed_and_overnight_ranges_not_saved(self):
        v = self.version()
        for body in ("@ShiftPatch 가능 15-13", "@ShiftPatch 가능 22:00-24:30", "@ShiftPatch 가능 13:15-15:00"):
            r = self.say("jian", body)
            self.assertNotEqual(r.get("status"), "applied", body)
        self.assertEqual(self.version(), v)

    def test_wrong_date_rejected(self):
        r = self.say("jian", "@ShiftPatch 가능 2026-11-10 13:00-15:00")
        self.assertIn("11/9", r["reply"])
        self.assertNotEqual(r.get("status"), "applied")

    def test_d26_random_event_orders_keep_invariants(self):
        rnd = random.Random(7)
        cmds = ["@ShiftPatch 가능 13-15", "@ShiftPatch 가능 15-17", "@ShiftPatch 가능 13-17", "@ShiftPatch 불가 13-15",
                "@ShiftPatch 불가 15-17", "@ShiftPatch 가능 취소", "@ShiftPatch 가능 14-16"]
        self.gap_13_17()
        for i in range(160):
            who = rnd.choice(["jian", "taeo"])
            roll = rnd.random()
            pid, parts = self.open_parts()
            if roll < 0.45:
                self.say(who, rnd.choice(cmds))
            elif roll < 0.7 and parts.get(who):
                self.say(who, f"@ShiftPatch 수락 {parts[who]}")
            elif roll < 0.8 and parts.get(who):
                self.say(who, f"@ShiftPatch 수락 취소 {parts[who]}")
            elif pid:
                self.say("seoyeon", f"@ShiftPatch 확정 {pid}")
            cov = self.cov()
            self.assertFalse([c for c in cov if c[3] == "conflict"], cov)       # never double coverage
            self.assertEqual(cov[0][0], "09:00")
            self.assertEqual(cov[-1][1], "18:00")
            for a, b in zip(cov, cov[1:]):
                self.assertEqual(a[1], b[0])                                   # contiguous, no holes
            gaps = [(c[0], c[1]) for c in cov if c[3] == "uncovered"]
            from shiftpatch import intervals as iv
            self.assertEqual(gaps, [(iv.fmt(s), iv.fmt(e)) for s, e in self.board()["gaps"]])
        kinds = self.history_kinds()
        self.assertGreater(len(kinds), 20)
