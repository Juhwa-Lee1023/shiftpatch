"""Room replies. Short, concrete, and in the language the person used."""
from __future__ import annotations

from .intervals import date_label, fmt_range


class Names:
    def __init__(self, staff_rows: dict, lang: str):
        self.rows, self.lang = staff_rows, lang

    def __call__(self, staff_id):
        r = self.rows.get(staff_id)
        if r is None:
            return staff_id or "—"
        return r["display_name_en"] if self.lang == "en" else r["display_name"]

    def manager(self):
        """Display name of the room's manager, or None."""
        for sid, r in self.rows.items():
            if r["role"] == "manager":
                return self(sid)
        return None


def _ranges(pairs):
    return ", ".join(fmt_range(s, e) for s, e in pairs)


def _final_consonant(word: str) -> bool:
    """Whether the word, read aloud in Korean, ends in a consonant: Hangul by
    its last syllable, digits as 영·일·삼·육·칠·팔, Latin letters as 엘·엠·엔·알."""
    ch = word.rstrip(" `'\")")[-1:]
    if not ch:
        return False
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit():
        return ch in "013678"
    return ch.lower() in "lmnr"


def josa(word: str, pair: str) -> str:
    """josa('P2', '은/는') -> 'P2는'; josa('P1', '은/는') -> 'P1은'."""
    with_c, without = pair.split("/")
    return word + (with_c if _final_consonant(word) else without)


def part_lines(parts, names: Names, ko: bool, proposal_id: str) -> str:
    """Who accepts which part, with the real IDs, then who confirms."""
    todo = [p for p in parts if not p.get("accepted")]
    lines = [f"{names(p['staff_id'])}: `{'수락' if ko else 'accept'} {p['part_id']}`" for p in todo]
    mgr = names.manager()
    cmd = f"`확정 {proposal_id}`" if ko else f"`confirm {proposal_id}`"
    if ko:
        tail = (f"{mgr}님이 " if mgr else "관리자가 ") + josa(cmd, "을/를") + " 보내면 근무표에 반영됩니다."
    else:
        tail = f"Then {mgr or 'the manager'} sends {cmd}."
    if not todo:
        tail = ("모두 수락했습니다. " if ko else "Everyone has accepted. ") + tail
    return (" · ".join(lines) + ("\n" if lines else "")) + tail


def render(code: str, info: dict, lang: str, names: Names, date: str, actor: str | None = None) -> str:
    ko = lang != "en"
    d = date_label(date, "ko" if ko else "en")
    me = names(actor) if actor else ""
    r = lambda: fmt_range(info["start"], info["end"])  # noqa: E731
    if code == "NOTHING_TO_WITHDRAW" and info.get("start") is not None:
        return (f"{fmt_range(info['start'], info['end'])}에 거둬들일 가능 기록이 없어 바꾼 것이 없습니다." if ko
                else f"You have no availability in {fmt_range(info['start'], info['end'])}, so nothing changed.")
    info = {**info, "start": info.get("start") or 0, "end": info.get("end") or 0}

    def prop_line():
        p = info.get("proposal") or {}
        pid = p.get("proposal_id")
        if not pid or not p.get("changed"):
            return ""
        carried = p.get("carried") or []
        note = ""
        if carried:
            items = ", ".join(f"{c['part_id']}←{c['from_part']}" for c in carried)
            note = f" (이전 수락 이어받음: {items})" if ko else f" (earlier acceptance carried: {items})"
        parts = p.get("parts") or []
        if not parts:
            return (f"\n새 대체안 {josa(pid, '이/가')} 올라왔습니다{note}. `대체안`으로 확인할 수 있어요."
                    if ko else f"\nNew proposal {pid} is up{note}. Send `proposal` to see it.")
        listing = ", ".join(f"{names(x['staff_id'])} {fmt_range(x['start'], x['end'])}" for x in parts)
        return ((f"\n새 대체안 {pid}: {listing}{note}." if ko else f"\nNew proposal {pid}: {listing}{note}.")
                + "\n" + part_lines(parts, names, ko, pid))

    if code == "AVAILABILITY_RECORDED":
        base = (f"{me}님 {d} {r()} 가능으로 기록했습니다. 가능 기록만으로는 근무를 맡은 것이 아닙니다."
                if ko else f"Recorded {me} as available {d} {r()}. Being available is not the same as taking the shift.")
        return base + prop_line()
    if code == "AVAILABILITY_WITHDRAWN":
        kept = info.get("kept") or []
        kept_txt = ""
        if kept:
            kept_txt = (f" 남은 가능 시간: {_ranges(kept)}." if ko else f" Still available: {_ranges(kept)}.")
        return ((f"{me}님의 가능 기록 {_ranges(info['ranges'])}을 거둬들였습니다.{kept_txt}" if ko
                 else f"Withdrew {me}'s availability for {_ranges(info['ranges'])}.{kept_txt}") + prop_line())
    if code == "INABILITY_RECORDED":
        if info["affected"]:
            gap = _ranges([(a["start"], a["end"]) for a in info["affected"]])
            kept = [k for k in info["kept_confirmed"]]
            kept_txt = ""
            if kept:
                kept_txt = (" " + " ".join(f"{names(k['staff_id'])}님의 {fmt_range(k['start'], k['end'])}은 유지됩니다." for k in kept)
                            if ko else " " + " ".join(f"{names(k['staff_id'])}'s {fmt_range(k['start'], k['end'])} stays confirmed." for k in kept))
            p = (info.get("proposal") or {}).get("proposal_id")
            who = ("" if p else (" 지금 이 시간을 맡을 수 있다고 답한 사람은 없습니다." if ko
                                 else " Nobody has said they can take it yet."))
            # "again" only when a confirmed replacement was cut; a first notice is new.
            reopened = any(a["kind"] == "confirmed" for a in info["affected"])
            if ko:
                head = f"{d} {gap}이 {'다시 ' if reopened else ''}비었습니다."
                return f"{head}{kept_txt}{who} 사유를 입력할 필요는 없어요." + prop_line()
            head = f"{d} {gap} is {'uncovered again' if reopened else 'now uncovered'}."
            return f"{head}{kept_txt}{who}" + prop_line()
        return ((f"{me}님의 {r()} 가능 기록을 거둬들였습니다." if ko else f"Withdrew {me}'s availability for {r()}.")
                + prop_line())
    if code == "ACCEPTED":
        wait = info["waiting_for"]
        if wait:
            tail = (" 남은 수락: " + ", ".join(names(s) for s in wait) + "." if ko
                    else " Still waiting for: " + ", ".join(names(s) for s in wait) + ".")
        else:
            mgr = names.manager()
            cmd = f"`확정 {info['proposal_id']}`"
            tail = (f" 필요한 수락이 모두 모였습니다. {mgr + '님이' if mgr else '관리자가'} {josa(cmd, '을/를')} 보내면 근무표에 반영됩니다."
                    if ko else f" All parts are accepted. Waiting for {mgr or 'the manager'} to send `confirm {info['proposal_id']}`.")
        return (f"{me}님이 {info['part_id']} {d} {r()}을 수락했습니다." if ko
                else f"{me} accepted {info['part_id']} {d} {r()}.") + tail
    if code == "ALREADY_ACCEPTED":
        return f"{josa(info['part_id'], '은/는')} 이미 수락하셨어요." if ko else f"You already accepted {info['part_id']}."
    if code == "REVOKED":
        return (f"{me}님의 {info['part_id']} {r()} 수락을 취소했습니다. 확정 전이라 근무표는 바뀌지 않았어요." if ko
                else f"Withdrew {me}'s acceptance of {info['part_id']} {r()}. Nothing was confirmed yet.")
    if code == "CONFIRMED":
        parts = ", ".join(f"{names(p['staff_id'])} {fmt_range(p['start'], p['end'])}" for p in info["parts"])
        rem = info["remaining_gaps"]
        tail = ((" 남은 빈 시간: " + _ranges(rem) + ".") if rem else " 빈 시간이 없습니다.") if ko else \
            ((" Still uncovered: " + _ranges(rem) + ".") if rem else " No gaps remain.")
        return (f"{josa(info['proposal_id'], '을/를')} 확정했습니다: {parts}." if ko
                else f"Confirmed {info['proposal_id']}: {parts}.") + tail + prop_line()
    if code == "ALREADY_CONFIRMED_CHANGED":
        pid = info.get("proposal_id") or ""
        cut = info.get("cut") or []
        cut_ko = ", ".join(f"{names(x['staff_id'])}님의 {fmt_range(x['start'], x['end'])}" for x in cut)
        cut_en = ", ".join(f"{names(x['staff_id'])}'s {fmt_range(x['start'], x['end'])}" for x in cut)
        cur = info.get("current")
        if ko:
            nxt = (f" 지금 올라온 대체안은 {cur}입니다." if cur else
                   " 비어 있는 시간은 새 대체안이 필요합니다. 누군가 가능 시간을 보내면 새 안이 올라와요.")
            return (f"{josa(pid, '은/는')} 앞서 확정됐습니다. 그 뒤 {cut_ko}이 빠져서 {josa(pid, '을/를')} "
                    f"다시 확정하지 않았습니다. 상태는 그대로예요.{nxt}")
        nxt = (f" The current proposal is {cur}." if cur else
               " The reopened hours need a new proposal; it appears when someone replies with hours they can take.")
        return f"{pid} was confirmed earlier. Since then {cut_en} reopened, so {pid} was not confirmed again. Nothing changed.{nxt}"
    if code == "BAD_CLOCK_TIME":
        return ("시각을 읽을 수 없어 기록하지 않았습니다. 분은 00–59, 하루의 끝은 24:00까지 씁니다. 예: `가능 13:30-15:00`"
                if ko else "That is not a clock time, so nothing was recorded. Minutes run 00–59 and the day ends at 24:00, "
                           "e.g. `available 13:30-15:00`.")
    # ---- rejections
    rej = {
        "NOT_YOUR_PART": ("본인에게 제안된 구간만 수락하거나 취소할 수 있습니다. 다른 분의 수락은 그분이 직접 보내야 해요.",
                          "You can only accept or withdraw your own part. Each person answers for themselves."),
        "ALREADY_CONFIRMED": (f"{josa(str(info.get('proposal_id')), '은/는')} 이미 확정됐습니다. 상태는 그대로예요.",
                              f"{info.get('proposal_id')} is already confirmed. Nothing changed."),
        "PROPOSAL_STALE": ("현재 조건이 달라 그대로 확정할 수 없습니다." + (f" 지금 대체안은 {info['current']}입니다." if info.get("current") else ""),
                           "This proposal no longer matches the current facts." + (f" The current one is {info['current']}." if info.get("current") else "")),
        "PROPOSAL_REPLACED": ("이 구간은 새 대체안으로 바뀌었습니다." + (f" {josa(str(info.get('current_part')), '을/를')} 확인해 주세요." if info.get("current_part") else ""),
                              "That part was replaced by a newer proposal." + (f" Check {info['current_part']}." if info.get("current_part") else "")),
        "PART_STALE": ("가능 기록이 바뀌어 이 구간은 더 이상 유효하지 않습니다.", "Your availability changed, so this part is no longer valid."),
        "PART_NOT_FOUND": (f"{info.get('part_id')} 구간을 찾지 못했습니다.", f"Could not find part {info.get('part_id')}."),
        "PROPOSAL_NOT_FOUND": (f"{info.get('proposal_id')} 대체안을 찾지 못했습니다.", f"Could not find proposal {info.get('proposal_id')}."),
        "NOT_MANAGER": ("확정은 관리자만 할 수 있습니다.", "Only the manager can confirm."),
        "REVOKE_AFTER_CONFIRM": (f"{josa(str(info.get('part_id')), '은/는')} 이미 확정됐습니다. 못 하게 됐다면 `불가 {fmt_range(info.get('start', 0), info.get('end', 0)).replace('–', '-')}`처럼 알려 주세요.",
                                 f"{info.get('part_id')} is already confirmed. If you can no longer do it, send `unavailable {fmt_range(info.get('start', 0), info.get('end', 0)).replace('–', '-')}`."),
        "NOTHING_TO_REVOKE": ("취소할 수락이 없습니다.", "There is no acceptance to withdraw."),
        "NOTHING_TO_WITHDRAW": ("거둬들일 가능 기록이 없습니다.", "There is no availability to withdraw."),
        "NOTHING_HELD": ("그 시간에 맡은 근무나 가능 기록이 없어 바꾼 것이 없습니다.", "You hold no shift or availability in those hours, so nothing changed."),
        "OUTSIDE_DUTY_HOURS": ("그 시간은 이 방의 근무 시간 밖입니다.", "Those hours are outside this room's duty hours."),
        "NOT_30_MIN_BOUNDARY": ("시간은 30분 단위로 보내 주세요. 예: 13:00-15:30", "Please use 30-minute boundaries, e.g. 13:00-15:30."),
        "NON_POSITIVE_OR_OVERNIGHT": ("끝 시각이 시작보다 늦어야 합니다. 자정을 넘는 근무는 다루지 않아요.", "The end must be after the start. Overnight shifts are out of scope."),
        "OUT_OF_DAY": ("하루 안의 시간만 다룹니다.", "Only times within one day are supported."),
        "OLDER_THAN_LATEST": ("이 메시지는 더 최근 메시지보다 먼저 작성된 것으로 보여 반영하지 않았습니다. 바꾸려면 새로 보내 주세요.",
                              "This message looks older than one already applied from you, so it was not applied. Please send it again."),
        "ACCEPTANCE_MISSING": ("아직 수락하지 않은 구간이 있습니다: " + ", ".join(f"{m['part_id']} {names(m['staff_id'])}" for m in info.get("missing", [])) + ". 본인 수락을 기다려 주세요.",
                               "Some parts are not accepted yet: " + ", ".join(f"{m['part_id']} {names(m['staff_id'])}" for m in info.get("missing", [])) + ". Each person has to accept their own part."),
        "NO_OPEN_CONFIRMATION": ("확인할 내용이 없습니다.", "There is nothing waiting for your confirmation."),
        "WHICH_CONFIRMATION": ("확인할 내용이 여러 개입니다. " + " / ".join(f"`네 {q}`" for q in info.get("open", [])) + " 중 하나로 보내 주세요.",
                               "Several confirmations are open. Reply with " + " / ".join(f"`yes {q}`" for q in info.get("open", [])) + "."),
        "NOT_YOUR_CONFIRMATION": ("다른 분에게 보낸 확인에는 답할 수 없습니다.", "You cannot answer someone else's confirmation."),
        "CONFIRMATION_OTHER_ACCOUNT": (f"{info.get('q_id')} 확인은 다른 채팅 계정에 보낸 질문이라 닫았습니다. 아무것도 바뀌지 않았어요. 필요하면 새로 보내 주세요.",
                                       f"{info.get('q_id')} was asked to a different chat account, so it is closed. Nothing changed. Send it again if you still need it."),
        "CONFIRMATION_NOT_OPEN": (f"{info.get('q_id')} 확인은 이미 닫혔습니다.", f"Confirmation {info.get('q_id')} is closed."),
        "ROSTER_NOT_READY": ("아직 초기 근무표가 등록되지 않았습니다. 관리자가 로컬 설정 화면에서 먼저 등록해야 해요.",
                             "The initial roster is not imported yet. The manager imports it in the local setup screen first."),
    }
    if code in rej:
        return rej[code][0] if ko else rej[code][1]
    return code
