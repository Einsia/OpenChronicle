"""SQLite-backed store for timeline blocks (default 1-min wall-clock windows).

Lives in the shared ``index.db`` so users still have one file to back
up. The schema enforces a uniqueness constraint on
``(start_time, end_time)`` so the aggregator tick is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS timeline_blocks (
    id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT '',
    entries TEXT NOT NULL,
    apps_used TEXT NOT NULL,
    capture_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(start_time, end_time)
);
CREATE INDEX IF NOT EXISTS idx_tlb_start ON timeline_blocks(start_time);
CREATE INDEX IF NOT EXISTS idx_tlb_end ON timeline_blocks(end_time);
"""


@dataclass
class TimelineBlock:
    start_time: datetime
    end_time: datetime
    timezone: str = ""
    entries: list[str] = field(default_factory=list)
    apps_used: list[str] = field(default_factory=list)
    capture_count: int = 0
    id: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = _make_id(self.start_time)
        if self.created_at is None:
            self.created_at = datetime.now().astimezone()


def _make_id(start: datetime) -> str:
    stamp = start.strftime("%Y%m%d-%H%M")
    suffix = hashlib.blake2s(os.urandom(8), digest_size=2).hexdigest()
    return f"tlb-{stamp}-{suffix}"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def has_window(conn: sqlite3.Connection, start: datetime, end: datetime) -> bool:
    row = conn.execute(
        "SELECT 1 FROM timeline_blocks WHERE start_time=? AND end_time=? LIMIT 1",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return row is not None


def insert(conn: sqlite3.Connection, block: TimelineBlock) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO timeline_blocks
            (id, start_time, end_time, timezone, entries, apps_used, capture_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            block.id,
            block.start_time.isoformat(),
            block.end_time.isoformat(),
            block.timezone,
            json.dumps(block.entries, ensure_ascii=False),
            json.dumps(block.apps_used, ensure_ascii=False),
            block.capture_count,
            (block.created_at or datetime.now().astimezone()).isoformat(),
        ),
    )


def get_latest_end(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT end_time FROM timeline_blocks ORDER BY end_time DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except (TypeError, ValueError):
        return None


def query_recent(conn: sqlite3.Connection, *, limit: int = 12) -> list[TimelineBlock]:
    """Most recent blocks, oldest first in the returned list."""
    rows = conn.execute(
        "SELECT * FROM timeline_blocks ORDER BY start_time DESC LIMIT ?",
        (limit,),
    ).fetchall()
    blocks = [_row_to_block(r) for r in rows]
    blocks.reverse()
    return blocks


def query_since(conn: sqlite3.Connection, since: datetime) -> list[TimelineBlock]:
    """All blocks with end_time > ``since``, chronological order."""
    rows = conn.execute(
        "SELECT * FROM timeline_blocks WHERE end_time > ? ORDER BY start_time ASC",
        (since.isoformat(),),
    ).fetchall()
    return [_row_to_block(r) for r in rows]


def _row_to_block(row: sqlite3.Row | tuple) -> TimelineBlock:
    # Row indexing works for both sqlite3.Row and tuple
    get = row.__getitem__
    return TimelineBlock(
        id=get("id"),
        start_time=datetime.fromisoformat(get("start_time")),
        end_time=datetime.fromisoformat(get("end_time")),
        timezone=get("timezone") or "",
        entries=json.loads(get("entries") or "[]"),
        apps_used=json.loads(get("apps_used") or "[]"),
        capture_count=get("capture_count") or 0,
        created_at=datetime.fromisoformat(get("created_at")) if get("created_at") else None,
    )


def floor_to_window(moment: datetime, window_minutes: int) -> datetime:
    """Floor to the wall-clock window boundary. 14:07:42 → 14:05:00 (w=5)."""
    floor_min = (moment.minute // window_minutes) * window_minutes
    return moment.replace(minute=floor_min, second=0, microsecond=0)


def iter_windows(
    start: datetime, end: datetime, window_minutes: int
) -> list[tuple[datetime, datetime]]:
    """Return the list of complete closed windows in ``[start, end)``.

    ``start`` is floored first; windows that would extend past ``end`` are
    not returned (partial trailing windows are left for a later tick).
    """
    cursor = floor_to_window(start, window_minutes)
    if cursor < start:
        cursor = start
    step = timedelta(minutes=window_minutes)
    out: list[tuple[datetime, datetime]] = []
    while cursor + step <= end:
        out.append((cursor, cursor + step))
        cursor = cursor + step
    return out
