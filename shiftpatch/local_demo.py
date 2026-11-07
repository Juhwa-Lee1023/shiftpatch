"""Local synthetic demo room. This is NOT Switch: one person operates four
fixed synthetic accounts on one Mac to rehearse the flow. The actor picker
exists only here and only for the `local_demo` room kind; the Switch path
takes its actor from the Switch event and has no such parameter.

Human message text is kept in memory only (never written to disk), so a
restart clears the transcript while the structured record stays."""
from __future__ import annotations

import itertools
import threading
import time

from . import engine, roster
from .agent import TrustedEnvelope

SYNTHETIC_USERS = {d["staff_id"]: d["local_user"] for d in roster.DIRECTORY}


class LocalDemoRoom:
    def __init__(self, store, agent):
        self.store, self.agent = store, agent
        self.transcript = {}  # room_id -> list[dict]
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.boot = int(time.time())

    def post(self, room_id: str, actor: str, body: str) -> dict:
        if actor not in SYNTHETIC_USERS:
            raise PermissionError("unknown synthetic actor")
        if len(body) > 1000:
            raise ValueError("MESSAGE_TOO_LONG")
        with self.store.snapshot() as c:
            rm = engine.room(c, room_id)
        if rm["kind"] != "local_demo":
            raise PermissionError("the actor picker only exists for the local demo room")
        now = roster.room_now_ms(rm)
        mid = f"demo-{self.boot}-{next(self._ids)}"
        with self._lock:
            self.transcript.setdefault(room_id, []).append(
                {"id": mid, "who": actor, "kind": "human", "body": body, "at": now})
        env = TrustedEnvelope(source="local_demo", room_id=room_id, message_id=mid, sender=SYNTHETIC_USERS[actor],
                              sender_name=actor, body=body, created_ms=now, received_ms=now,
                              addressed=body.lstrip().lower().startswith("@shiftpatch"))
        result = self.agent.handle(env)
        result["message_id"] = mid
        return result

    def deliver(self, room_id, row):
        """Outbox sender for the local room: append the agent's reply."""
        with self._lock:
            self.transcript.setdefault(room_id, []).append(
                {"id": f"out-{row['id']}", "who": "shiftpatch", "kind": "agent", "body": row["body"],
                 "reply_to": row["reply_to"], "at": row["created_ms"]})

    def messages(self, room_id):
        with self._lock:
            return list(self.transcript.get(room_id, []))

    def clear(self, room_id):
        with self._lock:
            self.transcript.pop(room_id, None)
