"""Exact command grammar. A message is executed directly only when the
whole addressed body matches one of these patterns. Anything tentative,
quoted, forwarded or partial falls through to clarification."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import intervals as iv

MENTION = re.compile(r"^\s*(?:@[\w.\-]+[:,]?\s*)+", re.UNICODE)
TENTATIVE = re.compile(
    r"(것\s?같|수도|아마|할까|글쎄|몰라|모르겠|일지도|\?|？|maybe|might|probably|not sure|i think|possibly|perhaps|could)",
    re.IGNORECASE)
FORWARDED = re.compile(r"^(?:전달[:：]|fwd?[:：]|forwarded)", re.IGNORECASE)

DATE = r"(?P<date>오늘|내일|today|tomorrow|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})"
T1 = r"(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*시?"
T2 = r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*시?"
RANGE = rf"{T1}\s*(?:-|~|–|부터|to)\s*{T2}\s*(?:까지)?"
OPT_DATE = rf"(?:{DATE}\s+)?"
PART = r"(?P<part>[Pp]\d+-[A-Za-z])"
PROP = r"(?P<prop>[Pp]\d+)"
Q = r"(?:\s+(?P<q>[Qq]\d+))?"

PATTERNS = [
    ("availability", "ko", rf"가능\s+{OPT_DATE}{RANGE}"),
    ("availability", "ko", rf"{OPT_DATE}{RANGE}\s*가능(?:합니다|해요|입니다|해)?"),
    ("availability", "en", rf"(?:available|avail)\s+{OPT_DATE}{RANGE}"),
    ("withdraw", "ko", rf"가능\s*취소(?:\s+{OPT_DATE}{RANGE})?"),
    ("withdraw", "en", rf"withdraw(?:\s+{OPT_DATE}{RANGE})?"),
    ("inability", "ko", rf"불가\s+{OPT_DATE}{RANGE}"),
    ("inability", "ko", rf"{OPT_DATE}{RANGE}\s*(?:불가|못\s?해요|못\s?합니다|못\s?하게\s?됐어요|못\s?하게\s?되었습니다|못\s?나가요)"),
    ("inability", "en", rf"(?:unavailable|cannot|can't|cant)\s+{OPT_DATE}{RANGE}"),
    ("revoke", "ko", rf"(?:수락\s*취소|철회)\s+{PART}"),
    ("revoke", "ko", rf"{PART}\s*(?:수락\s*취소|철회)"),
    ("revoke", "en", rf"revoke\s+{PART}"),
    ("accept", "ko", rf"수락\s+{PART}"),
    ("accept", "ko", rf"{PART}\s*(?:수락|맡을게요|맡겠습니다)"),
    ("accept", "en", rf"accept\s+{PART}"),
    ("confirm", "ko", rf"확정\s+{PROP}"),
    ("confirm", "ko", rf"{PROP}\s*확정"),
    ("confirm", "en", rf"confirm\s+{PROP}"),
    ("yes", "ko", rf"(?:네|예|맞아요){Q}"),
    ("yes", "en", rf"(?:yes|y){Q}"),
    ("no", "ko", rf"(?:아니요|아니오|아뇨){Q}"),
    ("no", "en", rf"(?:no|n){Q}"),
    ("status", "ko", r"(?:표|현황)"),
    ("status", "en", r"(?:status|board)"),
    ("export", "ko", r"내보내기(?:\s+(?P<fmt>csv|ics))?"),
    ("export", "en", r"export(?:\s+(?P<fmt>csv|ics))?"),
    ("proposal", "ko", r"(?:대체안|제안)"),
    ("proposal", "en", r"proposal"),
    ("help", "ko", r"도움말"),
    ("help", "en", r"help"),
]
COMPILED = [(k, lang, re.compile(rf"^{p}$", re.IGNORECASE)) for k, lang, p in PATTERNS]


@dataclass
class Parsed:
    kind: str
    lang: str = "ko"
    start: int | None = None
    end: int | None = None
    date: str | None = None
    part_id: str | None = None
    proposal_id: str | None = None
    q_id: str | None = None
    fmt: str | None = None


@dataclass
class Unparsed:
    reason: str            # tentative | quoted | forwarded | ambiguous_time | bad_range | wrong_date | unknown | empty
    lang: str = "ko"
    text: str = ""
    info: dict = field(default_factory=dict)


def strip_addressing(body: str) -> tuple[str, bool]:
    """Drop leading @mentions and quoted lines. Returns (own text, had_quote)."""
    lines = body.replace("\r\n", "\n").split("\n")
    own = [ln for ln in lines if not ln.lstrip().startswith(">")]
    had_quote = len(own) != len(lines)
    text = " ".join(ln.strip() for ln in own if ln.strip())
    text = MENTION.sub("", text).strip()
    text = re.sub(r"\s+", " ", text).rstrip(".!。 ")
    return text, had_quote


def _lang_of(text: str) -> str:
    return "ko" if re.search(r"[가-힣]", text) else "en"


def _time(h: str, m: str | None):
    """Same strict clock check as every other path: 00–59 minutes, nothing
    past 24:00. `13:60` raises instead of quietly becoming 14:00."""
    minute = iv.parse_hhmm(f"{h}:{m or '00'}")
    ambiguous = m is None and len(h) == 1 and 1 <= int(h) <= 11
    return minute, ambiguous


def parse(body: str, room_date: str, created_ms: int, tz: str):
    text, had_quote = strip_addressing(body)
    lang = _lang_of(text) if text else "ko"
    if not text:
        return Unparsed("quoted" if had_quote else "empty", lang)
    if FORWARDED.search(text):
        return Unparsed("forwarded", lang, text)
    if TENTATIVE.search(text):
        return Unparsed("tentative", lang, text)
    for kind, plang, rx in COMPILED:
        m = rx.match(text)
        if not m:
            continue
        g = m.groupdict()
        out = Parsed(kind, plang)
        if g.get("part"):
            pid = g["part"]
            out.part_id = pid[0].upper() + pid[1:-1] + pid[-1].lower()
        if g.get("prop"):
            out.proposal_id = g["prop"].upper()
        if g.get("q"):
            out.q_id = g["q"].upper()
        if g.get("fmt"):
            out.fmt = g["fmt"].lower()
        if g.get("h1") is not None:
            try:
                s, amb1 = _time(g["h1"], g.get("m1"))
                e, amb2 = _time(g["h2"], g.get("m2"))
            except ValueError:
                return Unparsed("bad_range", plang, text, {"code": "BAD_CLOCK_TIME"})
            if amb1 or amb2:
                return Unparsed("ambiguous_time", plang, text, {"start": s, "end": e, "kind": kind})
            bad = iv.valid_write_range(s, e)
            if bad:
                return Unparsed("bad_range", plang, text, {"code": bad, "start": s, "end": e})
            out.start, out.end = s, e
            d = g.get("date")
            if d:
                try:
                    if d.lower() in ("오늘", "내일", "today", "tomorrow"):
                        resolved = iv.resolve_relative_date(d.lower(), created_ms, tz)
                    elif "/" in d:
                        mo, dd = (int(x) for x in d.split("/"))
                        resolved = f"{room_date[:4]}-{mo:02d}-{dd:02d}"
                    else:
                        resolved = d
                except ValueError:
                    return Unparsed("bad_range", plang, text)
                if resolved != room_date:
                    return Unparsed("wrong_date", plang, text, {"date": resolved})
            out.date = room_date
        return out
    return Unparsed("unknown", lang, text)
