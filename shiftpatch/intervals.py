"""Half-open minute intervals [start, end) inside one day.

All times are minutes since local midnight in the room's timezone.
Overnight intervals are out of scope and rejected by callers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STEP = 30  # minute boundary accepted for any write


def fmt(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def fmt_range(start: int, end: int) -> str:
    return f"{fmt(start)}–{fmt(end)}"


def parse_hhmm(text: str) -> int:
    hh, _, mm = text.partition(":")
    h, m = int(hh), int(mm or 0)
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(text)
    return h * 60 + m


def overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def intersect(a0: int, a1: int, b0: int, b1: int):
    s, e = max(a0, b0), min(a1, b1)
    return (s, e) if s < e else None


def subtract(pieces, cut0: int, cut1: int):
    """Remove [cut0, cut1) from a list of (start, end) pieces."""
    out = []
    for s, e in pieces:
        if not overlaps(s, e, cut0, cut1):
            out.append((s, e))
            continue
        if s < cut0:
            out.append((s, cut0))
        if cut1 < e:
            out.append((cut1, e))
    return out


def union(pieces):
    merged = []
    for s, e in sorted(pieces):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def valid_write_range(start: int, end: int) -> str | None:
    """Return a reason code when a range cannot be written, else None."""
    if start >= end:
        return "NON_POSITIVE_OR_OVERNIGHT"
    if start % STEP or end % STEP:
        return "NOT_30_MIN_BOUNDARY"
    if start < 0 or end > 24 * 60:
        return "OUT_OF_DAY"
    return None


def local_date_of(ms: int, tz: str) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz)).date().isoformat()


def local_iso(ms: int, tz: str) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz)).isoformat(timespec="seconds")


def local_label(ms: int, tz: str) -> str:
    d = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz))
    return f"{d.month}/{d.day} {d.hour:02d}:{d.minute:02d}"


def resolve_relative_date(word: str, created_ms: int, tz: str) -> str:
    base = datetime.fromtimestamp(created_ms / 1000, tz=ZoneInfo(tz)).date()
    if word in ("오늘", "today"):
        return base.isoformat()
    if word in ("내일", "tomorrow"):
        return (base + timedelta(days=1)).isoformat()
    raise ValueError(word)


def ms_for_local(date_iso: str, minute: int, tz: str) -> int:
    y, mo, d = (int(x) for x in date_iso.split("-"))
    dt = datetime(y, mo, d, tzinfo=ZoneInfo(tz)) + timedelta(minutes=minute)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


WEEKDAY_KO = "월화수목금토일"
WEEKDAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def date_label(date_iso: str, lang: str = "ko") -> str:
    y, mo, d = (int(x) for x in date_iso.split("-"))
    wd = datetime(y, mo, d).weekday()
    if lang == "en":
        return f"{WEEKDAY_EN[wd]} {mo}/{d}"
    return f"{mo}/{d}({WEEKDAY_KO[wd]})"
