"""Roster image → editable draft. Real recognition runs in the local Apple
Vision helper (ocr/roster_ocr.swift). The image lives only in a private
0700 temp directory until the manager approves or discards the draft.
Nothing here imports a roster; `roster.import_roster` does, after review."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
HELPER_SRC = APP / "ocr" / "roster_ocr.swift"
HELPER_BIN = APP / "build" / "roster_ocr"
MODULE_CACHE = APP / "build" / "module-cache"
MAX_BYTES = 8 * 1024 * 1024
MIN_PX, MAX_PX = 320, 6000
FIELDS = ["name", "date", "start", "end", "duty"]
HEADER_ALIASES = {
    "name": {"이름", "직원", "name", "staff"},
    "date": {"날짜", "일자", "date"},
    "start": {"시작", "start"},
    "end": {"종료", "끝", "end"},
    "duty": {"업무", "duty", "task"},
}
TMP_PREFIX = "shiftpatch-ocr-"


class OcrError(Exception):
    pass


def sniff(data: bytes):
    """Return (mime, width|None, height|None) or raise OcrError."""
    if len(data) == 0:
        raise OcrError("EMPTY_FILE")
    if len(data) > MAX_BYTES:
        raise OcrError("FILE_TOO_LARGE")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise OcrError("UNREADABLE_IMAGE")
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", None, None
    raise OcrError("UNSUPPORTED_TYPE")


def check_pixels(w, h):
    if w is None:
        return
    if w < MIN_PX or h < MIN_PX // 2:
        raise OcrError("IMAGE_TOO_SMALL")
    if w > MAX_PX or h > MAX_PX:
        raise OcrError("IMAGE_TOO_LARGE")


def helper_command(image_path: str):
    if HELPER_BIN.exists() and os.access(HELPER_BIN, os.X_OK):
        return [str(HELPER_BIN), image_path, str(MIN_PX), str(MAX_PX)]
    swift = shutil.which("swift")
    if swift is None:
        raise OcrError("OCR_HELPER_UNAVAILABLE")
    MODULE_CACHE.mkdir(parents=True, exist_ok=True)
    return [swift, "-module-cache-path", str(MODULE_CACHE), str(HELPER_SRC), image_path, str(MIN_PX), str(MAX_PX)]


def recognize(image_path: str, timeout_s: float = 120.0) -> dict:
    proc = subprocess.run(helper_command(image_path), capture_output=True, text=True, timeout=timeout_s, shell=False)
    try:
        out = json.loads(proc.stdout or "{}")
    except ValueError:
        raise OcrError("OCR_HELPER_BAD_OUTPUT")
    if "error" in out:
        raise OcrError(out["error"])
    if proc.returncode != 0:
        raise OcrError("OCR_HELPER_FAILED")
    return out


def _header_field(text: str):
    t = text.strip().lower()
    for f, names in HEADER_ALIASES.items():
        if t in names:
            return f
    return None


def extract(ocr: dict) -> dict:
    """Fixed five-column table: one header per field, rows by y position.
    Anything else is UNSUPPORTED_LAYOUT; the manager can still type or
    upload CSV."""
    obs = ocr.get("observations", [])
    headers = {}
    for o in obs:
        f = _header_field(o["text"])
        if f and f not in headers:
            headers[f] = o
    if set(headers) != set(FIELDS):
        return {"status": "UNSUPPORTED_LAYOUT", "rows": [], "found_headers": sorted(headers)}
    hs = [headers[f] for f in FIELDS]
    xs = [o["bbox"]["x"] for o in hs]
    if xs != sorted(xs):
        return {"status": "UNSUPPORTED_LAYOUT", "rows": [], "found_headers": FIELDS}
    bounds = [(xs[i] + xs[i + 1]) / 2 for i in range(4)]
    header_y = min(o["bbox"]["y"] for o in hs)
    row_h = max(0.02, sum(o["bbox"]["height"] for o in hs) / 5 * 0.7)
    groups = []
    for o in sorted(obs, key=lambda o: -(o["bbox"]["y"] + o["bbox"]["height"] / 2)):
        b = o["bbox"]
        cy = b["y"] + b["height"] / 2
        if cy >= header_y:
            continue
        col = sum((b["x"] + b["width"] / 2) > x for x in bounds)
        grp = next((g for g in groups if abs(g["y"] - cy) < row_h), None)
        if grp is None:
            grp = {"y": cy, "cells": {}}
            groups.append(grp)
        if col in grp["cells"]:
            return {"status": "UNSUPPORTED_LAYOUT", "rows": [], "reason": "two_texts_in_one_cell"}
        grp["cells"][col] = o
    rows = []
    for g in sorted(groups, key=lambda g: -g["y"]):
        cells = {FIELDS[i]: g["cells"].get(i) for i in range(5)}
        row = {f: (cells[f]["text"].strip() if cells[f] else "") for f in FIELDS}
        issues = []
        if any(cells[f] is None for f in FIELDS):
            issues.append("EMPTY_CELL")
        if any(cells[f] is not None and cells[f]["confidence"] < 0.8 for f in FIELDS):
            issues.append("OCR_SCORE_REVIEW_SIGNAL_NOT_ACCURACY")
        row["ocr_issues"] = issues
        row["cells"] = {f: ({"confidence": round(cells[f]["confidence"], 2), "bbox": cells[f]["bbox"]} if cells[f] else None)
                        for f in FIELDS}
        rows.append(row)
    if not rows:
        return {"status": "UNSUPPORTED_LAYOUT", "rows": [], "reason": "no_rows"}
    return {"status": "NEEDS_MANAGER_REVIEW", "rows": rows}


def normalize_cell(field: str, text: str) -> str:
    """Light, visible normalisation only (fullwidth colon, spaces)."""
    t = text.replace("：", ":").strip()
    if field in ("start", "end"):
        t = re.sub(r"\s+", "", t)
    return t


class DraftStore:
    """In-memory drafts. The image stays in a private temp dir per draft."""

    def __init__(self):
        self.drafts = {}

    def create_from_image(self, data: bytes, room_id: str):
        mime, w, h = sniff(data)
        check_pixels(w, h)
        d = tempfile.mkdtemp(prefix=TMP_PREFIX)
        os.chmod(d, 0o700)
        path = os.path.join(d, "source.png" if mime == "image/png" else "source.jpg")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        started = time.monotonic()
        try:
            ocr = recognize(path)
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        draft = extract(ocr)
        for r in draft["rows"]:
            for f in FIELDS:
                r[f] = normalize_cell(f, r[f])
        draft_id = uuid.uuid4().hex[:10]
        self.drafts[draft_id] = {
            "draft_id": draft_id, "room_id": room_id, "source": "ocr", "mime": mime, "dir": d, "image": path,
            "width": ocr.get("width"), "height": ocr.get("height"), "engine": ocr.get("engine"),
            "seconds": round(time.monotonic() - started, 2), "status": draft["status"], "rows": draft["rows"],
            "detail": {k: v for k, v in draft.items() if k not in ("rows", "status")}, "created": time.time()}
        return self.drafts[draft_id]

    def create_from_rows(self, rows, room_id: str, source: str):
        draft_id = uuid.uuid4().hex[:10]
        self.drafts[draft_id] = {"draft_id": draft_id, "room_id": room_id, "source": source, "image": None, "dir": None,
                                 "status": "NEEDS_MANAGER_REVIEW", "rows": rows, "detail": {}, "created": time.time()}
        return self.drafts[draft_id]

    def get(self, draft_id):
        return self.drafts.get(draft_id)

    def discard(self, draft_id):
        d = self.drafts.pop(draft_id, None)
        if d and d.get("dir"):
            shutil.rmtree(d["dir"], ignore_errors=True)
        return d is not None

    def discard_all(self):
        for k in list(self.drafts):
            self.discard(k)


def purge_stale_temp(max_age_s: float = 3600):
    """Remove leftover private OCR temp dirs from an earlier crashed run."""
    root = Path(tempfile.gettempdir())
    now = time.time()
    for p in root.glob(TMP_PREFIX + "*"):
        try:
            if p.is_dir() and now - p.stat().st_mtime > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
