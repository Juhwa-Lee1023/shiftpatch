"""Exports from one frozen snapshot. The version and every row are read in a
single read transaction, written to a temp file, fsynced and renamed into
place. A failure here never touches domain state."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import time
import uuid
from datetime import date as _date, timedelta
from pathlib import Path

from . import engine
from . import intervals as iv

STATUS_KO = {"original": "원 근무", "confirmed": "대체 확정", "uncovered": "미해결", "conflict": "중복 확인 필요"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def room_dir(room_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", room_id)


def neutralize(cell) -> str:
    s = "" if cell is None else str(cell)
    return "'" + s if s.startswith(FORMULA_START) else s


def take_snapshot(store, room_id):
    with store.snapshot() as c:
        rm = dict(engine.room(c, room_id))
        cov = engine.coverage(c, room_id)
        staff = engine.staff_rows(c, room_id)
        names = {k: (v["display_name"], v["display_name_en"]) for k, v in staff.items()}
    return {"room": rm, "version": rm["version"], "coverage": cov, "names": names}


def render_csv(snap, generated_iso):
    rm = snap["room"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["date", "duty", "start", "end", "assignee", "status", "status_ko", "version", "generated_at"])
    for sg in snap["coverage"]:
        name = snap["names"].get(sg["staff_id"], ("", ""))[0] if sg["staff_id"] else ""
        w.writerow([neutralize(x) for x in (rm["date"], rm["duty"], iv.fmt(sg["start"]), iv.fmt(sg["end"]), name,
                                            sg["status"], STATUS_KO.get(sg["status"], sg["status"]), snap["version"],
                                            generated_iso)])
    return buf.getvalue().encode("utf-8-sig")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_local(date: str, minute: int) -> str:
    """Local DATE-TIME for minute 0..1440 of `date`. RFC 5545 hours run
    00-23, so the end of day (24:00, minute 1440) is written as 00:00 of the
    next calendar day; month and year ends roll over with the date."""
    day = _date.fromisoformat(date) + timedelta(days=minute // 1440)
    m = minute % 1440
    return f"{day.strftime('%Y%m%d')}T{m // 60:02d}{m % 60:02d}00"


def render_ics(snap, generated_ms):
    """Confirmed holdings only (original + confirmed replacements). Gaps and
    pending proposals are left out on purpose. No sync, a static file."""
    rm = snap["room"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(generated_ms / 1000))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ShiftPatch//local snapshot//KO", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_escape('ShiftPatch ' + rm['date'] + ' v' + str(snap['version']))}"]
    for sg in snap["coverage"]:
        if sg["status"] not in ("original", "confirmed"):
            continue
        name = snap["names"].get(sg["staff_id"], ("?", "?"))[0]
        lines += ["BEGIN:VEVENT",
                  f"UID:{rm['room_id']}-v{snap['version']}-{sg['start']}-{sg['staff_id']}@shiftpatch.local",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID={rm['timezone']}:{ics_local(rm['date'], sg['start'])}",
                  f"DTEND;TZID={rm['timezone']}:{ics_local(rm['date'], sg['end'])}",
                  f"SUMMARY:{_ics_escape(name + ' · ' + rm['duty'])}",
                  f"DESCRIPTION:{_ics_escape(STATUS_KO[sg['status']] + ' · snapshot v' + str(snap['version']))}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def export(store, room_id, kind: str, out_dir: str | Path, now_ms: int | None = None):
    """Never raises for an I/O problem: snapshot, folder creation, render,
    write and rename all report back as {"ok": False, "error": ...} and a
    `failed` row, so the room and the board can say what happened. The
    file name carries the snapshot version it was rendered from."""
    now_ms = now_ms or int(time.time() * 1000)
    export_id = uuid.uuid4().hex[:12]
    snap, tmp = None, None
    try:
        snap = take_snapshot(store, room_id)
        out_dir = Path(out_dir) / room_dir(room_id)
        store.hit("export_mkdir")
        out_dir.mkdir(parents=True, exist_ok=True)
        iso = iv.local_iso(now_ms, snap["room"]["timezone"])
        data = render_csv(snap, iso) if kind == "csv" else render_ics(snap, now_ms)
        name = f"coverage-{snap['room']['date']}-v{snap['version']}-{export_id}.{kind}"
        tmp = out_dir / (name + ".tmp")
        store.hit("export_write")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        store.hit("export_publish")
        os.replace(tmp, out_dir / name)
    except engine.Rejected:
        raise
    except Exception as e:  # noqa: BLE001
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        version = snap["version"] if snap else None
        try:
            with store.tx() as c:
                if version is None:
                    version = engine.room(c, room_id)["version"]
                c.execute("INSERT INTO exports VALUES (?,?,?,?,NULL,NULL,NULL,'failed',?,?)",
                          (export_id, room_id, kind, version, type(e).__name__, now_ms))
        except Exception:  # noqa: BLE001 - the database itself may be the problem
            pass
        return {"ok": False, "export_id": export_id, "version": version, "error": type(e).__name__}
    digest = hashlib.sha256(data).hexdigest()
    with store.tx() as c:
        c.execute("INSERT INTO exports VALUES (?,?,?,?,?,?,?,'published',NULL,?)",
                  (export_id, room_id, kind, snap["version"], name, digest, len(snap["coverage"]), now_ms))
        engine.log(c, room_id, snap["version"], now_ms, "exported", None, fmt=kind, snapshot_version=snap["version"],
                   file=name)
    return {"ok": True, "export_id": export_id, "version": snap["version"], "file": name, "sha256": digest,
            "path": str(out_dir / name)}
