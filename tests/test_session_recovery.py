"""Tests for the orphan-active-session recovery path on daemon startup."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from openchronicle import config as config_mod
from openchronicle.session import recovery
from openchronicle.session import store as session_store
from openchronicle.store import fts
from openchronicle.timeline import store as timeline_store


def _ts(s: str) -> datetime:
    """Parse a wall-clock-with-tz ISO string to a tz-aware datetime."""
    return datetime.fromisoformat(s)


def _insert_active(conn, *, session_id: str, start: str) -> None:
    session_store.insert(
        conn,
        session_store.SessionRow(
            id=session_id, start_time=_ts(start), status="active",
        ),
    )


def _insert_block(conn, *, start: str, end: str) -> None:
    timeline_store.insert(
        conn,
        timeline_store.TimelineBlock(
            start_time=_ts(start),
            end_time=_ts(end),
            entries=["[Cursor] worked on something"],
            apps_used=["Cursor"],
            capture_count=3,
        ),
    )


def _cfg(ac_root: Path) -> config_mod.Config:
    return config_mod.load(ac_root / "config.toml")


def test_recover_no_orphans_is_noop(ac_root: Path) -> None:
    """Empty DB → returns 0, no errors."""
    cfg = _cfg(ac_root)
    assert recovery.recover_orphan_sessions(cfg) == 0


def test_recover_orphan_with_blocks_uses_latest_block_end(ac_root: Path) -> None:
    """An orphan with persisted timeline blocks ends at the latest block end."""
    cfg = _cfg(ac_root)
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_a", start="2026-04-26T09:00:00+08:00")
        _insert_block(conn, start="2026-04-26T09:00:00+08:00", end="2026-04-26T09:01:00+08:00")
        _insert_block(conn, start="2026-04-26T09:01:00+08:00", end="2026-04-26T09:02:00+08:00")
        _insert_block(conn, start="2026-04-26T09:25:00+08:00", end="2026-04-26T09:26:00+08:00")

    assert recovery.recover_orphan_sessions(cfg) == 1

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_a")
        assert row is not None
        assert row.status == "ended"
        assert row.end_time == _ts("2026-04-26T09:26:00+08:00")


def test_recover_orphan_with_no_blocks_uses_one_minute_fallback(ac_root: Path) -> None:
    """Crash before any block was aggregated → end_time = start + 1min."""
    cfg = _cfg(ac_root)
    start = "2026-04-26T09:00:00+08:00"
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_b", start=start)

    assert recovery.recover_orphan_sessions(cfg) == 1

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_b")
        assert row is not None
        assert row.status == "ended"
        assert row.end_time == _ts(start) + timedelta(minutes=1)


def test_recover_two_orphans_dont_pollute_each_other(ac_root: Path) -> None:
    """Two consecutive orphans: A's blocks must not extend into B's window.

    Without ``next_session_start_after`` the latest-block-in-window query
    for A would walk all the way up to A.start + max_session_hours and
    swallow B's blocks too, ending A at B's last activity instead of
    A's last activity.
    """
    cfg = _cfg(ac_root)
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_a", start="2026-04-26T09:00:00+08:00")
        _insert_active(conn, session_id="sess_b", start="2026-04-26T09:35:00+08:00")
        # Blocks attributable to A
        _insert_block(conn, start="2026-04-26T09:00:00+08:00", end="2026-04-26T09:01:00+08:00")
        _insert_block(conn, start="2026-04-26T09:25:00+08:00", end="2026-04-26T09:26:00+08:00")
        # Blocks attributable to B (must NOT count toward A's end_time)
        _insert_block(conn, start="2026-04-26T09:35:00+08:00", end="2026-04-26T09:36:00+08:00")
        _insert_block(conn, start="2026-04-26T09:50:00+08:00", end="2026-04-26T09:51:00+08:00")

    assert recovery.recover_orphan_sessions(cfg) == 2

    with fts.cursor() as conn:
        a = session_store.get_by_id(conn, "sess_a")
        b = session_store.get_by_id(conn, "sess_b")
        assert a is not None and b is not None
        assert a.end_time == _ts("2026-04-26T09:26:00+08:00"), (
            "A should end at its own last block, not bleed into B's window"
        )
        assert b.end_time == _ts("2026-04-26T09:51:00+08:00")


def test_recover_caps_at_max_session_hours(ac_root: Path) -> None:
    """A wildly distant block must not stretch the orphan past max_session_hours.

    A timeline block from a totally unrelated future moment (e.g. a
    later session that somehow lost its row) shouldn't pull the
    orphan's end_time past the SessionManager's physical session
    ceiling.
    """
    cfg = _cfg(ac_root)
    # max_session_hours default is 2; place a stray block 5h after start.
    start = "2026-04-26T09:00:00+08:00"
    far_block = "2026-04-26T14:30:00+08:00"
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_a", start=start)
        _insert_block(conn, start=far_block, end="2026-04-26T14:31:00+08:00")

    assert recovery.recover_orphan_sessions(cfg) == 1

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_a")
        assert row is not None
        # No block exists inside [start, start+2h], so we fall back to
        # the 1-min empty-session sentinel.
        assert row.end_time == _ts(start) + timedelta(minutes=1)


def test_recover_is_idempotent(ac_root: Path) -> None:
    """Calling twice: second call sees no active rows, no changes."""
    cfg = _cfg(ac_root)
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_a", start="2026-04-26T09:00:00+08:00")

    assert recovery.recover_orphan_sessions(cfg) == 1
    assert recovery.recover_orphan_sessions(cfg) == 0

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_a")
        assert row is not None
        assert row.status == "ended"


def test_recovered_session_visible_to_reduce_all_pending_query(ac_root: Path) -> None:
    """After recovery the row matches the safety-net's catch-up SQL.

    This is the integration check: ``list_pending_reduction`` is the
    query the daily safety-net uses, and it filters
    ``status IN ('ended', 'failed') AND end_time IS NOT NULL``.
    The recovery's whole point is to flip the orphan from ``active`` →
    ``ended`` so this query picks it up.
    """
    cfg = _cfg(ac_root)
    with fts.cursor() as conn:
        _insert_active(conn, session_id="sess_a", start="2026-04-26T09:00:00+08:00")
        _insert_block(conn, start="2026-04-26T09:00:00+08:00", end="2026-04-26T09:01:00+08:00")

    recovery.recover_orphan_sessions(cfg)

    with fts.cursor() as conn:
        pending = session_store.list_pending_reduction(conn)
        assert len(pending) == 1
        assert pending[0].id == "sess_a"
        assert pending[0].status == "ended"
        assert pending[0].end_time is not None
