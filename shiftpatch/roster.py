"""Initial roster: rooms, the fixed synthetic directory, draft validation
and the one-time import a manager approves explicitly."""
from __future__ import annotations

import csv
import io
import re
import time

from . import engine
from . import intervals as iv

LOCAL_ROOM = "local-demo"
DATE = "2026-11-09"
TZ = "Asia/Seoul"
DUTY = "일반 고객문의 응대"
SCENARIO_START_MS = iv.ms_for_local("2026-11-08", 21 * 60, TZ)  # Sun 11/8 21:00 KST, synthetic

# Fixed synthetic people. Roles live here, in local config the manager owns,
# never in an uploaded CSV or an OCR result.
DIRECTORY = [
    {"staff_id": "seoyeon", "name": "서연", "name_en": "Seoyeon", "role": "manager", "local_user": "local:seoyeon"},
    {"staff_id": "minsu", "name": "민수", "name_en": "Minsu", "role": "staff", "local_user": "local:minsu"},
    {"staff_id": "jian", "name": "지안", "name_en": "Jian", "role": "staff", "local_user": "local:jian"},
    {"staff_id": "taeo", "name": "태오", "name_en": "Taeo", "role": "staff", "local_user": "local:taeo"},
]
BY_ID = {d["staff_id"]: d for d in DIRECTORY}

BLOCKING = {"DATE_YEAR_OR_FORMAT_NEEDS_REVIEW", "DATE_NOT_ROOM_DATE", "START_NEEDS_EXPLICIT_24H_TIME",
            "END_NEEDS_EXPLICIT_24H_TIME", "AMBIGUOUS_AM_PM", "NON_POSITIVE_OR_OVERNIGHT", "NOT_30_MIN_BOUNDARY",
            "DUTY_MISMATCH", "UNMAPPED_NAME", "MAPPING_NOT_CONFIRMED", "TWO_NAMES_ONE_ACCOUNT", "COLLISION",
            "EMPTY_CELL", "STAFF_HAS_NO_SWITCH_ACCOUNT", "START_NOT_A_CLOCK_TIME", "END_NOT_A_CLOCK_TIME"}
CSV_HEADERS = ["name", "date", "start", "end", "duty"]
MAX_CSV_BYTES = 64 * 1024
MAX_ROWS = 40
# 00:00-23:59, plus 24:00 as the end of the day. 24:30, 24:01 and 13:60 are not times.
HHMM = re.compile(r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$")
CLOCK_SHAPE = re.compile(r"^\d{1,2}:\d{2}$")


def now_ms() -> int:
    return int(time.time() * 1000)


def create_room(store, room_id, kind, label, offset_ms=0):
    with store.tx() as c:
        if c.execute("SELECT 1 FROM rooms WHERE room_id=?", (room_id,)).fetchone():
            return False
        c.execute("INSERT INTO rooms(room_id, kind, label, date, timezone, duty, clock_offset_ms, created_ms) "
                  "VALUES (?,?,?,?,?,?,?,?)", (room_id, kind, label, DATE, TZ, DUTY, offset_ms, now_ms()))
        for d in DIRECTORY:
            c.execute("INSERT INTO staff(room_id, staff_id, display_name, display_name_en, role) VALUES (?,?,?,?,?)",
                      (room_id, d["staff_id"], d["name"], d["name_en"], d["role"]))
        return True


def ensure_local_demo_room(store):
    return create_room(store, LOCAL_ROOM, "local_demo", "로컬 합성 시연 방 / Local synthetic demo room",
                       SCENARIO_START_MS - now_ms())


ROOM_TABLES = ["staff", "links", "base_shifts", "availability", "inability", "proposals", "parts", "acceptances",
               "assignments", "pending", "watermarks", "exec_ctx", "processed", "history", "outbox", "exports"]


def reset_local_demo(store):
    with store.tx() as c:
        for t in ROOM_TABLES:
            c.execute(f"DELETE FROM {t} WHERE room_id=?", (LOCAL_ROOM,))
        c.execute("DELETE FROM rooms WHERE room_id=?", (LOCAL_ROOM,))
    ensure_local_demo_room(store)


def room_now_ms(room_row) -> int:
    return now_ms() + room_row["clock_offset_ms"]


# ---------------------------------------------------------------- drafts

def parse_csv(data: bytes):
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV_TOO_LARGE")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV_NOT_UTF8")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(x.strip() for x in r)]
    if not rows:
        raise ValueError("CSV_EMPTY")
    head = [h.strip().lower() for h in rows[0]]
    if head != CSV_HEADERS:
        raise ValueError("CSV_HEADER_MISMATCH")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError("CSV_TOO_MANY_ROWS")
    out = []
    for r in rows[1:]:
        r = (r + [""] * 5)[:5]
        out.append({k: v.strip() for k, v in zip(CSV_HEADERS, r)})
    return out


def suggest_mapping(rows):
    """Exact display-name match is only a suggestion; the manager confirms."""
    names = {r["name"] for r in rows}
    sug = {}
    for n in names:
        hit = [d["staff_id"] for d in DIRECTORY if n in (d["name"], d["name_en"])]
        sug[n] = hit[0] if len(hit) == 1 else None
    return sug


def validate(rows, mapping: dict, confirmed_names: set, room_date=DATE, unlinked=frozenset()):
    """Returns (row_issues list[list[str]], global_issues list[str]).
    `unlinked`: staff ids with no chat account in a Switch room."""
    row_issues = []
    for r in rows:
        issues = list(r.get("ocr_issues", []))
        issues = [i for i in issues if i == "OCR_SCORE_REVIEW_SIGNAL_NOT_ACCURACY"]
        for k in CSV_HEADERS:
            if not r.get(k, "").strip():
                issues.append("EMPTY_CELL")
                break
        if re.search(r"오전|오후|\b[ap]\.?m\.?\b", f"{r.get('start', '')} {r.get('end', '')}", re.IGNORECASE):
            issues.append("AMBIGUOUS_AM_PM")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.get("date", "")):
            issues.append("DATE_YEAR_OR_FORMAT_NEEDS_REVIEW")
        elif r["date"] != room_date:
            issues.append("DATE_NOT_ROOM_DATE")
        ok_time = True
        for f in ("start", "end"):
            v = r.get(f, "")
            if not HHMM.fullmatch(v):
                ok_time = False
                if re.fullmatch(r"\d{1,2}", v) and int(v) <= 12:
                    issues.append("AMBIGUOUS_AM_PM")
                # "24:30" or "13:60" is written as a clock time but is not one: say so for this row
                issues.append(f.upper() + ("_NOT_A_CLOCK_TIME" if CLOCK_SHAPE.fullmatch(v) else "_NEEDS_EXPLICIT_24H_TIME"))
        if ok_time:
            s, e = iv.parse_hhmm(r["start"]), iv.parse_hhmm(r["end"])
            bad = iv.valid_write_range(s, e)
            if bad:
                issues.append(bad)
        name = r.get("name", "")
        if name and not mapping.get(name):
            issues.append("UNMAPPED_NAME")
        elif name and name not in confirmed_names:
            issues.append("MAPPING_NOT_CONFIRMED")
        if name and mapping.get(name) in unlinked:
            issues.append("STAFF_HAS_NO_SWITCH_ACCOUNT")
        if re.match(r"^[=+\-@\t\r]", name):
            issues.append("FORMULA_LIKE_TEXT")
        row_issues.append(sorted(set(issues)))
    global_issues = []
    duties = {r.get("duty", "") for r in rows}
    if len(duties) > 1:
        global_issues.append("DUTY_MISMATCH")
    used = {}
    for n, sid in mapping.items():
        if sid and n in {r["name"] for r in rows}:
            used.setdefault(sid, set()).add(n)
    if any(len(v) > 1 for v in used.values()):
        global_issues.append("TWO_NAMES_ONE_ACCOUNT")
    timed = []
    for i, r in enumerate(rows):
        if HHMM.fullmatch(r.get("start", "")) and HHMM.fullmatch(r.get("end", "")):
            timed.append((i, iv.parse_hhmm(r["start"]), iv.parse_hhmm(r["end"])))
    for a in range(len(timed)):
        for b in range(a + 1, len(timed)):
            i, s1, e1 = timed[a]
            j, s2, e2 = timed[b]
            if iv.overlaps(s1, e1, s2, e2):
                row_issues[i] = sorted(set(row_issues[i] + ["COLLISION"]))
                row_issues[j] = sorted(set(row_issues[j] + ["COLLISION"]))
    if not rows:
        global_issues.append("NO_ROWS")
    return row_issues, global_issues


def blocking(row_issues, global_issues):
    return sorted({i for ri in row_issues for i in ri if i in BLOCKING} | set(global_issues))


def import_roster(store, room_id, rows, mapping, confirmed_names, manager_approved: bool, source: str):
    """One-time import. Refuses without explicit approval, with any blocking
    issue, or once coordination has started in the room."""
    if not manager_approved:
        raise engine.Rejected("MANAGER_APPROVAL_REQUIRED")
    row_issues, global_issues = validate(rows, mapping, confirmed_names)
    block = blocking(row_issues, global_issues)
    if block:
        raise engine.Rejected("DRAFT_HAS_BLOCKING_ISSUES", issues=block)
    with store.tx() as c:
        rm = engine.room(c, room_id)
        if rm["events_started"]:
            raise engine.Rejected("COORDINATION_ALREADY_STARTED")
        if rm["kind"] == "switch":
            linked = {r["staff_id"] for r in c.execute("SELECT staff_id FROM links WHERE room_id=?", (room_id,))}
            missing = sorted({mapping[r["name"]] for r in rows} - linked)
            if missing:
                raise engine.Rejected("DRAFT_HAS_BLOCKING_ISSUES", issues=["STAFF_HAS_NO_SWITCH_ACCOUNT"], staff=missing)
        c.execute("DELETE FROM base_shifts WHERE room_id=?", (room_id,))
        rv = rm["roster_version"] + 1
        c.execute("UPDATE rooms SET roster_version=?, duty=? WHERE room_id=?", (rv, rows[0]["duty"], room_id))
        if rm["kind"] == "local_demo":
            # Fixed synthetic accounts. Switch rooms keep the links the
            # manager imported with import_switch_links.
            c.execute("DELETE FROM links WHERE room_id=?", (room_id,))
            for d in DIRECTORY:
                c.execute("INSERT INTO links(room_id, platform_user_id, staff_id, link_rev) VALUES (?,?,?,?)",
                          (room_id, d["local_user"], d["staff_id"], rv))
        for i, r in enumerate(sorted(rows, key=lambda r: r["start"])):
            c.execute("INSERT INTO base_shifts VALUES (?,?,?,?,?,?)",
                      (room_id, f"R{i + 1}", mapping[r["name"]], iv.parse_hhmm(r["start"]), iv.parse_hhmm(r["end"]), rv))
        v = engine.bump(c, room_id)
        engine.log(c, room_id, v, room_now_ms(rm), "roster_imported", "seoyeon", source=source, rows=len(rows),
                   roster_version=rv)
    return {"roster_version": rv, "rows": len(rows)}


def room_accounts(store, room_id):
    """What the review screen shows next to each staff member: the chat
    account that will act as them in this room. Local demo rooms use the
    fixed synthetic accounts; Switch rooms show the opaque participant id
    imported with import_switch_links, or None when nobody is linked."""
    with store.snapshot() as c:
        rm = engine.room(c, room_id)
        links = {r["staff_id"]: r["platform_user_id"] for r in c.execute("SELECT * FROM links WHERE room_id=?", (room_id,))}
    out = []
    for d in DIRECTORY:
        if rm["kind"] == "local_demo":
            out.append({"staff_id": d["staff_id"], "account": d["local_user"], "kind": "local_synthetic"})
        else:
            out.append({"staff_id": d["staff_id"], "account": links.get(d["staff_id"]), "kind": "switch"})
    return {"room_kind": rm["kind"], "accounts": out}


def import_switch_links(store, room_id, links: dict):
    """links: {opaque Switch participant id: staff_id}. Local admin only.

    A staff member whose account changes gets a link revision higher than any
    used before in the room, and every confirmation question still open for
    them is closed. A question asked to account A can never be answered by a
    newly linked account B. Unchanged links keep their revision. Returns
    {"linked": n, "closed_questions": [...]}."""
    with store.tx() as c:
        rm = engine.room(c, room_id)
        if rm["kind"] != "switch":
            raise engine.Rejected("NOT_A_SWITCH_ROOM")
        if rm["events_started"]:
            raise engine.Rejected("COORDINATION_ALREADY_STARTED")
        if len(set(links.values())) != len(links) or any(s not in BY_ID for s in links.values()):
            raise engine.Rejected("BAD_LINKS")
        old = {r["staff_id"]: (r["platform_user_id"], r["link_rev"])
               for r in c.execute("SELECT * FROM links WHERE room_id=?", (room_id,))}
        top = max([rev for _, rev in old.values()] + [0])
        new = {sid: pid for pid, sid in links.items()}
        changed = {sid for sid in set(old) | set(new) if old.get(sid, (None,))[0] != new.get(sid)}
        closed = []
        for sid in sorted(changed):
            for r in c.execute("SELECT q_id FROM pending WHERE room_id=? AND staff_id=? AND state='open'",
                               (room_id, sid)).fetchall():
                c.execute("UPDATE pending SET state='stale' WHERE room_id=? AND q_id=?", (room_id, r["q_id"]))
                closed.append(r["q_id"])
        c.execute("DELETE FROM links WHERE room_id=?", (room_id,))
        for pid, sid in links.items():
            rev = old[sid][1] if sid in old and sid not in changed else top + 1
            c.execute("INSERT INTO links(room_id, platform_user_id, staff_id, link_rev) VALUES (?,?,?,?)",
                      (room_id, pid, sid, rev))
        c.execute("DELETE FROM unlinked_seen WHERE room_id=? AND platform_user_id IN "
                  "(SELECT platform_user_id FROM links WHERE room_id=?)", (room_id, room_id))
        if changed and old:
            engine.log(c, room_id, rm["version"], room_now_ms(rm), "links_changed", None,
                       staff=sorted(changed), closed_questions=closed)
    return {"linked": len(links), "closed_questions": closed}


def link_observed_sender(store, room_id, sender_id: str, staff_id: str, now_ms: int | None = None):
    """Link one sender that has actually written to the agent in this room
    (seen in unlinked_seen) to `staff_id`, keeping the other links. An id that
    was never observed is refused: participant ids are opaque and are not
    derived from another account's id or a display name."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    with store.snapshot() as c:
        seen = {r["platform_user_id"] for r in engine.unlinked_seen(c, room_id, now_ms)}
        current = {r["platform_user_id"]: r["staff_id"] for r in c.execute("SELECT * FROM links WHERE room_id=?", (room_id,))}
    if sender_id not in seen:
        raise engine.Rejected("SENDER_NOT_OBSERVED", sender=sender_id)
    if staff_id not in BY_ID:
        raise engine.Rejected("BAD_LINKS")
    links = {pid: sid for pid, sid in current.items() if sid != staff_id}
    links[sender_id] = staff_id
    return import_switch_links(store, room_id, links)
