"""Local synthetic demo room. This is NOT Switch: one person operates four
fixed synthetic accounts on one Mac to rehearse the flow. The actor picker
exists only here and only for the `local_demo` room kind; the Switch path
takes its actor from the Switch event and has no such parameter.

Human message text is kept in memory only (never written to disk), so a
restart clears the transcript while the structured record stays.

Messages in one room are handled one at a time, in the order they arrived,
like the single worker on the Switch path. The agent keeps one execution
context per room, so two overlapping requests (a second Send while the AI
is still reading the first) would otherwise void the first one. Two locks,
never nested the other way round:
- `_turns` (a condition) hands out arrival tickets and lets one message per
  room through `agent.handle` at a time;
- `_lock` guards only the in-memory transcript, so the reply sender
  (`deliver`) never waits behind a slow interpretation."""
from __future__ import annotations

import itertools
import threading
import time

from . import engine, roster
from .agent import TrustedEnvelope

SYNTHETIC_USERS = {d["staff_id"]: d["local_user"] for d in roster.DIRECTORY}
MAX_WAITING = 8          # per room; more than this is refused instead of queued
WAIT_LIMIT_S = 180.0     # a message that cannot start within this time is refused, nothing recorded


class NotLocalDemo(PermissionError):
    """The request is not allowed through the actor picker at all."""


class DemoRoomBusy(RuntimeError):
    """Too many messages already waiting in this room."""


class LocalDemoRoom:
    def __init__(self, store, agent):
        self.store, self.agent = store, agent
        self.transcript = {}  # room_id -> list[dict]
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._turns = threading.Condition()
        self._next = {}       # room_id -> next ticket to hand out
        self._serving = {}    # room_id -> ticket now allowed to run
        self._last_ms = {}    # room_id -> last message time handed out
        self._skipped = set() # (room_id, ticket) that gave up waiting
        self.boot = int(time.time())

    def post(self, room_id: str, actor: str, body: str) -> dict:
        if actor not in SYNTHETIC_USERS:
            raise NotLocalDemo("unknown synthetic actor")
        if len(body) > 1000:
            raise ValueError("MESSAGE_TOO_LONG")
        with self.store.snapshot() as c:
            rm = engine.room(c, room_id)
        if rm["kind"] != "local_demo":
            raise NotLocalDemo("the actor picker only exists for the local demo room")
        with self._turns:
            waiting = self._next.get(room_id, 0) - self._serving.get(room_id, 0)
            if waiting >= MAX_WAITING:
                raise DemoRoomBusy("DEMO_ROOM_BUSY")
            ticket = self._next.get(room_id, 0)
            self._next[room_id] = ticket + 1
            # Arrival order fixes the message id, the transcript position and the
            # message time together; times never repeat, so the watermark keeps order.
            now = max(roster.room_now_ms(rm), self._last_ms.get(room_id, 0) + 1)
            self._last_ms[room_id] = now
            mid = f"demo-{self.boot}-{next(self._ids)}"
            with self._lock:
                self.transcript.setdefault(room_id, []).append(
                    {"id": mid, "who": actor, "kind": "human", "body": body, "at": now})
            deadline = time.monotonic() + WAIT_LIMIT_S
            while self._serving.get(room_id, 0) != ticket:
                left = deadline - time.monotonic()
                if left <= 0 or not self._turns.wait(left):
                    if self._serving.get(room_id, 0) == ticket:
                        break
                    # Give up our turn; whoever is ahead still advances past it.
                    self._skip(room_id, ticket)
                    raise DemoRoomBusy("DEMO_ROOM_BUSY")
        try:
            env = TrustedEnvelope(source="local_demo", room_id=room_id, message_id=mid, sender=SYNTHETIC_USERS[actor],
                                  sender_name=actor, body=body, created_ms=now, received_ms=now,
                                  addressed=body.lstrip().lower().startswith("@shiftpatch"))
            result = self.agent.handle(env)
        finally:
            with self._turns:
                self._advance(room_id)
        result["message_id"] = mid
        return result

    # ticket bookkeeping, always under self._turns
    def _skip(self, room_id, ticket):
        self._skipped.add((room_id, ticket))

    def _advance(self, room_id):
        n = self._serving.get(room_id, 0) + 1
        while (room_id, n) in self._skipped:
            self._skipped.discard((room_id, n))
            n += 1
        self._serving[room_id] = n
        self._turns.notify_all()

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
