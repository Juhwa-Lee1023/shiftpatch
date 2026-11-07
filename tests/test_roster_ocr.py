"""Roster import guard rails and OCR. The Vision tests run the real local
helper on synthetic fixtures (skip if `swift` is missing)."""
import shutil
import unittest
from pathlib import Path

from harness import MAPPING, ROWS, Base

from shiftpatch import engine, ocr, roster

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "ocr"


class RosterImport(Base):
    def test_import_blocked_without_manager_approval(self):
        with self.assertRaises(engine.Rejected) as cm:
            roster.import_roster(self.store, self.room, ROWS, MAPPING, set(MAPPING), False, "test")
        self.assertEqual(cm.exception.code, "MANAGER_APPROVAL_REQUIRED")
        with self.store.snapshot() as c:
            self.assertEqual(engine.room(c, self.room)["roster_version"], 0)

    def test_import_blocked_without_confirmed_mapping(self):
        with self.assertRaises(engine.Rejected) as cm:
            roster.import_roster(self.store, self.room, ROWS, MAPPING, {"지안"}, True, "test")
        self.assertIn("MAPPING_NOT_CONFIRMED", cm.exception.info["issues"])

    def test_suggestion_is_not_confirmation(self):
        sug = roster.suggest_mapping(ROWS)
        self.assertEqual(sug["지안"], "jian")
        ri, gi = roster.validate(ROWS, sug, set())
        self.assertIn("MAPPING_NOT_CONFIRMED", roster.blocking(ri, gi))

    def test_no_live_roster_overwrite_after_events_begin(self):
        self.import_roster()
        self.say("minsu", "@ShiftPatch 불가 13-17")
        with self.assertRaises(engine.Rejected) as cm:
            self.import_roster()
        self.assertEqual(cm.exception.code, "COORDINATION_ALREADY_STARTED")

    def test_roles_never_come_from_the_file(self):
        rows = [dict(r) for r in ROWS]
        rows[0]["name"] = "서연"
        mapping = {"서연": "seoyeon", "민수": "minsu", "태오": "taeo"}
        self.import_roster(rows, mapping)
        with self.store.snapshot() as c:
            st = engine.staff_rows(c, self.room)
        self.assertEqual(st["seoyeon"]["role"], "manager")
        self.assertEqual({k: v["role"] for k, v in st.items() if k != "seoyeon"}, {"minsu": "staff", "jian": "staff", "taeo": "staff"})

    def test_validation_flags(self):
        rows = [
            {"name": "지안", "date": "11/9", "start": "9", "end": "1", "duty": "일반 문의"},
            {"name": "민지", "date": "2026-11-09", "start": "13:00", "end": "17:00", "duty": "일반 문의"},
            {"name": "태오", "date": "2026-11-09", "start": "16:00", "end": "18:00", "duty": "기타"},
            {"name": "=HYPERLINK(1)", "date": "2026-11-10", "start": "오후 5", "end": "18:15", "duty": "일반 문의"},
        ]
        ri, gi = roster.validate(rows, {"지안": "jian", "태오": "taeo", "민지": None}, {"지안", "태오"})
        self.assertIn("DATE_YEAR_OR_FORMAT_NEEDS_REVIEW", ri[0])
        self.assertIn("AMBIGUOUS_AM_PM", ri[0])
        self.assertIn("UNMAPPED_NAME", ri[1])
        self.assertIn("COLLISION", ri[1])
        self.assertIn("COLLISION", ri[2])
        self.assertIn("DUTY_MISMATCH", gi)
        self.assertIn("FORMULA_LIKE_TEXT", ri[3])
        self.assertIn("DATE_NOT_ROOM_DATE", ri[3])
        self.assertIn("AMBIGUOUS_AM_PM", ri[3])

    def test_two_names_one_account(self):
        rows = [dict(r) for r in ROWS]
        ri, gi = roster.validate(rows, {"지안": "jian", "민수": "jian", "태오": "taeo"}, {"지안", "민수", "태오"})
        self.assertIn("TWO_NAMES_ONE_ACCOUNT", gi)

    def test_csv_parse_bounds(self):
        good = "name,date,start,end,duty\n지안,2026-11-09,09:00,13:00,일반 문의\n".encode()
        self.assertEqual(len(roster.parse_csv(good)), 1)
        for bad, code in ((b"a,b\n1,2\n", "CSV_HEADER_MISMATCH"), (b"\xff\xfe\x00", "CSV_NOT_UTF8"),
                          (b"x" * (roster.MAX_CSV_BYTES + 1), "CSV_TOO_LARGE"), (b"", "CSV_EMPTY")):
            with self.assertRaises(ValueError) as cm:
                roster.parse_csv(bad)
            self.assertEqual(str(cm.exception), code)


class FileBounds(unittest.TestCase):
    def test_type_and_size(self):
        for data, code in ((b"", "EMPTY_FILE"), (b"GIF89a" + b"0" * 50, "UNSUPPORTED_TYPE"),
                           (b"%PDF-1.7", "UNSUPPORTED_TYPE"), (b"\x89PNG\r\n\x1a\n" + b"0" * (ocr.MAX_BYTES), "FILE_TOO_LARGE")):
            with self.assertRaises(ocr.OcrError) as cm:
                ocr.sniff(data)
            self.assertEqual(str(cm.exception), code)

    def test_pixel_bounds(self):
        import struct
        def png(w, h):
            return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
        for (w, h), code in (((100, 100), "IMAGE_TOO_SMALL"), ((7000, 400), "IMAGE_TOO_LARGE")):
            mime, ww, hh = ocr.sniff(png(w, h))
            with self.assertRaises(ocr.OcrError) as cm:
                ocr.check_pixels(ww, hh)
            self.assertEqual(str(cm.exception), code)

    def test_extract_unsupported_without_headers(self):
        d = ocr.extract({"observations": [{"text": "직원", "confidence": 1, "bbox": {"x": .1, "y": .8, "width": .1, "height": .05}}]})
        self.assertEqual(d["status"], "UNSUPPORTED_LAYOUT")


@unittest.skipIf(shutil.which("swift") is None, "swift not available")
class RealVision(unittest.TestCase):
    """Runs Apple Vision through ocr/roster_ocr.swift. Synthetic images only."""

    def setUp(self):
        self.drafts = ocr.DraftStore()

    def tearDown(self):
        self.drafts.discard_all()

    def draft(self, name):
        return self.drafts.create_from_image((FIX / f"{name}.png").read_bytes(), "local-demo")

    def test_clear_and_small_read_exactly_but_stay_unimported(self):
        for name in ("clear", "small"):
            d = self.draft(name)
            got = [[r[f] for f in ocr.FIELDS] for r in d["rows"]]
            self.assertEqual(got, [["지안", "2026-11-09", "09:00", "13:00", "일반 문의"],
                                   ["민수", "2026-11-09", "13:00", "17:00", "일반 문의"],
                                   ["태오", "2026-11-09", "17:00", "18:00", "일반 문의"]], name)
            self.assertEqual(d["status"], "NEEDS_MANAGER_REVIEW")
            ri, gi = roster.validate(d["rows"], roster.suggest_mapping(d["rows"]), set())
            self.assertIn("MAPPING_NOT_CONFIRMED", roster.blocking(ri, gi))

    def test_ambiguous_flags_year_and_am_pm(self):
        d = self.draft("ambiguous")
        ri, gi = roster.validate(d["rows"], roster.suggest_mapping(d["rows"]), {"지안", "민수", "태오"})
        b = roster.blocking(ri, gi)
        for code in ("DATE_YEAR_OR_FORMAT_NEEDS_REVIEW", "AMBIGUOUS_AM_PM", "START_NEEDS_EXPLICIT_24H_TIME"):
            self.assertIn(code, b)

    def test_unknown_name_and_collision(self):
        d = self.draft("unknown_collision")
        rows = d["rows"]
        ri, gi = roster.validate(rows, roster.suggest_mapping(rows), {r["name"] for r in rows})
        flat = [x for r in ri for x in r]
        self.assertIn("UNMAPPED_NAME", flat)
        self.assertIn("COLLISION", flat)

    def test_unsupported_layout(self):
        d = self.draft("unsupported")
        self.assertEqual(d["status"], "UNSUPPORTED_LAYOUT")
        self.assertEqual(d["rows"], [])

    def test_private_temp_removed_on_discard(self):
        import os
        import stat
        d = self.draft("small")
        self.assertEqual(stat.S_IMODE(os.stat(d["dir"]).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(d["image"]).st_mode), 0o600)
        self.drafts.discard(d["draft_id"])
        self.assertFalse(os.path.exists(d["dir"]))
