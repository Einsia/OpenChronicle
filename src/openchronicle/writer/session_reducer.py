"""S2 session reducer: closed session → event-YYYY-MM-DD.md entry.

Ported from Einsia-Partner's ``s2_aggregator`` but writes to Markdown
files instead of a session DB table. For a session that just ended:

  1. Query ``timeline_blocks`` in ``[start, end)``.
  2. Render them into a prompt, call the LLM (stage ``reducer``).
  3. Parse ``{summary, sub_tasks}`` and append one entry to
     ``event-<session-start-local-date>.md`` — creating the file if it
     doesn't exist yet.
  4. On LLM success mark the session row ``reduced``; on failure with
     retries remaining mark it ``failed`` + schedule next retry; on
     terminal failure write a heuristic entry and mark ``reduced``.

This module is called from two places:

  * The SessionManager's ``on_session_end`` callback — spawns
    ``reduce_session`` on a daemon thread so the dispatcher doesn't
    block on LLM latency.
  * The daily 23:55 cron / retry tick — calls ``retry_due`` which
    picks up any ``failed`` rows whose ``next_retry_at`` has elapsed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..config import Config
from ..logger import get
from ..prompts import load as load_prompt
from ..session import store as session_store
from ..store import entries as entries_mod
from ..store import files as files_mod
from ..store import fts
from ..timeline import store as timeline_store
from . import llm as llm_mod

# Number of preceding entries from the same event-YYYY-MM-DD.md file to show
# the reducer as context. Lets a new session summary align with / avoid
# duplicating entries that earlier sessions (or earlier flushes of this same
# session) already wrote for the same day.
_PRECEDING_ENTRY_LIMIT = 6

logger = get("openchronicle.writer")

# Matches Einsia. The index into this tuple is the attempt counter
# *before* the retry — a freshly-failed row (retry_count=0) schedules
# at _RETRY_BACKOFF_MINUTES[0] = 5 min.
_RETRY_BACKOFF_MINUTES: tuple[int, ...] = (5, 15, 30, 60, 120)
_MAX_RETRIES: int = len(_RETRY_BACKOFF_MINUTES)


@dataclass
class ReduceResult:
    session_id: str
    succeeded: bool          # LLM produced parseable output
    written: bool            # entry landed in event-YYYY-MM-DD.md
    entry_id: str = ""
    path: str = ""
    sub_tasks: list[str] = field(default_factory=list)
    summary: str = ""
    # Session window this reduction covered.
    start_time: datetime | None = None
    end_time: datetime | None = None
    # False for incremental flushes inside an active session, True for the
    # terminal reduction at session end (or the catch-up path). Drives
    # whether the caller should fire the classifier.
    is_final: bool = True


def reduce_session(
    cfg: Config,
    *,
    session_id: str,
    start_time: datetime,
    end_time: datetime,
) -> ReduceResult:
    """Terminal reduce for a session that has already ended.

    Covers only the trailing window since the last flush (or the full
    session if no flush has happened). Opens its own DB connection so
    this is safe to call from a background thread.
    """
    with fts.cursor() as conn:
        existing = session_store.get_by_id(conn, session_id)
        flush_end = existing.flush_end if existing and existing.flush_end else None
        window_start = flush_end if flush_end and flush_end > start_time else start_time
        return _reduce_window_locked(
            cfg, conn,
            session_id=session_id,
            session_start=start_time,
            session_end=end_time,
            window_start=window_start,
            window_end=end_time,
            is_final=True,
        )


def flush_active_session(
    cfg: Config,
    *,
    session_id: str,
    session_start: datetime,
    now: datetime,
) -> ReduceResult | None:
    """Run an incremental reduce on an active session.

    Reduces any closed timeline blocks in ``[flush_end or session_start, now)``
    and appends a partial entry to the event-daily file. Returns ``None``
    if there are no new blocks to reduce yet (common during short
    sessions) or if the LLM call failed (no retry bookkeeping — the next
    flush covers the missed window).
    """
    with fts.cursor() as conn:
        existing = session_store.get_by_id(conn, session_id)
        if existing is None:
            session_store.insert(
                conn,
                session_store.SessionRow(
                    id=session_id, start_time=session_start, status="active",
                ),
            )
            existing = session_store.get_by_id(conn, session_id)

        if existing is not None and existing.status in ("reduced", "ended"):
            # Session already closed from under us — nothing to flush.
            return None

        flush_end = existing.flush_end if existing and existing.flush_end else None
        window_start = (
            flush_end if flush_end and flush_end > session_start else session_start
        )
        if now <= window_start:
            return None

        result = _reduce_window_locked(
            cfg, conn,
            session_id=session_id,
            session_start=session_start,
            session_end=None,
            window_start=window_start,
            window_end=now,
            is_final=False,
        )
        return result if result.written else None


def _reduce_window_locked(
    cfg: Config,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    session_start: datetime,
    session_end: datetime | None,
    window_start: datetime,
    window_end: datetime,
    is_final: bool,
) -> ReduceResult:
    existing = session_store.get_by_id(conn, session_id)
    if existing is None and is_final and session_end is not None:
        session_store.insert(
            conn,
            session_store.SessionRow(
                id=session_id, start_time=session_start, end_time=session_end,
                status="ended",
            ),
        )
        existing = session_store.get_by_id(conn, session_id)

    if existing is not None and existing.status == "reduced":
        logger.info("session %s already reduced, skipping", session_id)
        return ReduceResult(
            session_id=session_id, succeeded=True, written=False,
            start_time=session_start, end_time=session_end, is_final=is_final,
        )

    blocks = _blocks_for_session(conn, window_start, window_end)
    if not blocks:
        if is_final:
            logger.info(
                "session %s: terminal reduce has 0 blocks in %s → %s, marking reduced (no-op)",
                session_id, window_start.isoformat(), window_end.isoformat(),
            )
            session_store.mark_reduced(conn, session_id)
        else:
            logger.debug(
                "session %s: flush has 0 new blocks since %s",
                session_id, window_start.isoformat(),
            )
        return ReduceResult(
            session_id=session_id, succeeded=True, written=False,
            start_time=session_start, end_time=session_end, is_final=is_final,
        )

    event_daily_name = _event_daily_name(session_start)
    payload = _call_reducer_llm(
        cfg, blocks, window_start, window_end,
        event_daily_name=event_daily_name,
    )

    if payload is None:
        if not is_final:
            # Flush failures don't schedule retries — the next flush tick
            # naturally covers a bigger window.
            logger.warning(
                "session %s: flush reducer LLM failed at window %s → %s, will retry on next tick",
                session_id, window_start.isoformat(), window_end.isoformat(),
            )
            return ReduceResult(
                session_id=session_id, succeeded=False, written=False,
                start_time=session_start, end_time=session_end, is_final=False,
            )
        retry_count = existing.retry_count if existing else 0
        if retry_count + 1 >= _MAX_RETRIES:
            logger.warning(
                "session %s: reducer exhausted %d attempts, writing heuristic fallback",
                session_id, _MAX_RETRIES,
            )
            payload = _heuristic_payload(blocks)
            succeeded = False
        else:
            next_retry_at = datetime.now().astimezone() + timedelta(
                minutes=_RETRY_BACKOFF_MINUTES[retry_count]
            )
            session_store.mark_failed(
                conn, session_id,
                error="reducer LLM call failed or returned unparseable JSON",
                next_retry_at=next_retry_at,
            )
            logger.warning(
                "session %s: reducer failed (retry %d/%d), next attempt at %s",
                session_id, retry_count + 1, _MAX_RETRIES, next_retry_at.isoformat(),
            )
            return ReduceResult(
                session_id=session_id, succeeded=False, written=False,
                start_time=session_start, end_time=session_end, is_final=True,
            )
    else:
        succeeded = True

    summary = str(payload.get("summary") or "").strip()
    sub_tasks = [
        str(t).strip() for t in (payload.get("sub_tasks") or []) if str(t).strip()
    ]
    if not sub_tasks:
        sub_tasks = _heuristic_payload(blocks)["sub_tasks"]
    sub_tasks = [_attach_drill_down_breadcrumb(s) for s in sub_tasks]

    entry_id, path_name = _append_event_entry(
        conn,
        session_id=session_id,
        start_time=window_start,
        end_time=window_end,
        summary=summary,
        sub_tasks=sub_tasks,
        heuristic=not succeeded,
        is_final=is_final,
    )

    last_block_end = blocks[-1].end_time
    new_flush_end = max(window_end, last_block_end)
    session_store.set_flush_end(conn, session_id, new_flush_end)

    if is_final:
        session_store.mark_reduced(conn, session_id)

    logger.info(
        "session %s %s → %s#%s (%d sub_tasks, window %s-%s, llm_ok=%s)",
        session_id,
        "reduced" if is_final else "flushed",
        path_name, entry_id, len(sub_tasks),
        window_start.strftime("%H:%M"),
        window_end.strftime("%H:%M"),
        succeeded,
    )
    return ReduceResult(
        session_id=session_id,
        succeeded=succeeded,
        written=True,
        entry_id=entry_id,
        path=path_name,
        sub_tasks=sub_tasks,
        summary=summary,
        start_time=session_start,
        end_time=session_end,
        is_final=is_final,
    )


def reduce_session_async(
    cfg: Config,
    *,
    session_id: str,
    start_time: datetime,
    end_time: datetime,
    on_done: callable | None = None,  # type: ignore[valid-type]
) -> threading.Thread:
    """Spawn a daemon thread that reduces the session. Fire-and-forget."""
    def _run() -> None:
        try:
            result = reduce_session(
                cfg,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
            )
            if on_done is not None:
                try:
                    on_done(result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "session %s: on_done callback failed: %s", session_id, exc
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "session %s: reducer thread crashed: %s", session_id, exc, exc_info=True
            )

    t = threading.Thread(target=_run, name=f"reduce-{session_id}", daemon=True)
    t.start()
    return t


def retry_due(cfg: Config) -> list[ReduceResult]:
    """Pick up any ``failed`` session rows whose ``next_retry_at`` has elapsed."""
    now = datetime.now().astimezone()
    results: list[ReduceResult] = []
    with fts.cursor() as conn:
        due = session_store.list_due_for_retry(conn, now=now)
    for row in due:
        if row.end_time is None:
            logger.warning("session %s: failed row has no end_time, skipping", row.id)
            continue
        results.append(
            reduce_session(
                cfg,
                session_id=row.id,
                start_time=row.start_time,
                end_time=row.end_time,
            )
        )
    return results


def reduce_all_pending(cfg: Config) -> list[ReduceResult]:
    """Unconditional catch-up: reduce every non-reduced ended/failed session.

    Called from the daily 23:55 safety-net. Covers ``ended`` rows
    whose async reducer thread got killed at shutdown, and ``failed``
    rows regardless of ``next_retry_at``.
    """
    with fts.cursor() as conn:
        rows = session_store.list_pending_reduction(conn)
    out: list[ReduceResult] = []
    for row in rows:
        if row.end_time is None:
            continue
        out.append(
            reduce_session(
                cfg,
                session_id=row.id,
                start_time=row.start_time,
                end_time=row.end_time,
            )
        )
    return out


# ─── Block selection + prompt rendering ─────────────────────────────────────

def _blocks_for_session(
    conn: sqlite3.Connection, start: datetime, end: datetime
) -> list[timeline_store.TimelineBlock]:
    """Return timeline blocks whose window intersects ``[start, end)``."""
    rows = conn.execute(
        """
        SELECT * FROM timeline_blocks
         WHERE end_time > ? AND start_time < ?
         ORDER BY start_time ASC
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    blocks: list[timeline_store.TimelineBlock] = []
    for r in rows:
        blocks.append(
            timeline_store.TimelineBlock(
                id=r["id"],
                start_time=datetime.fromisoformat(r["start_time"]),
                end_time=datetime.fromisoformat(r["end_time"]),
                timezone=r["timezone"] or "",
                entries=json.loads(r["entries"] or "[]"),
                apps_used=json.loads(r["apps_used"] or "[]"),
                capture_count=r["capture_count"] or 0,
                created_at=datetime.fromisoformat(r["created_at"])
                if r["created_at"] else None,
            )
        )
    return blocks


def _format_blocks(blocks: list[timeline_store.TimelineBlock]) -> str:
    out: list[str] = []
    for b in blocks:
        header = f"[{b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')}]"
        entries = list(b.entries) if b.entries else []
        if not entries:
            out.append(f"{header} (no notable activity)")
            continue
        lines = "\n".join(f"  - {e}" for e in entries)
        out.append(f"{header}\n{lines}")
    return "\n".join(out)


def _format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


# Pattern that matches the canonical sub_task prefix the reducer prompt asks
# the LLM to emit: "[HH:MM-HH:MM, <app>] …". The trailing app token is
# greedy-matched up to the closing bracket.
_SUBTASK_PREFIX_RE = re.compile(
    r"^\s*\[\s*(\d{2}):(\d{2})\s*[-–—]\s*(\d{2}):(\d{2})\s*,\s*([^\]]+?)\s*\]"
)


def _attach_drill_down_breadcrumb(sub_task: str) -> str:
    """Append a ``read_recent_capture`` breadcrumb to a sub_task line.

    Parses the canonical ``[HH:MM-HH:MM, <app>]`` prefix and appends
    ``— raw: read_recent_capture(at="HH:MM", app_name="<app>")`` using the
    *start* minute of the range. Lines that don't match the prefix are
    returned unchanged (no breadcrumb noise on heuristic / malformed lines).
    Already-breadcrumbed lines are left alone too.
    """
    if "read_recent_capture(" in sub_task:
        return sub_task
    m = _SUBTASK_PREFIX_RE.match(sub_task)
    if not m:
        return sub_task
    start_h, start_m, _end_h, _end_m, app_raw = m.groups()
    app = app_raw.strip().replace('"', "'")
    breadcrumb = (
        f' — raw: read_recent_capture(at="{start_h}:{start_m}", app_name="{app}")'
    )
    return sub_task.rstrip() + breadcrumb


def _load_preceding_entries(file_name: str, limit: int) -> str:
    """Return the last ``limit`` entries of ``file_name`` as a single string.

    Used to give the reducer context about what's already been written to
    today's event-daily file — both from earlier sessions and from earlier
    flushes of the current session — so the new summary can align with or
    explicitly supersede them instead of silently duplicating.
    """
    path = files_mod.memory_path(file_name)
    if not path.exists():
        return "(no prior entries today)"
    try:
        parsed = files_mod.read_file(path)
    except Exception:  # noqa: BLE001
        return "(prior entries unavailable)"
    if not parsed.entries:
        return "(no prior entries today)"
    tail = parsed.entries[-limit:]
    out: list[str] = []
    for e in tail:
        out.append(f"### [{e.timestamp}] {{id: {e.id}}}")
        body = e.body.strip()
        if body:
            out.append(body)
        out.append("")
    return "\n".join(out).strip()


def _call_reducer_llm(
    cfg: Config,
    blocks: list[timeline_store.TimelineBlock],
    start_time: datetime,
    end_time: datetime,
    *,
    event_daily_name: str,
) -> dict[str, Any] | None:
    preceding_text = _load_preceding_entries(event_daily_name, _PRECEDING_ENTRY_LIMIT)
    prompt = load_prompt("session_reduce.md").format(
        start_time=_format_time(start_time),
        end_time=_format_time(end_time),
        block_count=len(blocks),
        capture_count=sum(b.capture_count for b in blocks),
        blocks_text=_format_blocks(blocks),
        preceding_text=preceding_text,
        event_daily_name=event_daily_name,
    )
    try:
        resp = llm_mod.call_llm(
            cfg, "reducer",
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        text = llm_mod.extract_text(resp).strip()
        if not text:
            return None
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return None
    except json.JSONDecodeError as exc:
        logger.warning("reducer: malformed JSON from LLM: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("reducer: LLM call failed: %s", exc)
        return None


def _heuristic_payload(
    blocks: list[timeline_store.TimelineBlock],
) -> dict[str, Any]:
    """Fallback when LLM attempts are exhausted."""
    apps: list[str] = []
    for b in blocks:
        for a in b.apps_used:
            if a and a not in apps:
                apps.append(a)
    if not blocks:
        return {
            "summary": "",
            "sub_tasks": ["[Unknown] no notable activity, involving —"],
        }
    start_hm = blocks[0].start_time.strftime("%H:%M")
    end_hm = blocks[-1].end_time.strftime("%H:%M")
    sub_tasks = [
        f"[{start_hm}-{end_hm}, {app}] active during the session, involving —"
        for app in apps
    ] or [f"[{start_hm}-{end_hm}, Unknown] no notable activity, involving —"]
    summary = f"Used {', '.join(apps)}." if apps else ""
    return {"summary": summary, "sub_tasks": sub_tasks}


# ─── Entry writing ──────────────────────────────────────────────────────────

def _event_daily_name(start_time: datetime) -> str:
    return f"event-{start_time.strftime('%Y-%m-%d')}.md"


def _ensure_event_daily_file(conn: sqlite3.Connection, name: str, *, day: str) -> None:
    path = files_mod.memory_path(name)
    if path.exists():
        return
    entries_mod.create_file(
        conn,
        name=name,
        description=(
            f"Session-level activity log for {day} — one entry per reduced work "
            "session, each carrying a time-ranged sub-task list produced by the "
            "S2 reducer."
        ),
        tags=["event", "session", "daily"],
    )


def _append_event_entry(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    start_time: datetime,
    end_time: datetime,
    summary: str,
    sub_tasks: list[str],
    heuristic: bool,
    is_final: bool,
) -> tuple[str, str]:
    day = start_time.strftime("%Y-%m-%d")
    name = _event_daily_name(start_time)
    _ensure_event_daily_file(conn, name, day=day)

    marker = "" if is_final else " [flush]"
    header = (
        f"**Session {session_id}{marker}** "
        f"({start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')})"
    )
    body_parts = [header]
    if summary:
        body_parts.append("")
        body_parts.append(summary)
    body_parts.append("")
    body_parts.extend(f"- {s}" for s in sub_tasks)
    body = "\n".join(body_parts)

    tags = ["session", f"sid:{session_id}"]
    if not is_final:
        tags.append("flush")
    if heuristic:
        tags.append("heuristic")

    entry_id = entries_mod.append_entry(
        conn, name=name, content=body, tags=tags,
    )
    return entry_id, name
