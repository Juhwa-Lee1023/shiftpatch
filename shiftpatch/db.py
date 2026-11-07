"""SQLite persistence. One writer at a time; every domain mutation is one
BEGIN IMMEDIATE transaction that commits state, history, the processed
marker and the reply outbox together, or nothing at all."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
  room_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('local_demo','switch')),
  label TEXT NOT NULL,
  date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  duty TEXT NOT NULL,
  roster_version INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 0,
  events_started INTEGER NOT NULL DEFAULT 0,
  clock_offset_ms INTEGER NOT NULL DEFAULT 0,
  proposal_counter INTEGER NOT NULL DEFAULT 0,
  pending_counter INTEGER NOT NULL DEFAULT 0,
  created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS staff (
  room_id TEXT NOT NULL REFERENCES rooms(room_id),
  staff_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  display_name_en TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('manager','staff')),
  fact_rev INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (room_id, staff_id)
);
CREATE TABLE IF NOT EXISTS links (
  room_id TEXT NOT NULL,
  platform_user_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  link_rev INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (room_id, platform_user_id),
  UNIQUE (room_id, staff_id)
);
CREATE TABLE IF NOT EXISTS base_shifts (
  room_id TEXT NOT NULL,
  shift_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  roster_version INTEGER NOT NULL,
  PRIMARY KEY (room_id, shift_id)
);
CREATE TABLE IF NOT EXISTS availability (
  room_id TEXT NOT NULL,
  avail_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL CHECK (state IN ('active','withdrawn')),
  source_msg TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  created_version INTEGER NOT NULL,
  PRIMARY KEY (room_id, avail_id)
);
CREATE TABLE IF NOT EXISTS inability (
  room_id TEXT NOT NULL,
  inab_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  source_msg TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  created_version INTEGER NOT NULL,
  PRIMARY KEY (room_id, inab_id)
);
CREATE TABLE IF NOT EXISTS proposals (
  room_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('open','confirmed','superseded')),
  created_version INTEGER NOT NULL,
  created_ms INTEGER NOT NULL,
  closed_reason TEXT,
  PRIMARY KEY (room_id, proposal_id)
);
CREATE TABLE IF NOT EXISTS parts (
  room_id TEXT NOT NULL,
  part_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  avail_id TEXT NOT NULL,
  avail_rev INTEGER NOT NULL,
  link_rev INTEGER NOT NULL,
  roster_version INTEGER NOT NULL,
  component_hash TEXT NOT NULL,
  PRIMARY KEY (room_id, part_id)
);
CREATE TABLE IF NOT EXISTS acceptances (
  room_id TEXT NOT NULL,
  acc_id TEXT NOT NULL,
  part_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  component_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('active','revoked')),
  carried_from_acc TEXT,
  source_msg TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY (room_id, acc_id)
);
CREATE TABLE IF NOT EXISTS assignments (
  room_id TEXT NOT NULL,
  asg_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  start_min INTEGER NOT NULL,
  end_min INTEGER NOT NULL,
  proposal_id TEXT NOT NULL,
  part_id TEXT NOT NULL,
  confirmed_version INTEGER NOT NULL,
  confirmed_ms INTEGER NOT NULL,
  PRIMARY KEY (room_id, asg_id),
  UNIQUE (room_id, part_id)
);
CREATE TABLE IF NOT EXISTS pending (
  room_id TEXT NOT NULL,
  q_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  origin_msg TEXT NOT NULL,
  action_json TEXT NOT NULL,
  dep_json TEXT NOT NULL,
  expires_ms INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('open','applied','declined','stale','superseded','expired')),
  created_ms INTEGER NOT NULL,
  asked_user TEXT,
  source_created_ms INTEGER,
  PRIMARY KEY (room_id, q_id)
);
CREATE TABLE IF NOT EXISTS watermarks (
  room_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  last_created_ms INTEGER NOT NULL,
  last_msg TEXT NOT NULL,
  PRIMARY KEY (room_id, staff_id)
);
CREATE TABLE IF NOT EXISTS exec_ctx (
  ctx_id TEXT PRIMARY KEY,
  room_id TEXT NOT NULL,
  msg_key TEXT NOT NULL,
  staff_id TEXT,
  role TEXT,
  allowed_json TEXT NOT NULL,
  expires_ms INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('issued','used','expired'))
);
CREATE TABLE IF NOT EXISTS processed (
  msg_key TEXT PRIMARY KEY,
  room_id TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  result_json TEXT NOT NULL,
  version_after INTEGER NOT NULL,
  processed_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  at_ms INTEGER NOT NULL,
  kind TEXT NOT NULL,
  actor_staff TEXT,
  detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL,
  idem_key TEXT NOT NULL UNIQUE,
  reply_to TEXT,
  body TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','sent','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_ms INTEGER NOT NULL,
  sent_ms INTEGER,
  next_attempt_ms INTEGER NOT NULL DEFAULT 0,
  claim TEXT,
  claimed_until_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS exports (
  export_id TEXT PRIMARY KEY,
  room_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('csv','ics')),
  version INTEGER NOT NULL,
  file_name TEXT,
  sha256 TEXT,
  rows INTEGER,
  state TEXT NOT NULL CHECK (state IN ('published','failed')),
  error TEXT,
  created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bridge_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Chat accounts that wrote to the agent before they were linked: the
-- transport's sender id and display name only, never the message text.
-- Rows expire after engine.UNLINKED_SEEN_TTL_MS and go away once linked.
CREATE TABLE IF NOT EXISTS unlinked_seen (
  room_id TEXT NOT NULL,
  platform_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  first_ms INTEGER NOT NULL,
  last_ms INTEGER NOT NULL,
  seen_count INTEGER NOT NULL,
  PRIMARY KEY (room_id, platform_user_id)
);
"""

# Columns added after the first release; ALTER TABLE keeps existing data files.
MIGRATIONS = [
    ("pending", "asked_user", "TEXT"),
    ("pending", "source_created_ms", "INTEGER"),
    ("outbox", "next_attempt_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("outbox", "claim", "TEXT"),
    ("outbox", "claimed_until_ms", "INTEGER NOT NULL DEFAULT 0"),
]


class Store:
    """Owns the SQLite file. `tx()` serialises writers process-wide."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._write_lock = threading.RLock()
        self.fault = None  # test hook: callable(point) that may raise
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        c = self._connect()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            for table, col, decl in MIGRATIONS:
                if col not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            # An open confirmation question written before source_created_ms existed has no
            # record of when its message was written, so no yes/no can be matched to it safely.
            # Close it (state 'stale'); its action was never applied. Nothing else is touched:
            # confirmed coverage, history, versions and other rooms stay as they are. The time
            # is not guessed from the receive time.
            self.legacy_questions_closed = c.execute(
                "UPDATE pending SET state='stale' WHERE state='open' AND source_created_ms IS NULL").rowcount
        finally:
            c.close()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def hit(self, point: str):
        if self.fault:
            self.fault(point)

    @contextmanager
    def tx(self):
        with self._write_lock:
            c = self._connect()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                self.hit("before_commit")
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()

    @contextmanager
    def snapshot(self):
        """A read transaction: every SELECT inside sees one committed state."""
        c = self._connect()
        try:
            c.execute("BEGIN")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
