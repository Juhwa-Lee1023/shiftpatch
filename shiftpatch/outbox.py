"""Reply delivery, independent of domain commits. A committed state change
is never re-run to resend its reply; only the outbox row is retried.

Rules:
- One dispatch pass at a time per process (lock), and each row is claimed
  with a short lease in SQLite before it is handed to a sender, so two
  dispatchers on the same data file never send the same row concurrently.
- Replies in one room go out in commit order. While the oldest unsent reply
  in a room is waiting to be retried, later replies in that room wait too.
- A failed send is retried with exponential backoff (1 s, 2 s, 4 s … capped
  at 60 s). After MAX_ATTEMPTS the row is parked as `failed`, shown on the
  board, and later replies in that room continue. `retry_failed` puts it back
  in line; it goes out with a short "delayed reply" note.
- Delivery is at least once, not exactly once: if the process stops after the
  chat server accepted a reply but before the row is marked sent, the lease
  runs out and the reply is posted again. The transport has no idempotency
  key we could use to rule that out.
"""
from __future__ import annotations

import re
import threading
import time
import uuid

MAX_ATTEMPTS = 6
BACKOFF_BASE_MS = 1000
BACKOFF_CAP_MS = 60 * 1000
LEASE_MS = 60 * 1000


def backoff_ms(attempts: int) -> int:
    """Delay after the n-th failed attempt (n >= 1)."""
    return min(BACKOFF_BASE_MS * 2 ** (attempts - 1), BACKOFF_CAP_MS)


class Dispatcher:
    def __init__(self, store, senders: dict, clock=lambda: int(time.time() * 1000)):
        self.store, self.senders, self.clock = store, senders, clock  # kind -> callable(room_id, row)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.name = uuid.uuid4().hex[:12]

    def run_once(self) -> int:
        """One pass. Returns how many rows this call sent. A call that finds
        another pass already running returns 0 at once; that pass, or the
        next loop tick, delivers the rows."""
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            return self._pass()
        finally:
            self._lock.release()

    def _pass(self) -> int:
        now = self.clock()
        with self.store.snapshot() as c:
            rows = c.execute("SELECT o.*, r.kind FROM outbox o JOIN rooms r ON r.room_id=o.room_id "
                             "WHERE o.state='pending' ORDER BY o.id LIMIT 200").fetchall()
        sent = 0
        blocked = set()
        for row in rows:
            room = row["room_id"]
            if room in blocked:
                continue
            send = self.senders.get(row["kind"])
            if send is None or row["next_attempt_ms"] > now or row["claimed_until_ms"] > now:
                blocked.add(room)          # head of this room's line is not ready; keep order
                continue
            if not self._claim(row["id"], now):
                blocked.add(room)
                continue
            try:
                send(room, row)
            except Exception as e:  # noqa: BLE001 - any sender failure is a delivery failure
                self._failed(row, e, now)
                blocked.add(room)
                continue
            with self.store.tx() as c:
                c.execute("UPDATE outbox SET state='sent', attempts=attempts+1, sent_ms=?, claim=NULL, claimed_until_ms=0 "
                          "WHERE id=? AND claim=?", (self.clock(), row["id"], self.name))
            sent += 1
        return sent

    def _claim(self, row_id, now) -> bool:
        with self.store.tx() as c:
            return c.execute("UPDATE outbox SET claim=?, claimed_until_ms=? WHERE id=? AND state='pending' "
                             "AND claimed_until_ms<=?", (self.name, now + LEASE_MS, row_id, now)).rowcount == 1

    def _failed(self, row, e, now):
        n = row["attempts"] + 1
        err = (type(e).__name__ + ": " + str(e))[:160]
        with self.store.tx() as c:
            c.execute("UPDATE outbox SET attempts=?, last_error=?, claim=NULL, claimed_until_ms=0, next_attempt_ms=?, "
                      "state=CASE WHEN ?>=? THEN 'failed' ELSE 'pending' END WHERE id=? AND claim=?",
                      (n, err, now + backoff_ms(n), n, MAX_ATTEMPTS, row["id"], self.name))

    def retry_failed(self, room_id) -> int:
        """Board button / POST /api/outbox/retry. Only the reply rows move;
        no domain action runs again."""
        with self.store.tx() as c:
            rows = c.execute("SELECT id, body FROM outbox WHERE room_id=? AND state='failed'", (room_id,)).fetchall()
            for r in rows:
                ko = bool(re.search(r"[가-힣]", r["body"]))
                note = "(늦게 전달되는 답장입니다)\n" if ko else "(Delayed reply)\n"
                body = r["body"] if r["body"].startswith(note) else note + r["body"]
                c.execute("UPDATE outbox SET state='pending', attempts=0, next_attempt_ms=0, claim=NULL, "
                          "claimed_until_ms=0, body=? WHERE id=?", (body, r["id"]))
            return len(rows)

    def loop(self, interval=0.3):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - keep the loop alive; rows stay pending
                pass
            self._stop.wait(interval)

    def start(self):
        threading.Thread(target=self.loop, daemon=True, name="outbox").start()

    def stop(self):
        self._stop.set()


def delivery_view(c, room_id, now_ms):
    """Rows the board should mention: parked failures and replies that are
    waiting for a retry. Bodies are ShiftPatch's own replies, never people's
    messages."""
    out = []
    for r in c.execute("SELECT id, state, attempts, last_error, next_attempt_ms, body FROM outbox "
                       "WHERE room_id=? AND (state='failed' OR (state='pending' AND attempts>0)) ORDER BY id",
                       (room_id,)):
        out.append({"id": r["id"], "state": r["state"], "attempts": r["attempts"], "last_error": r["last_error"],
                    "retry_in_ms": max(0, r["next_attempt_ms"] - now_ms) if r["state"] == "pending" else None,
                    "excerpt": r["body"].split("\n")[0][:90]})
    return out
