"""Recover sessions left in 'active' state by a previous hard crash.

The graceful shutdown path in ``daemon._run`` calls
``SessionManager.force_end`` so any in-progress session is persisted as
``ended`` before the process exits. A SIGKILL / OOM kill / kernel panic
/ power loss skips that — the ``sessions`` row stays at
``status='active'`` with ``end_time=NULL``, and the daily safety-net's
``reduce_all_pending`` query explicitly excludes ``active`` rows
(`session/store.py:list_pending_reduction`). The session's work is then
silently lost: never reduced, never classified, no ``event-*.md`` entry.

This module runs once at daemon startup, before the new
``SessionManager`` takes over. It lists every ``active`` row, infers a
plausible ``end_time`` from the timeline blocks the previous run did
manage to persist, and force-ends each row so the existing safety-net
catch-up picks them up on its next pass.

The inferred end_time is the latest ``timeline_blocks.end_time`` whose
``start_time`` falls within the orphan's plausible lifetime — bounded
above by either the next session row's ``start_time`` (so consecutive
orphans don't pollute each other) or the configured
``session.max_session_hours``, whichever is sooner. If no blocks were
ever persisted (the crash beat the 1-min aggregator), the orphan ends
``start_time + 1 minute`` so the reducer's empty-window code path runs
and marks it ``reduced`` as a no-op rather than leaving it stuck.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..config import Config
from ..logger import get
from ..store import fts
from ..timeline import store as timeline_store
from . import store as session_store

logger = get("openchronicle.session.recovery")

# How long after start_time we treat as the latest plausible end for an
# orphan that has *no* persisted timeline blocks. One minute is enough
# for the reducer to recognize the window as empty (its block-count
# branch handles this case explicitly) and mark the row 'reduced' as a
# no-op, freeing it from the orphan state forever.
_EMPTY_SESSION_FALLBACK = timedelta(minutes=1)


def recover_orphan_sessions(cfg: Config) -> int:
    """Force-end any ``active`` sessions left behind by a hard crash.

    Returns the count of orphans that were force-ended. Idempotent: a
    second call sees no ``active`` rows and is a no-op.
    """
    with fts.cursor() as conn:
        active = session_store.list_active(conn)
        if not active:
            return 0
        max_window = timedelta(hours=cfg.session.max_session_hours)
        for row in active:
            end_time = _infer_end_time(conn, row.start_time, max_window)
            session_store.mark_ended(conn, row.id, end_time)
            logger.info(
                "recovered orphan session %s: start=%s, inferred end=%s",
                row.id,
                row.start_time.isoformat(),
                end_time.isoformat(),
            )
    return len(active)


def _infer_end_time(
    conn: sqlite3.Connection, start_time: datetime, max_window: timedelta
) -> datetime:
    """Best-guess end_time for an orphan: latest block end inside its window.

    The window is ``[start_time, upper_bound)`` where ``upper_bound`` is
    the next session's start (so two orphans don't claim each other's
    blocks) capped by ``start_time + max_session_hours`` (the absolute
    physical session ceiling enforced by SessionManager).
    """
    next_start = session_store.next_session_start_after(conn, start_time)
    ceiling = start_time + max_window
    upper_bound = (
        next_start if next_start is not None and next_start < ceiling else ceiling
    )

    block_end = timeline_store.latest_end_in_window(conn, start_time, upper_bound)
    if block_end is not None and block_end > start_time:
        # Don't extend past the next session's start even if a block's
        # end_time would (shouldn't happen if the aggregator and session
        # cuts are aligned, but be defensive).
        return min(block_end, upper_bound)

    # Clamp the fallback to upper_bound for the same disjoint-sessions
    # invariant: if the next session begins within a minute of this
    # orphan's start (back-to-back hard crashes), an unclamped 1-min
    # fallback would push our end_time past the next session's start
    # and the eventual reducer pass over [start, end) would sweep up
    # blocks that belong to the next session, double-attributing them.
    return min(start_time + _EMPTY_SESSION_FALLBACK, upper_bound)
