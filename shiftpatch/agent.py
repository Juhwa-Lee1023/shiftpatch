"""Message pipeline.

Adapters (the local demo room, or the Switch bridge) build a
`TrustedEnvelope` from what *their* transport says: room, message id,
sender, timestamp. Nothing in a message body, a web request or a model
answer can change who the actor is. Each envelope gets a short-lived
execution context bound to that room/message/actor; the domain write, the
processed marker and the reply are committed together against it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import engine, grammar
from . import intervals as iv
from .engine import Rejected
from .messages import Names, part_lines, render

CTX_TTL_MS = 120 * 1000
FUTURE_SKEW_MS = 2 * 60 * 1000
MAX_AGE_MS = 15 * 60 * 1000
STATE_KINDS = {"availability", "withdraw", "inability", "accept", "revoke", "confirm"}
ALLOWED = {"staff": ["availability", "withdraw", "inability", "accept", "revoke", "yes", "no", "status", "export",
                     "proposal", "help"]}
ALLOWED["manager"] = ALLOWED["staff"] + ["confirm"]


@dataclass(frozen=True)
class TrustedEnvelope:
    source: str            # 'local_demo' | 'switch'
    room_id: str
    message_id: str
    sender: str            # transport participant id, opaque
    sender_name: str
    body: str
    created_ms: int        # platform timestamp
    received_ms: int       # our clock when the adapter received it
    addressed: bool = True
    markers: frozenset = field(default_factory=frozenset)
    note: str | None = None  # adapter note, e.g. gap


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Agent:
    def __init__(self, store, interpreter, exporter=None, board_url: str | None = None):
        self.store, self.ai, self.exporter, self.board_url = store, interpreter, exporter, board_url

    # ------------------------------------------------------------ entry
    def handle(self, env: TrustedEnvelope) -> dict:
        msg_key = f"{env.source}:{env.room_id}:{env.message_id}"
        body_hash = _sha(env.body)
        with self.store.snapshot() as c:
            rm = c.execute("SELECT * FROM rooms WHERE room_id=?", (env.room_id,)).fetchone()
            prev = c.execute("SELECT * FROM processed WHERE msg_key=?", (msg_key,)).fetchone()
            link = c.execute("SELECT * FROM links WHERE room_id=? AND platform_user_id=?",
                             (env.room_id, env.sender)).fetchone()
        if rm is None:
            return {"status": "unknown_room"}
        if (rm["kind"] == "switch") != (env.source == "switch"):
            raise PermissionError("envelope source does not match room kind")
        if prev is not None:
            if prev["body_sha256"] != body_hash:
                lang = "en" if not re.search(r"[가-힣]", env.body) else "ko"
                self._reply_only(rm, msg_key + ":edited", env, lang,
                                 "수정된 메시지는 반영하지 않았습니다. 바꾸려면 새 메시지로 보내 주세요." if lang == "ko"
                                 else "Edited messages are not applied. Please send a new message.", record=False)
                return {"status": "edited_ignored"}
            first = json.loads(prev["result_json"])
            return {**first, "status": "duplicate", "first_status": first.get("status")}
        if not env.addressed:
            return {"status": "not_addressed"}
        if env.markers & {"auto_reply", "admin", "bot"}:
            self._record(rm, msg_key, body_hash, {"status": "ignored_marker"})
            return {"status": "ignored_marker"}
        lang = "ko" if re.search(r"[가-힣]", env.body) else "en"
        if link is None:
            text = ("이 계정은 아직 ShiftPatch 직원 명단과 연결되지 않아 아무것도 바꾸지 않았습니다. 관리자에게 연결을 요청해 주세요."
                    if lang == "ko" else "This account is not linked to the ShiftPatch staff list, so nothing changed. Ask the manager to link it.")
            return self._reply_only(rm, msg_key, env, lang, text, status="unlinked", body_hash=body_hash,
                                    seen=env.source == "switch")
        staff_id = link["staff_id"]
        if rm["roster_version"] == 0:
            return self._reply_only(rm, msg_key, env, lang, render("ROSTER_NOT_READY", {}, lang, None, rm["date"]),
                                    status="roster_not_ready", body_hash=body_hash)
        if env.created_ms > env.received_ms + FUTURE_SKEW_MS:
            text = ("메시지 작성 시각이 서버 시각보다 너무 앞서 있어 반영하지 않았습니다." if lang == "ko"
                    else "The message timestamp is too far in the future, so it was not applied.")
            return self._reply_only(rm, msg_key, env, lang, text, status="future_timestamp", body_hash=body_hash)
        if env.created_ms < env.received_ms - MAX_AGE_MS:
            text = ("15분보다 오래된 메시지라 반영하지 않았습니다. 지금 상황에 맞게 다시 보내 주세요." if lang == "ko"
                    else "This message is older than 15 minutes, so it was not applied. Please send it again.")
            return self._reply_only(rm, msg_key, env, lang, text, status="too_old", body_hash=body_hash)

        ctx_id = self._issue_ctx(rm, msg_key, staff_id, env.received_ms)
        parsed = grammar.parse(env.body, rm["date"], env.created_ms, rm["timezone"])
        suggestion, source = None, None
        if isinstance(parsed, grammar.Unparsed) and parsed.reason in ("tentative", "unknown"):
            suggestion, source = self._suggest(rm, staff_id, env, parsed)
        result = self._commit(rm["room_id"], ctx_id, msg_key, body_hash, staff_id, env, parsed, suggestion, source)
        if result.get("export"):
            self._run_export(rm, msg_key, result)
        return result

    # ------------------------------------------------------------ helpers
    def _issue_ctx(self, rm, msg_key, staff_id, now):
        with self.store.tx() as c:
            role = engine.staff_rows(c, rm["room_id"])[staff_id]["role"]
            c.execute("UPDATE exec_ctx SET state='expired' WHERE room_id=? AND state='issued'", (rm["room_id"],))
            ctx_id = uuid.uuid4().hex
            c.execute("INSERT INTO exec_ctx VALUES (?,?,?,?,?,?,?,'issued')",
                      (ctx_id, rm["room_id"], msg_key, staff_id, role, json.dumps(ALLOWED[role]), now + CTX_TTL_MS))
        return ctx_id

    def _record(self, rm, msg_key, body_hash, result):
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO processed VALUES (?,?,?,?,?,?)",
                      (msg_key, rm["room_id"], body_hash, json.dumps(result, ensure_ascii=False),
                       engine.room(c, rm["room_id"])["version"], 0))

    def _reply_only(self, rm, msg_key, env, lang, text, status="replied", body_hash=None, record=True, seen=False):
        if env.note:
            text = env.note + "\n" + text
        result = {"status": status, "reply": text}
        with self.store.tx() as c:
            if seen:
                # the transport's sender id and display name only; the message text is not kept
                engine.note_unlinked(c, rm["room_id"], env.sender, env.sender_name, env.received_ms)
            if record:
                c.execute("INSERT OR IGNORE INTO processed VALUES (?,?,?,?,?,?)",
                          (msg_key, rm["room_id"], body_hash or _sha(env.body), json.dumps(result, ensure_ascii=False),
                           engine.room(c, rm["room_id"])["version"], env.received_ms))
            c.execute("INSERT OR IGNORE INTO outbox(room_id, idem_key, reply_to, body, state, created_ms) "
                      "VALUES (?,?,?,?,'pending',?)", (rm["room_id"], msg_key + ":reply" if record else msg_key,
                                                       env.message_id, text, env.received_ms))
        return result

    def _suggest(self, rm, staff_id, env, parsed):
        """AI first when available, then a narrow rule reader for hedged
        messages that already carry an explicit two-digit range. Either way
        the result is only a suggestion the sender must confirm."""
        with self.store.snapshot() as c:
            st = engine.staff_rows(c, rm["room_id"])[staff_id]
            prop = engine.open_proposal(c, rm["room_id"])
            mine = []
            if prop:
                mine = [{"part_id": p["part_id"], "start": iv.fmt(p["start_min"]), "end": iv.fmt(p["end_min"])}
                        for p in engine.parts_of(c, rm["room_id"], prop["proposal_id"]) if p["staff_id"] == staff_id]
            gaps = [iv.fmt_range(s, e) for s, e in engine.gaps(c, rm["room_id"])]
            need = [iv.fmt_range(s, e) for s, e in engine.need(c, rm["room_id"])]
            held = [iv.fmt_range(h["start"], h["end"]) for h in engine.holdings(c, rm["room_id"]) if h["staff_id"] == staff_id]
        if self.ai is not None and self.ai.enabled:
            context = {"sender_display_name": st["display_name"], "roster_date": rm["date"], "timezone": rm["timezone"],
                       "message_local_time": iv.local_iso(env.created_ms, rm["timezone"]),
                       "duty_hours": need, "sender_current_shifts": held, "current_gaps": gaps,
                       "sender_open_parts": mine}
            s = self.ai.interpret(parsed.text, context)
            if s is not None:
                return s, "ai"
        return _rule_suggest(parsed.text, rm, env.created_ms), "rule"

    # ------------------------------------------------------------ commit
    def _commit(self, room_id, ctx_id, msg_key, body_hash, staff_id, env, parsed, suggestion, source):
        with self.store.tx() as c:
            ctx = c.execute("SELECT * FROM exec_ctx WHERE ctx_id=?", (ctx_id,)).fetchone()
            if ctx is None or ctx["state"] != "issued" or ctx["msg_key"] != msg_key or ctx["room_id"] != room_id \
                    or ctx["staff_id"] != staff_id or ctx["expires_ms"] <= env.received_ms:
                raise PermissionError("execution context is not valid for this message")
            if c.execute("SELECT 1 FROM processed WHERE msg_key=?", (msg_key,)).fetchone():
                raise PermissionError("message already processed")
            rm = engine.room(c, room_id)
            names = None
            lang = getattr(parsed, "lang", "ko")
            if suggestion is not None and getattr(suggestion, "lang", None) in ("ko", "en"):
                lang = suggestion.lang
            names = Names(engine.staff_rows(c, room_id), lang)
            allowed = json.loads(ctx["allowed_json"])
            now = env.created_ms
            out = {"status": "ok", "lang": lang}
            c.execute("SAVEPOINT act")
            try:
                text = self._dispatch(c, rm, staff_id, ctx, allowed, msg_key, env, parsed, suggestion, source,
                                      names, lang, out)
                c.execute("RELEASE act")
            except Rejected as r:
                c.execute("ROLLBACK TO act")
                c.execute("RELEASE act")
                if out.get("attempted") == "confirm":
                    engine.log(c, room_id, rm["version"], now, "confirm_rejected", staff_id,
                               proposal_id=out.get("proposal_id"), reason=r.code)
                text = render(r.code, r.info, lang, names, rm["date"], staff_id)
                out.update(status="rejected", code=r.code)
            if env.note:
                text = env.note + "\n" + text
            out["reply"] = text
            version = engine.room(c, room_id)["version"]
            out["version"] = version
            c.execute("UPDATE exec_ctx SET state='used' WHERE ctx_id=?", (ctx_id,))
            c.execute("INSERT INTO processed VALUES (?,?,?,?,?,?)",
                      (msg_key, room_id, body_hash, json.dumps(out, ensure_ascii=False), version, env.received_ms))
            self.store.hit("after_processed")
            c.execute("INSERT INTO outbox(room_id, idem_key, reply_to, body, state, created_ms) VALUES (?,?,?,?,'pending',?)",
                      (room_id, msg_key + ":reply", env.message_id, text, env.received_ms))
        return out

    def _dispatch(self, c, rm, staff_id, ctx, allowed, msg_key, env, parsed, suggestion, source, names, lang, out):
        room_id, date, now = rm["room_id"], rm["date"], env.created_ms
        if isinstance(parsed, grammar.Unparsed):
            return self._unparsed(c, rm, staff_id, msg_key, env, parsed, suggestion, source, names, lang, out)
        kind = parsed.kind
        if kind not in allowed:
            raise Rejected("NOT_MANAGER")
        if kind in STATE_KINDS:
            out["attempted"] = kind
            out["proposal_id"] = parsed.proposal_id
            engine.check_and_advance_watermark(c, room_id, staff_id, env.created_ms, msg_key)
            o = self._apply_action(c, room_id, staff_id, {"kind": kind, "start": parsed.start, "end": parsed.end,
                                                          "part_id": parsed.part_id, "proposal_id": parsed.proposal_id},
                                   msg_key, now)
            out.update(status="applied", code=o.code)
            return render(o.code, o.info, lang, names, date, staff_id)
        if kind in ("yes", "no"):
            return self._ack(c, rm, staff_id, msg_key, env, parsed, names, lang, out)
        if kind == "status":
            return status_text(c, rm, lang, names, self.board_url)
        if kind == "proposal":
            return proposal_text(c, rm, lang, names)
        if kind == "export":
            out["export"] = parsed.fmt or "csv"
            return ("현재 현황을 시점 고정 파일로 만들고 있습니다." if lang == "ko"
                    else "Creating a snapshot file of the current coverage.")
        return help_text(lang, ctx["role"])

    def _apply_action(self, c, room_id, staff_id, a, msg_key, now):
        k = a["kind"]
        if k == "availability":
            return engine.add_availability(c, room_id, staff_id, a["start"], a["end"], msg_key, now)
        if k == "withdraw":
            return engine.withdraw_availability(c, room_id, staff_id, a.get("start"), a.get("end"), msg_key, now)
        if k == "inability":
            return engine.add_inability(c, room_id, staff_id, a["start"], a["end"], msg_key, now)
        if k == "accept":
            return engine.accept(c, room_id, staff_id, a["part_id"], msg_key, now)
        if k == "revoke":
            return engine.revoke(c, room_id, staff_id, a["part_id"], msg_key, now)
        if k == "confirm":
            return engine.confirm(c, room_id, staff_id, a["proposal_id"], msg_key, now)
        raise Rejected("UNKNOWN_ACTION")

    def _ack(self, c, rm, staff_id, msg_key, env, parsed, names, lang, out):
        room_id, date = rm["room_id"], rm["date"]
        # Question lifetime runs on our receive clock. Which question this reply can answer, and the
        # watermark below, run on the platform's created_ms: a reply written before the message a
        # question is about never approves or closes that question.
        pend = engine.pick_pending(c, room_id, staff_id, parsed.q_id, env.received_ms, sender=env.sender,
                                   reply_created_ms=env.created_ms)
        action = json.loads(pend["action_json"])
        if parsed.kind == "no":
            c.execute("UPDATE pending SET state='declined' WHERE room_id=? AND q_id=?", (room_id, pend["q_id"]))
            return (f"{pend['q_id']} 확인을 닫았습니다. 아무것도 바뀌지 않았어요." if lang == "ko"
                    else f"Closed {pend['q_id']}. Nothing changed.")
        if not engine.pending_dep_current(c, room_id, pend):
            c.execute("UPDATE pending SET state='stale' WHERE room_id=? AND q_id=?", (room_id, pend["q_id"]))
            try:
                q = engine.create_pending(c, room_id, staff_id, action, msg_key, env.received_ms, asked_user=env.sender,
                                         source_created_ms=env.created_ms)
            except Rejected:
                return ("확인하려던 내용의 조건이 바뀌어 더 이상 적용할 수 없습니다." if lang == "ko"
                        else "The facts behind that confirmation changed, so it can no longer be applied.")
            out["pending"] = q
            exp = iv.local_label(env.received_ms + engine.PENDING_TTL_MS, rm["timezone"]).split(" ")[1]
            return (("그 사이 관련 기록이 바뀌었습니다. 다시 확인해 주세요.\n" if lang == "ko"
                     else "Something related changed in the meantime. Please confirm again.\n")
                    + pending_question(action, q, names, lang, date, staff_id, exp))
        out["attempted"] = action["kind"]
        out["proposal_id"] = action.get("proposal_id")
        engine.check_and_advance_watermark(c, room_id, staff_id, env.created_ms, msg_key)
        o = self._apply_action(c, room_id, staff_id, action, pend["origin_msg"], env.created_ms)
        c.execute("UPDATE pending SET state='applied' WHERE room_id=? AND q_id=?", (room_id, pend["q_id"]))
        out.update(status="applied", code=o.code, via=pend["q_id"])
        return render(o.code, o.info, lang, names, date, staff_id)

    def _unparsed(self, c, rm, staff_id, msg_key, env, parsed, suggestion, source, names, lang, out):
        room_id, date = rm["room_id"], rm["date"]
        r = parsed.reason
        ko = lang == "ko"
        if r == "quoted":
            return "인용된 내용으로는 기록을 바꾸지 않습니다. 본인 메시지로 직접 보내 주세요." if ko else \
                "Quoted text never changes the record. Please send it as your own message."
        if r == "forwarded":
            return "전달된 메시지로는 기록을 바꾸지 않습니다." if ko else "Forwarded messages never change the record."
        if r == "ambiguous_time":
            s, e = parsed.info["start"], parsed.info["end"]
            kind = parsed.info.get("kind")
            verb = ({"inability": "불가", "availability": "가능"} if ko else
                    {"inability": "unavailable", "availability": "available"}).get(kind, "가능" if ko else "available")
            alt = f"{verb} {(s // 60) + 12:02d}-{(e // 60) + 12:02d}" if e // 60 + 12 <= 24 else f"{verb} {iv.fmt(s)}-{iv.fmt(e)}"
            return (f"{iv.fmt_range(s, e)}인가요, 오후인가요? 24시 표기로 보내 주세요. 예: `{alt}`" if ko
                    else f"Did you mean {iv.fmt_range(s, e)} or the afternoon? Please use 24-hour time, e.g. `{alt}`.")
        if r == "bad_range":
            return render(parsed.info.get("code", "NON_POSITIVE_OR_OVERNIGHT"), {}, lang, names, date)
        if r == "wrong_date":
            return (f"이 방은 {iv.date_label(date)} 근무만 다룹니다. 날짜를 확인해 주세요." if ko
                    else f"This room only covers {iv.date_label(date, 'en')}. Please check the date.")
        if r == "empty":
            return help_text(lang, "staff")
        # tentative / unknown
        if suggestion is None:
            ai_off = self.ai is None or not self.ai.enabled
            tail = (" (AI 해석이 지금 꺼져 있어 정확한 명령만 처리합니다.)" if ko else " (AI reading is off right now; exact commands still work.)") if ai_off else ""
            if r == "tentative":
                return ("확실하지 않은 표현이라 바로 기록하지 않았어요. 정하셨다면 `불가 2026-11-09 13:00-17:00`이나 `가능 13-15`처럼 보내 주세요." if ko
                        else "That sounds tentative, so nothing was recorded. When you are sure, send e.g. `unavailable 2026-11-09 13:00-17:00`.") + tail
            return ("무엇을 기록할지 알아듣지 못했어요. 예: `가능 13-15`, `불가 13-15`, `수락 P1-a`, `표`" if ko
                    else "I could not tell what to record. Try `available 13-15`, `unavailable 13-15`, `accept P1-a`, `status`.") + tail
        return self._from_suggestion(c, rm, staff_id, msg_key, env, suggestion, source, names, lang, out)

    def _from_suggestion(self, c, rm, staff_id, msg_key, env, s, source, names, lang, out):
        room_id, date = rm["room_id"], rm["date"]
        ko = lang == "ko"
        tag = (" · AI가 읽은 내용" if ko else " · read by AI") if source == "ai" else \
              (" · 규칙으로 읽은 내용" if ko else " · read by rule")
        out["interpreted_by"] = source
        if s.kind == "about_other_person":
            return ("다른 분의 시간이나 수락은 대신 기록할 수 없어요. 각자 본인 메시지로 보내야 합니다." if ko
                    else "I cannot record hours or acceptance for someone else. Each person replies for themselves.") + tag
        if s.kind == "none":
            return help_text(lang, "staff")
        if s.kind == "clarify":
            q = re.sub(r"[`@<>]", "", s.question or "")[:200].strip()
            return (q or ("정확한 시간을 24시 표기로 보내 주세요." if ko else "Please send the exact hours in 24-hour time.")) + tag
        action = {"kind": s.kind}
        if s.kind in ("availability", "inability", "withdraw"):
            if s.date and s.date != date:
                return (f"이 방은 {iv.date_label(date)} 근무만 다룹니다." if ko else f"This room only covers {iv.date_label(date, 'en')}.") + tag
            if s.start and s.end:
                try:
                    st_, en_ = iv.parse_hhmm(s.start), iv.parse_hhmm(s.end)
                except ValueError:
                    return render("NON_POSITIVE_OR_OVERNIGHT", {}, lang, names, date)
                bad = iv.valid_write_range(st_, en_)
                if bad:
                    return render(bad, {}, lang, names, date)
                action.update(start=st_, end=en_)
            elif s.kind != "withdraw":
                return ("몇 시부터 몇 시까지인지 24시 표기로 알려 주세요." if ko else "Which hours exactly? Please use 24-hour time.") + tag
        if s.kind in ("accept", "revoke"):
            prop = engine.open_proposal(c, room_id)
            mine = [p["part_id"] for p in engine.parts_of(c, room_id, prop["proposal_id"])
                    if p["staff_id"] == staff_id] if prop else []
            if s.part_id not in mine:
                return ("어느 구간인지 확실하지 않아요. `수락 P1-a`처럼 구간 번호를 넣어 보내 주세요." if ko
                        else "I am not sure which part you mean. Send e.g. `accept P1-a`.") + tag
            action["part_id"] = s.part_id
        q = engine.create_pending(c, room_id, staff_id, action, msg_key, env.received_ms, asked_user=env.sender,
                                         source_created_ms=env.created_ms)
        out.update(status="pending", pending=q)
        exp = iv.local_label(env.received_ms + engine.PENDING_TTL_MS, rm["timezone"]).split(" ")[1]
        return pending_question(action, q, names, lang, date, staff_id, exp) + tag

    # ------------------------------------------------------------ export side effect
    def _run_export(self, rm, msg_key, result):
        """Runs after the request is committed as processed, so a redelivery of
        the same message is a duplicate and never exports twice. Whatever the
        exporter raises (snapshot, mkdir, write), the room gets a closing reply
        and the way to retry is a new `export` message."""
        if self.exporter is None:
            return
        try:
            res = self.exporter(rm["room_id"], result["export"])
        except Exception as e:  # noqa: BLE001 - every failure must end in a reply
            res = {"ok": False, "error": type(e).__name__}
        result["export_result"] = res
        self._export_reply(rm["room_id"], msg_key, result.get("lang", "ko"), res)

    def _export_reply(self, room_id, msg_key, lang, res):
        if res.get("ok"):
            text = (f"{res['file']} 파일을 만들었습니다 (판본 #{res['version']}). 이 Mac의 exports 폴더와 현황표의 내보내기 목록에 있어요."
                    if lang == "ko" else f"Created {res['file']} (version #{res['version']}). It is in this Mac's exports folder and the board's export list.")
        elif res.get("error") == "interrupted":
            text = ("앞서 요청한 내보내기는 ShiftPatch가 다시 시작되면서 끝나지 않았습니다. 근무 기록은 그대로입니다. `내보내기`로 다시 요청해 주세요."
                    if lang == "ko" else "The export you asked for earlier did not finish because ShiftPatch restarted. Coverage is unchanged. Send `export` to make it again.")
        else:
            why = f" ({res['error']})" if res.get("error") else ""
            text = (f"파일을 만들지 못했습니다{why}. 확정된 내용은 그대로입니다. `내보내기`를 다시 보내면 새로 만듭니다." if lang == "ko"
                    else f"Export failed{why}. Confirmed coverage is unchanged. Send `export` again to make a new file.")
        with self.store.tx() as c:
            at = engine.room(c, room_id)["clock_offset_ms"] + int(time.time() * 1000)
            c.execute("INSERT OR IGNORE INTO outbox(room_id, idem_key, reply_to, body, state, created_ms) "
                      "VALUES (?,?,?,?,'pending',?)", (room_id, msg_key + ":export", None, text, at))

    def recover_unfinished_exports(self) -> int:
        """At startup: an export request that was committed but never got its
        closing reply (process stopped mid-export) gets one now, so the room is
        not left with only "Creating…". It does not re-run the export."""
        with self.store.snapshot() as c:
            rows = c.execute(
                "SELECT p.msg_key, p.room_id, p.result_json FROM processed p WHERE p.result_json LIKE '%\"export\":%' "
                "AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.idem_key = p.msg_key || ':export')").fetchall()
        n = 0
        for r in rows:
            res = json.loads(r["result_json"])
            if not res.get("export"):
                continue
            self._export_reply(r["room_id"], r["msg_key"], res.get("lang", "ko"), {"ok": False, "error": "interrupted"})
            n += 1
        return n


# ---------------------------------------------------------------- text views

def pending_question(action, q, names, lang, date, staff_id, expires_label):
    ko = lang == "ko"
    me = names(staff_id)
    d = iv.date_label(date, "ko" if ko else "en")
    k = action["kind"]
    rng = iv.fmt_range(action["start"], action["end"]) if action.get("start") is not None else ""
    until = (f" ({q}, {expires_label}까지)" if ko else f" ({q}, until {expires_label})") if expires_label else f" ({q})"
    if k == "inability":
        body = (f"{me}님, {d} {rng}을 '불가'로 기록할까요? 반영하면 맡은 시간이 빈 시간으로 표시됩니다." if ko
                else f"{me}, should I mark {d} {rng} unavailable? Your hours there would show as uncovered.")
    elif k == "availability":
        body = (f"{me}님, {d} {rng} 가능으로 기록할까요? 가능 기록은 근무를 맡는 수락과 다릅니다." if ko
                else f"{me}, should I record you as available {d} {rng}? Being available is not accepting a shift.")
    elif k == "withdraw":
        body = (f"{me}님의 가능 기록{(' ' + rng) if rng else ''}을 거둬들일까요?" if ko
                else f"{me}, withdraw your availability{(' ' + rng) if rng else ''}?")
    elif k == "accept":
        body = (f"{me}님, {action['part_id']} 구간을 맡겠다고 수락할까요?" if ko
                else f"{me}, accept part {action['part_id']}?")
    else:
        body = (f"{me}님, {action['part_id']} 수락을 취소할까요?" if ko else f"{me}, withdraw your acceptance of {action['part_id']}?")
    tail = (f" 맞으면 `네`, 아니면 `아니요`라고 답해 주세요.{until}" if ko else f" Reply `yes` or `no`.{until}")
    return body + tail


def status_text(c, rm, lang, names, board_url):
    ko = lang == "ko"
    cov = engine.coverage(c, rm["room_id"])
    label = {"original": ("원 근무", "original"), "confirmed": ("대체 확정", "confirmed"),
             "uncovered": ("미해결", "uncovered"), "conflict": ("중복", "conflict")}
    lines = [(f"{iv.date_label(rm['date'])} 담당 현황 (판본 #{rm['version']})" if ko
              else f"Coverage {iv.date_label(rm['date'], 'en')} (version #{rm['version']})")]
    for sg in cov:
        who = names(sg["staff_id"]) if sg["staff_id"] else "—"
        lines.append(f"{iv.fmt_range(sg['start'], sg['end'])}  {who}  {label[sg['status']][0 if ko else 1]}")
    if board_url:
        link = board_link(board_url, rm["room_id"])
        lines.append((f"현황표: {link} (이 Mac에서만 열립니다)" if ko else f"Board: {link} (opens on this Mac only)"))
    return "\n".join(lines)


def board_link(board_url, room_id):
    """Same board URL bound to this room (?room=…), fragment kept; the web app
    reads the room from the query string, so a bare link opens the demo room."""
    parts = urlsplit(board_url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "room"] + [("room", room_id)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def proposal_text(c, rm, lang, names):
    ko = lang == "ko"
    prop = engine.open_proposal(c, rm["room_id"])
    if prop is None:
        gaps = engine.gaps(c, rm["room_id"])
        if gaps:
            return ("지금 올라온 대체안은 없습니다. 빈 시간: " if ko else "No open proposal. Uncovered: ") + \
                ", ".join(iv.fmt_range(s, e) for s, e in gaps)
        return "빈 시간이 없습니다." if ko else "There are no gaps."
    v = engine.proposal_view(c, rm["room_id"], prop["proposal_id"])
    lines = [f"{iv.date_label(rm['date'], 'ko' if ko else 'en')} {'대체 근무안' if ko else 'proposal'} {v['proposal_id']}"]
    for p in v["parts"]:
        st = ("수락함" if ko else "accepted") if p["accepted"] else ("수락 대기" if ko else "waiting")
        if p["carried_from"]:
            st += f" ({p['carried_from']}에서 이어받음)" if ko else f" (carried from {p['carried_from']})"
        lines.append(f"{p['part_id']}  {names(p['staff_id'])}  {iv.fmt_range(p['start'], p['end'])}  {st}")
    lines.append(part_lines(v["parts"], names, ko, v["proposal_id"]))
    return "\n".join(lines)


def help_text(lang, role):
    if lang == "en":
        t = ("Commands: `available 13-15`, `unavailable 13-15`, `withdraw`, `accept P1-a`, `revoke P1-a`, "
             "`yes` / `no`, `status`, `proposal`, `export`")
        return t + (", `confirm P1`" if role == "manager" else "")
    t = "명령: `가능 13-15`, `불가 13-15`, `가능 취소`, `수락 P1-a`, `수락 취소 P1-a`, `네` / `아니요`, `표`, `대체안`, `내보내기`"
    return t + (", `확정 P1`" if role == "manager" else "")


# ---------------------------------------------------------------- rule reader

_RANGE = re.compile(r"(\d{2})(?::(\d{2}))?\s*시?\s*(?:-|~|–|부터)\s*(\d{2})(?::(\d{2}))?\s*시?")
_NEG = re.compile(r"(못|불가|안\s?될|안\s?돼|어렵|can't|cannot|unable|not able)", re.IGNORECASE)
_POS = re.compile(r"(가능|돼요|될\s?것|할\s?수\s?있|can do|available)", re.IGNORECASE)


@dataclass
class _RuleSuggestion:
    kind: str
    date: str
    start: str
    end: str
    part_id: str = ""
    lang: str = "ko"
    question: str = ""


def _rule_suggest(text, rm, created_ms):
    """Hedged sentence + one explicit two-digit range + one clear verb cue."""
    ranges = _RANGE.findall(text)
    neg, pos = bool(_NEG.search(text)), bool(_POS.search(text))
    if len(ranges) != 1 or neg == pos:
        return None
    h1, m1, h2, m2 = ranges[0]
    date = ""
    for word in ("오늘", "내일", "today", "tomorrow"):
        if word in text.lower():
            date = iv.resolve_relative_date(word, created_ms, rm["timezone"])
    return _RuleSuggestion("inability" if neg else "availability", date, f"{h1}:{m1 or '00'}", f"{h2}:{m2 or '00'}",
                           lang="ko" if re.search(r"[가-힣]", text) else "en")
