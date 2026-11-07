"""Reply delivery, independent of domain commits. A committed state change
is never re-run to resend its reply; only the outbox row is retried."""
from __future__ import annotations

import threading
import time

MAX_ATTEMPTS = 5


class Dispatcher:
    def __init__(self, store, senders: dict):
        self.store, self.senders = store, senders  # kind -> callable(room_id, row)
        self._stop = threading.Event()

    def run_once(self) -> int:
        with self.store.snapshot() as c:
            rows = c.execute("SELECT o.*, r.kind FROM outbox o JOIN rooms r ON r.room_id=o.room_id "
                             "WHERE o.state='pending' ORDER BY o.id LIMIT 50").fetchall()
        sent = 0
        for row in rows:
            send = self.senders.get(row["kind"])
            if send is None:
                continue
            try:
                send(row["room_id"], row)
            except Exception as e:
                with self.store.tx() as c:
                    c.execute("UPDATE outbox SET attempts=attempts+1, last_error=?, "
                              "state=CASE WHEN attempts+1>=? THEN 'failed' ELSE 'pending' END WHERE id=?",
                              (type(e).__name__ + ": " + str(e)[:120], MAX_ATTEMPTS, row["id"]))
                continue
            with self.store.tx() as c:
                c.execute("UPDATE outbox SET state='sent', attempts=attempts+1, sent_ms=? WHERE id=? AND state='pending'",
                          (int(time.time() * 1000), row["id"]))
            sent += 1
        return sent

    def retry_failed(self, room_id):
        with self.store.tx() as c:
            return c.execute("UPDATE outbox SET state='pending', attempts=0 WHERE room_id=? AND state='failed'",
                             (room_id,)).rowcount

    def loop(self, interval=0.3):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                pass
            self._stop.wait(interval)

    def start(self):
        threading.Thread(target=self.loop, daemon=True, name="outbox").start()

    def stop(self):
        self._stop.set()
