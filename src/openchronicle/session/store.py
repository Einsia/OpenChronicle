"""SQLite-backed store for work sessions.

Lives in the shared ``index.db`` alongside ``timeline_blocks`` and
``entries``. A session row tracks when a user was actively working and
carries the S2-reducer retry state (so retries survive a daemon
restart and the daily 23:55 safety-net can pick up unfinished work).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SessionStatus = Literal["active", "ended", "reduced", "failed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    flush_end TEXT,
    classified_end TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_sessions_retry ON sessions(next_retry_at)
    WHERE status = 'failed';
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Backfill columns added after initial schema."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "flush_end" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN flush_end TEXT")
    if "classified_end" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN classified_end TEXT")


@dataclass
class SessionRow:
    id: str
    start_time: datetime
    end_time: datetime | None = None
    status: SessionStatus = "active"
    retry_count: int = 0
    next_retry_at: datetime | None = None
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    flush_end: datetime | None = None
    classified_end: datetime | None = None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)


def insert(conn: sqlite3.Connection, row: SessionRow) -> None:
    now = datetime.now().astimezone().isoformat()
    conn.execute(
        """
        INSERT OR IGNORE INTO sessions
            (id, start_time, end_time, status, retry_count, next_retry_at,
             last_error, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.start_time.isoformat(),
            row.end_time.isoformat() if row.end_time else None,
            row.status,
            row.retry_count,
            row.next_retry_at.isoformat() if row.next_retry_at else None,
            row.last_error,
            (row.created_at or datetime.now().astimezone()).isoformat(),
            (row.updated_at or datetime.now().astimezone()).isoformat() or now,
        ),
    )


def mark_ended(conn: sqlite3.Connection, session_id: str, end_time: datetime) -> None:
    conn.execute(
        """
        UPDATE sessions
           SET end_time=?, status='ended', updated_at=?
         WHERE id=? AND status='active'
        """,
        (end_time.isoformat(), datetime.now().astimezone().isoformat(), session_id),
    )


def mark_reduced(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET status='reduced', updated_at=? WHERE id=?",
        (datetime.now().astimezone().isoformat(), session_id),
    )


def mark_failed(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    error: str,
    next_retry_at: datetime | None,
) -> None:
    conn.execute(
        """
        UPDATE sessions
           SET status='failed',
               retry_count = retry_count + 1,
               next_retry_at=?,
               last_error=?,
               updated_at=?
         WHERE id=?
        """,
        (
            next_retry_at.isoformat() if next_retry_at else None,
            error,
            datetime.now().astimezone().isoformat(),
            session_id,
        ),
    )


def get_by_id(conn: sqlite3.Connection, session_id: str) -> SessionRow | None:
    r = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return _to_row(r) if r else None


def get_open(conn: sqlite3.Connection) -> SessionRow | None:
    r = conn.execute(
        "SELECT * FROM sessions WHERE status='active' ORDER BY start_time DESC LIMIT 1"
    ).fetchone()
    return _to_row(r) if r else None


def set_flush_end(
    conn: sqlite3.Connection, session_id: str, flush_end: datetime,
) -> None:
    conn.execute(
        "UPDATE sessions SET flush_end=?, updated_at=? WHERE id=?",
        (
            flush_end.isoformat(),
            datetime.now().astimezone().isoformat(),
            session_id,
        ),
    )


def set_classified_end(
    conn: sqlite3.Connection, session_id: str, classified_end: datetime,
) -> None:
    conn.execute(
        "UPDATE sessions SET classified_end=?, updated_at=? WHERE id=?",
        (
            classified_end.isoformat(),
            datetime.now().astimezone().isoformat(),
            session_id,
        ),
    )


def list_active(conn: sqlite3.Connection) -> list[SessionRow]:
    rows = conn.execute(
        "SELECT * FROM sessions WHERE status='active' ORDER BY start_time ASC"
    ).fetchall()
    return [_to_row(r) for r in rows]


def list_due_for_retry(conn: sqlite3.Connection, *, now: datetime) -> list[SessionRow]:
    rows = conn.execute(
        """
        SELECT * FROM sessions
         WHERE status='failed'
           AND (next_retry_at IS NULL OR next_retry_at <= ?)
         ORDER BY start_time ASC
        """,
        (now.isoformat(),),
    ).fetchall()
    return [_to_row(r) for r in rows]


def list_unfinished_for_date(
    conn: sqlite3.Connection, *, day_start: datetime, day_end: datetime
) -> list[SessionRow]:
    """Sessions that started during [day_start, day_end) and aren't reduced."""
    rows = conn.execute(
        """
        SELECT * FROM sessions
         WHERE start_time >= ?
           AND start_time < ?
           AND status != 'reduced'
         ORDER BY start_time ASC
        """,
        (day_start.isoformat(), day_end.isoformat()),
    ).fetchall()
    return [_to_row(r) for r in rows]


def list_pending_reduction(conn: sqlite3.Connection) -> list[SessionRow]:
    """All non-reduced, non-active rows — the safety-net retry universe.

    Picks up ``ended`` rows whose reducer thread was killed mid-run
    (daemon shutdown) as well as ``failed`` rows regardless of
    ``next_retry_at`` (the daily cron is an unconditional catch-up
    pass, not the scheduled retry tick).
    """
    rows = conn.execute(
        """
        SELECT * FROM sessions
         WHERE status IN ('ended', 'failed')
           AND end_time IS NOT NULL
         ORDER BY start_time ASC
        """,
    ).fetchall()
    return [_to_row(r) for r in rows]


def _to_row(r: sqlite3.Row) -> SessionRow:
    def _dt(v: str | None) -> datetime | None:
        if not v:
            return None
        try:
            return datetime.fromisoformat(v)
        except (TypeError, ValueError):
            return None

    # Older rows may not have flush_end / classified_end columns; PRAGMA
    # migration adds them but existing rows default to NULL (→ None).
    flush_end: datetime | None = None
    try:
        flush_end = _dt(r["flush_end"])
    except (IndexError, KeyError):
        flush_end = None
    classified_end: datetime | None = None
    try:
        classified_end = _dt(r["classified_end"])
    except (IndexError, KeyError):
        classified_end = None
    return SessionRow(
        id=r["id"],
        start_time=_dt(r["start_time"]) or datetime.now().astimezone(),
        end_time=_dt(r["end_time"]),
        status=r["status"] or "active",
        retry_count=r["retry_count"] or 0,
        next_retry_at=_dt(r["next_retry_at"]),
        last_error=r["last_error"] or "",
        created_at=_dt(r["created_at"]),
        updated_at=_dt(r["updated_at"]),
        flush_end=flush_end,
        classified_end=classified_end,
    )
