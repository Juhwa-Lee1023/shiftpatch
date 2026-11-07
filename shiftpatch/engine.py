"""Domain rules. Every function here runs inside a caller-owned write
transaction (`Store.tx()`), except the pure readers which also accept a
snapshot connection. Nothing in this module talks to the network or a model.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import intervals as iv

PENDING_TTL_MS = 10 * 60 * 1000


class Rejected(Exception):
    """A request that changes nothing. `code` is stable for tests and UI."""

    def __init__(self, code: str, **info):
        super().__init__(code)
        self.code = code
        self.info = info


# ---------------------------------------------------------------- readers

def room(c, room_id):
    r = c.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,)).fetchone()
    if r is None:
        raise Rejected("ROOM_NOT_FOUND")
    return r


def staff_rows(c, room_id):
    return {r["staff_id"]: r for r in c.execute("SELECT * FROM staff WHERE room_id=?", (room_id,))}


def link_rev(c, room_id, staff_id) -> int:
    r = c.execute("SELECT link_rev FROM links WHERE room_id=? AND staff_id=?", (room_id, staff_id)).fetchone()
    return r["link_rev"] if r else 0


def need(c, room_id):
    rows = c.execute("SELECT start_min, end_min FROM base_shifts WHERE room_id=?", (room_id,)).fetchall()
    return iv.union([(r[0], r[1]) for r in rows])


def _inabilities(c, room_id):
    return c.execute("SELECT * FROM inability WHERE room_id=? ORDER BY created_version", (room_id,)).fetchall()


def holdings(c, room_id):
    """Current responsibilities: original roster rows and confirmed
    replacements, each minus later inability notices from the same person."""
    inabs = _inabilities(c, room_id)
    out = []
    for r in c.execute("SELECT * FROM base_shifts WHERE room_id=? ORDER BY start_min", (room_id,)):
        pieces = [(r["start_min"], r["end_min"])]
        for i in inabs:
            if i["staff_id"] == r["staff_id"]:
                pieces = iv.subtract(pieces, i["start_min"], i["end_min"])
        for s, e in pieces:
            out.append({"staff_id": r["staff_id"], "start": s, "end": e, "kind": "original", "ref": r["shift_id"]})
    for a in c.execute("SELECT * FROM assignments WHERE room_id=? ORDER BY start_min", (room_id,)):
        pieces = [(a["start_min"], a["end_min"])]
        for i in inabs:
            if i["staff_id"] == a["staff_id"] and i["created_version"] > a["confirmed_version"]:
                pieces = iv.subtract(pieces, i["start_min"], i["end_min"])
        for s, e in pieces:
            out.append({"staff_id": a["staff_id"], "start": s, "end": e, "kind": "confirmed",
                        "ref": a["part_id"], "proposal_id": a["proposal_id"]})
    return out


def coverage(c, room_id):
    """Elementary segments over the needed hours, merged when identical."""
    hold = holdings(c, room_id)
    segs = []
    for n0, n1 in need(c, room_id):
        cuts = {n0, n1}
        for h in hold:
            for x in (h["start"], h["end"]):
                if n0 < x < n1:
                    cuts.add(x)
        pts = sorted(cuts)
        for s, e in zip(pts, pts[1:]):
            covering = [h for h in hold if h["start"] <= s and e <= h["end"]]
            if not covering:
                segs.append({"start": s, "end": e, "status": "uncovered", "staff_id": None, "ref": None})
            elif len(covering) > 1:
                segs.append({"start": s, "end": e, "status": "conflict",
                             "staff_id": ",".join(h["staff_id"] for h in covering), "ref": None})
            else:
                h = covering[0]
                segs.append({"start": s, "end": e, "status": h["kind"], "staff_id": h["staff_id"], "ref": h["ref"]})
    merged = []
    for sg in segs:
        if merged and merged[-1]["end"] == sg["start"] and all(
                merged[-1][k] == sg[k] for k in ("status", "staff_id", "ref")):
            merged[-1]["end"] = sg["end"]
        else:
            merged.append(dict(sg))
    return merged


def gaps(c, room_id):
    return [(s["start"], s["end"]) for s in coverage(c, room_id) if s["status"] == "uncovered"]


def effective_availability(c, room_id):
    inabs = _inabilities(c, room_id)
    out = []
    for a in c.execute("SELECT * FROM availability WHERE room_id=? AND state='active' ORDER BY created_version",
                       (room_id,)):
        pieces = [(a["start_min"], a["end_min"])]
        for i in inabs:
            if i["staff_id"] == a["staff_id"] and i["created_version"] > a["created_version"]:
                pieces = iv.subtract(pieces, i["start_min"], i["end_min"])
        if pieces:
            out.append({"row": a, "pieces": pieces})
    return out


def open_proposal(c, room_id):
    return c.execute("SELECT * FROM proposals WHERE room_id=? AND state='open'", (room_id,)).fetchone()


def parts_of(c, room_id, proposal_id):
    return c.execute("SELECT * FROM parts WHERE room_id=? AND proposal_id=? ORDER BY start_min",
                     (room_id, proposal_id)).fetchall()


def active_acceptance(c, room_id, part):
    return c.execute(
        "SELECT * FROM acceptances WHERE room_id=? AND part_id=? AND staff_id=? AND component_hash=? AND state='active'",
        (room_id, part["part_id"], part["staff_id"], part["component_hash"])).fetchone()


# ---------------------------------------------------------------- writers

def bump(c, room_id) -> int:
    c.execute("UPDATE rooms SET version=version+1 WHERE room_id=?", (room_id,))
    return c.execute("SELECT version FROM rooms WHERE room_id=?", (room_id,)).fetchone()[0]


def log(c, room_id, version, at_ms, kind, actor, **detail):
    c.execute("INSERT INTO history(room_id, version, at_ms, kind, actor_staff, detail_json) VALUES (?,?,?,?,?,?)",
              (room_id, version, at_ms, kind, actor, json.dumps(detail, ensure_ascii=False, sort_keys=True)))


def _start_events(c, room_id):
    c.execute("UPDATE rooms SET events_started=1 WHERE room_id=?", (room_id,))


def _touch_fact(c, room_id, staff_id):
    c.execute("UPDATE staff SET fact_rev=fact_rev+1 WHERE room_id=? AND staff_id=?", (room_id, staff_id))


def component_hash(rm, part: dict) -> str:
    key = [rm["room_id"], rm["date"], rm["duty"], part["staff_id"], part["start"], part["end"],
           part["avail_id"], part["avail_rev"], part["link_rev"], part["roster_version"]]
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()


def _check_range(c, rm, start, end):
    bad = iv.valid_write_range(start, end)
    if bad:
        raise Rejected(bad, start=start, end=end)
    if not any(iv.overlaps(start, end, n0, n1) for n0, n1 in need(c, rm["room_id"])):
        raise Rejected("OUTSIDE_DUTY_HOURS", start=start, end=end)


@dataclass
class Outcome:
    code: str
    info: dict


def add_availability(c, room_id, staff_id, start, end, msg, created_ms) -> Outcome:
    rm = room(c, room_id)
    _check_range(c, rm, start, end)
    v = bump(c, room_id)
    n = c.execute("SELECT COUNT(*) FROM availability WHERE room_id=?", (room_id,)).fetchone()[0] + 1
    avail_id = f"A{n}"
    c.execute("INSERT INTO availability VALUES (?,?,?,?,?,1,'active',?,?,?)",
              (room_id, avail_id, staff_id, start, end, msg, created_ms, v))
    _touch_fact(c, room_id, staff_id)
    _start_events(c, room_id)
    log(c, room_id, v, created_ms, "availability", staff_id, avail_id=avail_id, start=start, end=end)
    prop = regenerate(c, room_id, created_ms)
    in_gap = [g for g in gaps(c, room_id) if iv.overlaps(start, end, *g)]
    return Outcome("AVAILABILITY_RECORDED", {"avail_id": avail_id, "start": start, "end": end,
                                             "overlaps_gap": bool(in_gap), "proposal": prop})


def withdraw_availability(c, room_id, staff_id, start, end, msg, created_ms) -> Outcome:
    """Bare withdraw removes all of the sender's availability. A ranged one
    removes exactly [start, end): each overlapping row is closed and what is
    left of it comes back as new rows. Those keep the original statement's
    created_version/created_ms, so an earlier inability still cuts them and
    the earlier-reply tie-break is unchanged; nothing outside the range is
    ever withdrawn."""
    rows = c.execute("SELECT * FROM availability WHERE room_id=? AND staff_id=? AND state='active'",
                     (room_id, staff_id)).fetchall()
    if start is not None:
        bad = iv.valid_write_range(start, end)
        if bad:
            raise Rejected(bad, start=start, end=end)
        rows = [r for r in rows if iv.overlaps(r["start_min"], r["end_min"], start, end)]
    if not rows:
        raise Rejected("NOTHING_TO_WITHDRAW", start=start, end=end)
    v = bump(c, room_id)
    removed, remainder = [], []
    for r in rows:
        c.execute("UPDATE availability SET state='withdrawn', rev=rev+1 WHERE room_id=? AND avail_id=?",
                  (room_id, r["avail_id"]))
        if start is None:
            removed.append((r["start_min"], r["end_min"]))
            continue
        removed.append(iv.intersect(r["start_min"], r["end_min"], start, end))
        for s, e in iv.subtract([(r["start_min"], r["end_min"])], start, end):
            n = c.execute("SELECT COUNT(*) FROM availability WHERE room_id=?", (room_id,)).fetchone()[0] + 1
            c.execute("INSERT INTO availability VALUES (?,?,?,?,?,1,'active',?,?,?)",
                      (room_id, f"A{n}", staff_id, s, e, r["source_msg"], r["created_ms"], r["created_version"]))
            remainder.append({"avail_id": f"A{n}", "from": r["avail_id"], "start": s, "end": e})
    _touch_fact(c, room_id, staff_id)
    _start_events(c, room_id)
    log(c, room_id, v, created_ms, "availability_withdrawn", staff_id, avail_ids=[r["avail_id"] for r in rows],
        start=start, end=end, kept=remainder)
    prop = regenerate(c, room_id, created_ms)
    left = [p for a in effective_availability(c, room_id) if a["row"]["staff_id"] == staff_id for p in a["pieces"]]
    return Outcome("AVAILABILITY_WITHDRAWN", {"ranges": iv.union(removed), "kept": iv.union(left), "proposal": prop})


def add_inability(c, room_id, staff_id, start, end, msg, created_ms) -> Outcome:
    rm = room(c, room_id)
    _check_range(c, rm, start, end)
    mine = [h for h in holdings(c, room_id) if h["staff_id"] == staff_id and iv.overlaps(h["start"], h["end"], start, end)]
    avail = [a for a in effective_availability(c, room_id)
             if a["row"]["staff_id"] == staff_id and any(iv.overlaps(s, e, start, end) for s, e in a["pieces"])]
    if not mine and not avail:
        raise Rejected("NOTHING_HELD", start=start, end=end)
    v = bump(c, room_id)
    n = c.execute("SELECT COUNT(*) FROM inability WHERE room_id=?", (room_id,)).fetchone()[0] + 1
    inab_id = f"U{n}"
    c.execute("INSERT INTO inability VALUES (?,?,?,?,?,?,?,?)",
              (room_id, inab_id, staff_id, start, end, msg, created_ms, v))
    for a in avail:
        c.execute("UPDATE availability SET rev=rev+1 WHERE room_id=? AND avail_id=?", (room_id, a["row"]["avail_id"]))
    _touch_fact(c, room_id, staff_id)
    _start_events(c, room_id)
    affected = [{"kind": h["kind"], "ref": h["ref"], **dict(zip(("start", "end"),
                iv.intersect(h["start"], h["end"], start, end)))} for h in mine]
    log(c, room_id, v, created_ms, "inability", staff_id, inab_id=inab_id, start=start, end=end, affected=affected,
        availability_cut=[a["row"]["avail_id"] for a in avail])
    prop = regenerate(c, room_id, created_ms)
    kept = [h for h in holdings(c, room_id) if h["kind"] == "confirmed"]
    return Outcome("INABILITY_RECORDED", {"start": start, "end": end, "affected": affected,
                                          "availability_cut": bool(avail), "kept_confirmed": kept,
                                          "proposal": prop})


def regenerate(c, room_id, now_ms):
    """Rebuild the single open proposal from current gaps and availability.

    Candidate = availability ∩ gap − the person's own current holdings, never
    widened beyond the gap. Greedy from each gap start, longest reach first,
    earlier response on ties. If the component set is unchanged the open
    proposal stays; otherwise it is superseded and acceptances carry over
    only to parts whose immutable component hash is identical."""
    rm = room(c, room_id)
    gp = gaps(c, room_id)
    hold = holdings(c, room_id)
    cands = []
    for a in effective_availability(c, room_id):
        row = a["row"]
        own = [(h["start"], h["end"]) for h in hold if h["staff_id"] == row["staff_id"]]
        for ps, pe in a["pieces"]:
            for gs, ge in gp:
                x = iv.intersect(ps, pe, gs, ge)
                if not x:
                    continue
                pieces = [x]
                for os_, oe in own:
                    pieces = iv.subtract(pieces, os_, oe)
                for s, e in pieces:
                    cands.append({"staff_id": row["staff_id"], "start": s, "end": e, "avail_id": row["avail_id"],
                                  "avail_rev": row["rev"], "order": row["created_version"], "gap": (gs, ge)})
    chosen = []
    for gs, ge in gp:
        pos = gs
        while pos < ge:
            here = [k for k in cands if k["gap"] == (gs, ge) and k["start"] <= pos < k["end"]
                    and not any(ch["staff_id"] == k["staff_id"] and iv.overlaps(ch["start"], ch["end"], pos, k["end"]) for ch in chosen)]
            if here:
                best = max(here, key=lambda k: (k["end"], -k["order"]))
                chosen.append({**best, "start": pos, "end": best["end"]})
                pos = best["end"]
            else:
                later = [k["start"] for k in cands if k["gap"] == (gs, ge) and k["start"] > pos]
                if not later:
                    break
                pos = min(later)
    staff = staff_rows(c, room_id)
    for ch in chosen:
        ch["link_rev"] = link_rev(c, room_id, ch["staff_id"])
        ch["roster_version"] = rm["roster_version"]
        ch["hash"] = component_hash(rm, ch)
    cur = open_proposal(c, room_id)
    if cur is not None:
        cur_hashes = sorted(p["component_hash"] for p in parts_of(c, room_id, cur["proposal_id"]))
        if cur_hashes == sorted(ch["hash"] for ch in chosen):
            return {"proposal_id": cur["proposal_id"], "changed": False}
        c.execute("UPDATE proposals SET state='superseded', closed_reason=? WHERE room_id=? AND proposal_id=?",
                  ("facts_changed", room_id, cur["proposal_id"]))
        log(c, room_id, rm["version"], now_ms, "proposal_superseded", None, proposal_id=cur["proposal_id"])
    if not chosen:
        return {"proposal_id": None, "changed": cur is not None, "superseded": cur["proposal_id"] if cur else None}
    c.execute("UPDATE rooms SET proposal_counter=proposal_counter+1 WHERE room_id=?", (room_id,))
    pn = c.execute("SELECT proposal_counter FROM rooms WHERE room_id=?", (room_id,)).fetchone()[0]
    pid = f"P{pn}"
    c.execute("INSERT INTO proposals VALUES (?,?,'open',?,?,NULL)", (room_id, pid, rm["version"], now_ms))
    carried, listed = [], []
    for idx, ch in enumerate(sorted(chosen, key=lambda k: k["start"])):
        part_id = f"{pid}-{chr(ord('a') + idx)}"
        listed.append({"part_id": part_id, "staff_id": ch["staff_id"], "start": ch["start"], "end": ch["end"],
                       "accepted": False})
        c.execute("INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (room_id, part_id, pid, ch["staff_id"], ch["start"], ch["end"], ch["avail_id"], ch["avail_rev"],
                   ch["link_rev"], ch["roster_version"], ch["hash"]))
        prev = c.execute(
            "SELECT * FROM acceptances WHERE room_id=? AND staff_id=? AND component_hash=? AND state='active' "
            "ORDER BY created_ms LIMIT 1", (room_id, ch["staff_id"], ch["hash"])).fetchone()
        if prev is not None:
            acc_id = _next_acc_id(c, room_id)
            c.execute("INSERT INTO acceptances VALUES (?,?,?,?,?,'active',?,?,?)",
                      (room_id, acc_id, part_id, ch["staff_id"], ch["hash"], prev["acc_id"], prev["source_msg"], now_ms))
            carried.append({"part_id": part_id, "from_part": prev["part_id"], "staff_id": ch["staff_id"]})
            listed[-1]["accepted"] = True
    log(c, room_id, rm["version"], now_ms, "proposal_created", None, proposal_id=pid,
        parts=[{"staff_id": ch["staff_id"], "start": ch["start"], "end": ch["end"]} for ch in chosen],
        carried=carried, replaces=cur["proposal_id"] if cur else None)
    return {"proposal_id": pid, "changed": True, "carried": carried, "parts": listed,
            "superseded": cur["proposal_id"] if cur else None}


def _next_acc_id(c, room_id):
    n = c.execute("SELECT COUNT(*) FROM acceptances WHERE room_id=?", (room_id,)).fetchone()[0] + 1
    return f"K{n}"


def _part(c, room_id, part_id):
    p = c.execute("SELECT * FROM parts WHERE room_id=? AND part_id=?", (room_id, part_id)).fetchone()
    if p is None:
        raise Rejected("PART_NOT_FOUND", part_id=part_id)
    return p


def _part_still_valid(c, room_id, p) -> bool:
    a = c.execute("SELECT * FROM availability WHERE room_id=? AND avail_id=?", (room_id, p["avail_id"])).fetchone()
    if a is None or a["state"] != "active" or a["rev"] != p["avail_rev"]:
        return False
    if link_rev(c, room_id, p["staff_id"]) != p["link_rev"]:
        return False
    return room(c, room_id)["roster_version"] == p["roster_version"]


def accept(c, room_id, staff_id, part_id, msg, created_ms) -> Outcome:
    p = _part(c, room_id, part_id)
    if p["staff_id"] != staff_id:
        raise Rejected("NOT_YOUR_PART", part_id=part_id, owner=p["staff_id"])
    prop = c.execute("SELECT * FROM proposals WHERE room_id=? AND proposal_id=?", (room_id, p["proposal_id"])).fetchone()
    if prop["state"] == "confirmed":
        raise Rejected("ALREADY_CONFIRMED", proposal_id=prop["proposal_id"])
    if prop["state"] != "open":
        cur = open_proposal(c, room_id)
        same = None
        if cur:
            same = c.execute("SELECT part_id FROM parts WHERE room_id=? AND proposal_id=? AND staff_id=?",
                             (room_id, cur["proposal_id"], staff_id)).fetchone()
        raise Rejected("PROPOSAL_REPLACED", part_id=part_id, current_part=same["part_id"] if same else None)
    if not _part_still_valid(c, room_id, p):
        raise Rejected("PART_STALE", part_id=part_id)
    if active_acceptance(c, room_id, p):
        return Outcome("ALREADY_ACCEPTED", {"part_id": part_id})
    v = bump(c, room_id)
    acc_id = _next_acc_id(c, room_id)
    c.execute("INSERT INTO acceptances VALUES (?,?,?,?,?,'active',NULL,?,?)",
              (room_id, acc_id, part_id, staff_id, p["component_hash"], msg, created_ms))
    _start_events(c, room_id)
    log(c, room_id, v, created_ms, "accepted", staff_id, part_id=part_id, start=p["start_min"], end=p["end_min"])
    waiting = [q["staff_id"] for q in parts_of(c, room_id, p["proposal_id"]) if not active_acceptance(c, room_id, q)]
    return Outcome("ACCEPTED", {"part_id": part_id, "proposal_id": p["proposal_id"], "start": p["start_min"],
                                "end": p["end_min"], "waiting_for": waiting})


def revoke(c, room_id, staff_id, part_id, msg, created_ms) -> Outcome:
    p = _part(c, room_id, part_id)
    if p["staff_id"] != staff_id:
        raise Rejected("NOT_YOUR_PART", part_id=part_id, owner=p["staff_id"])
    prop = c.execute("SELECT * FROM proposals WHERE room_id=? AND proposal_id=?", (room_id, p["proposal_id"])).fetchone()
    if prop["state"] == "confirmed":
        raise Rejected("REVOKE_AFTER_CONFIRM", part_id=part_id, start=p["start_min"], end=p["end_min"])
    rows = c.execute("SELECT acc_id FROM acceptances WHERE room_id=? AND staff_id=? AND component_hash=? AND state='active'",
                     (room_id, staff_id, p["component_hash"])).fetchall()
    if not rows:
        raise Rejected("NOTHING_TO_REVOKE", part_id=part_id)
    v = bump(c, room_id)
    # Revoke every live acceptance of this exact component so a later
    # proposal cannot carry a withdrawn consent forward.
    c.execute("UPDATE acceptances SET state='revoked' WHERE room_id=? AND staff_id=? AND component_hash=? AND state='active'",
              (room_id, staff_id, p["component_hash"]))
    log(c, room_id, v, created_ms, "acceptance_revoked", staff_id, part_id=part_id, acc_ids=[r[0] for r in rows])
    return Outcome("REVOKED", {"part_id": part_id, "start": p["start_min"], "end": p["end_min"]})


def confirm(c, room_id, staff_id, proposal_id, msg, created_ms) -> Outcome:
    st = staff_rows(c, room_id).get(staff_id)
    if st is None or st["role"] != "manager":
        raise Rejected("NOT_MANAGER")
    prop = c.execute("SELECT * FROM proposals WHERE room_id=? AND proposal_id=?", (room_id, proposal_id)).fetchone()
    rm = room(c, room_id)
    if prop is None:
        raise Rejected("PROPOSAL_NOT_FOUND", proposal_id=proposal_id)
    if prop["state"] == "confirmed":
        cut = _assignment_cuts(c, room_id, proposal_id)
        cur = open_proposal(c, room_id)
        raise Rejected("ALREADY_CONFIRMED_CHANGED" if cut else "ALREADY_CONFIRMED", proposal_id=proposal_id, cut=cut,
                       current=cur["proposal_id"] if cur else None)
    if prop["state"] != "open":
        cur = open_proposal(c, room_id)
        raise Rejected("PROPOSAL_STALE", proposal_id=proposal_id, current=cur["proposal_id"] if cur else None)
    parts = parts_of(c, room_id, proposal_id)
    current_gaps = gaps(c, room_id)
    hold = holdings(c, room_id)
    missing, stale = [], []
    for i, p in enumerate(parts):
        if not _part_still_valid(c, room_id, p):
            stale.append(p["part_id"])
            continue
        if not any(gs <= p["start_min"] and p["end_min"] <= ge for gs, ge in current_gaps):
            stale.append(p["part_id"])
            continue
        if any(h["staff_id"] == p["staff_id"] and iv.overlaps(h["start"], h["end"], p["start_min"], p["end_min"]) for h in hold):
            stale.append(p["part_id"])
            continue
        if any(iv.overlaps(p["start_min"], p["end_min"], q["start_min"], q["end_min"]) for q in parts[i + 1:]):
            stale.append(p["part_id"])
            continue
        if not active_acceptance(c, room_id, p):
            missing.append({"part_id": p["part_id"], "staff_id": p["staff_id"]})
    if stale:
        raise Rejected("PROPOSAL_STALE", proposal_id=proposal_id, parts=stale, current=None)
    if missing:
        raise Rejected("ACCEPTANCE_MISSING", proposal_id=proposal_id, missing=missing)
    v = bump(c, room_id)
    for p in parts:
        n = c.execute("SELECT COUNT(*) FROM assignments WHERE room_id=?", (room_id,)).fetchone()[0] + 1
        c.execute("INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?,?)",
                  (room_id, f"C{n}", p["staff_id"], p["start_min"], p["end_min"], proposal_id, p["part_id"], v, created_ms))
    c.execute("UPDATE proposals SET state='confirmed' WHERE room_id=? AND proposal_id=?", (room_id, proposal_id))
    _start_events(c, room_id)
    log(c, room_id, v, created_ms, "confirmed", staff_id, proposal_id=proposal_id,
        parts=[{"part_id": p["part_id"], "staff_id": p["staff_id"], "start": p["start_min"], "end": p["end_min"]} for p in parts])
    nxt = regenerate(c, room_id, created_ms)
    return Outcome("CONFIRMED", {"proposal_id": proposal_id,
                                 "parts": [{"staff_id": p["staff_id"], "start": p["start_min"], "end": p["end_min"]} for p in parts],
                                 "remaining_gaps": gaps(c, room_id), "proposal": nxt})


def _assignment_cuts(c, room_id, proposal_id):
    out = []
    for i in _inabilities(c, room_id):
        for a in c.execute("SELECT * FROM assignments WHERE room_id=? AND proposal_id=?", (room_id, proposal_id)):
            if a["staff_id"] == i["staff_id"] and i["created_version"] > a["confirmed_version"] and \
                    iv.overlaps(a["start_min"], a["end_min"], i["start_min"], i["end_min"]):
                out.append({"staff_id": a["staff_id"], "start": max(a["start_min"], i["start_min"]),
                            "end": min(a["end_min"], i["end_min"])})
    return out


# ---------------------------------------------------------------- pending acknowledgements

def dep_for(c, room_id, staff_id, action: dict) -> dict:
    st = staff_rows(c, room_id)[staff_id]
    dep = {"fact_rev": st["fact_rev"], "roster_version": room(c, room_id)["roster_version"],
           "link_rev": link_rev(c, room_id, staff_id)}
    if action["kind"] in ("accept", "revoke"):
        p = _part(c, room_id, action["part_id"])
        prop = c.execute("SELECT state FROM proposals WHERE room_id=? AND proposal_id=?",
                         (room_id, p["proposal_id"])).fetchone()
        dep["component_hash"] = p["component_hash"]
        dep["proposal_state"] = prop["state"]
    return dep


def create_pending(c, room_id, staff_id, action: dict, origin_msg: str, now_ms: int, asked_user: str | None = None) -> str:
    """`now_ms` is when ShiftPatch received the message (our clock), so a
    question asked about a delayed message still gets its full 10 minutes.
    `asked_user` is the chat account the question went to; only that account
    can answer it, even if the staff link changes later."""
    for r in c.execute("SELECT q_id, action_json FROM pending WHERE room_id=? AND staff_id=? AND state='open'",
                       (room_id, staff_id)).fetchall():
        if json.loads(r["action_json"])["kind"] == action["kind"]:
            c.execute("UPDATE pending SET state='superseded' WHERE room_id=? AND q_id=?", (room_id, r["q_id"]))
    dep = dep_for(c, room_id, staff_id, action)
    c.execute("UPDATE rooms SET pending_counter=pending_counter+1 WHERE room_id=?", (room_id,))
    n = c.execute("SELECT pending_counter FROM rooms WHERE room_id=?", (room_id,)).fetchone()[0]
    q_id = f"Q{n}"
    c.execute("INSERT INTO pending(room_id, q_id, staff_id, origin_msg, action_json, dep_json, expires_ms, state, "
              "created_ms, asked_user) VALUES (?,?,?,?,?,?,?,'open',?,?)",
              (room_id, q_id, staff_id, origin_msg, json.dumps(action, sort_keys=True), json.dumps(dep, sort_keys=True),
               now_ms + PENDING_TTL_MS, now_ms, asked_user))
    return q_id


def open_pendings(c, room_id, staff_id, now_ms):
    rows = c.execute("SELECT * FROM pending WHERE room_id=? AND staff_id=? AND state='open' ORDER BY created_ms",
                     (room_id, staff_id)).fetchall()
    live = []
    for r in rows:
        if r["expires_ms"] <= now_ms:
            c.execute("UPDATE pending SET state='expired' WHERE room_id=? AND q_id=?", (room_id, r["q_id"]))
        else:
            live.append(r)
    return live


def pick_pending(c, room_id, staff_id, q_id, now_ms, sender: str | None = None):
    """Resolve which open confirmation a bare yes/no refers to. `now_ms` is
    the receive time of the yes/no, the same clock the question was set on.
    A question asked to another chat account is closed, never answered."""
    live = open_pendings(c, room_id, staff_id, now_ms)
    if sender is not None:
        foreign = [r for r in live if r["asked_user"] is not None and r["asked_user"] != sender]
        live = [r for r in live if r not in foreign]
        if foreign and not live and (q_id is None or q_id in {r["q_id"] for r in foreign}):
            raise Rejected("CONFIRMATION_OTHER_ACCOUNT", q_id=q_id or foreign[0]["q_id"])
    if q_id:
        hit = [r for r in live if r["q_id"] == q_id]
        if not hit:
            other = c.execute("SELECT staff_id, state FROM pending WHERE room_id=? AND q_id=?", (room_id, q_id)).fetchone()
            if other is not None and other["staff_id"] != staff_id:
                raise Rejected("NOT_YOUR_CONFIRMATION", q_id=q_id)
            raise Rejected("CONFIRMATION_NOT_OPEN", q_id=q_id, state=other["state"] if other else None)
        return hit[0]
    if not live:
        raise Rejected("NO_OPEN_CONFIRMATION")
    if len(live) > 1:
        raise Rejected("WHICH_CONFIRMATION", open=[r["q_id"] for r in live])
    return live[0]


def pending_dep_current(c, room_id, pend) -> bool:
    action = json.loads(pend["action_json"])
    try:
        return dep_for(c, room_id, pend["staff_id"], action) == json.loads(pend["dep_json"])
    except Rejected:
        return False


# ---------------------------------------------------------------- watermark

def check_and_advance_watermark(c, room_id, staff_id, created_ms, msg_key):
    w = c.execute("SELECT * FROM watermarks WHERE room_id=? AND staff_id=?", (room_id, staff_id)).fetchone()
    if w is not None and created_ms <= w["last_created_ms"]:
        raise Rejected("OLDER_THAN_LATEST", last_ms=w["last_created_ms"])
    c.execute("INSERT INTO watermarks VALUES (?,?,?,?) ON CONFLICT(room_id, staff_id) DO UPDATE SET "
              "last_created_ms=excluded.last_created_ms, last_msg=excluded.last_msg",
              (room_id, staff_id, created_ms, msg_key))


# ---------------------------------------------------------------- views

def board(c, room_id):
    rm = room(c, room_id)
    st = staff_rows(c, room_id)
    cov = coverage(c, room_id)
    prop = open_proposal(c, room_id)
    proposal = None
    if prop is not None:
        proposal = proposal_view(c, room_id, prop["proposal_id"])
    for sg in cov:
        sg["name"] = st[sg["staff_id"]]["display_name"] if sg["staff_id"] in st else None
        sg["name_en"] = st[sg["staff_id"]]["display_name_en"] if sg["staff_id"] in st else None
        sg["pending"] = []
        if proposal and sg["status"] == "uncovered":
            for p in proposal["parts"]:
                if iv.overlaps(p["start"], p["end"], sg["start"], sg["end"]):
                    sg["pending"].append(p)
    avail = []
    for a in effective_availability(c, room_id):
        r = a["row"]
        avail.append({"avail_id": r["avail_id"], "staff_id": r["staff_id"], "name": st[r["staff_id"]]["display_name"],
                      "name_en": st[r["staff_id"]]["display_name_en"], "pieces": a["pieces"], "created_ms": r["created_ms"]})
    return {"room": dict(rm), "coverage": cov, "gaps": gaps(c, room_id), "proposal": proposal,
            "availability": avail, "staff": [dict(s) for s in st.values()]}


def proposal_view(c, room_id, proposal_id):
    st = staff_rows(c, room_id)
    prop = c.execute("SELECT * FROM proposals WHERE room_id=? AND proposal_id=?", (room_id, proposal_id)).fetchone()
    if prop is None:
        raise Rejected("PROPOSAL_NOT_FOUND")
    parts = []
    for p in parts_of(c, room_id, proposal_id):
        acc = active_acceptance(c, room_id, p)
        carried_from = None
        if acc and acc["carried_from_acc"]:
            src = c.execute("SELECT part_id FROM acceptances WHERE room_id=? AND acc_id=?",
                            (room_id, acc["carried_from_acc"])).fetchone()
            carried_from = src["part_id"] if src else None
        asg = c.execute("SELECT * FROM assignments WHERE room_id=? AND part_id=?", (room_id, p["part_id"])).fetchone()
        parts.append({"part_id": p["part_id"], "staff_id": p["staff_id"], "name": st[p["staff_id"]]["display_name"],
                      "name_en": st[p["staff_id"]]["display_name_en"], "start": p["start_min"], "end": p["end_min"],
                      "accepted": acc is not None, "carried_from": carried_from, "confirmed": asg is not None,
                      "valid": _part_still_valid(c, room_id, p)})
    cuts = _assignment_cuts(c, room_id, proposal_id) if prop["state"] == "confirmed" else []
    return {"proposal_id": proposal_id, "state": prop["state"], "parts": parts, "cuts": cuts,
            "closed_reason": prop["closed_reason"], "created_ms": prop["created_ms"]}
