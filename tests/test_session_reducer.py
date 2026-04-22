from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openchronicle import config as config_mod
from openchronicle import paths
from openchronicle.session import store as session_store
from openchronicle.store import fts
from openchronicle.timeline import store as timeline_store
from openchronicle.writer import session_reducer


_TZ = timezone(timedelta(hours=8))
_SID = "sess_test0000"


def test_attach_drill_down_breadcrumb_unit() -> None:
    """Direct unit test of the breadcrumb post-processor."""
    f = session_reducer._attach_drill_down_breadcrumb
    assert f("[14:30-14:35, Cursor] edited main.py").endswith(
        'raw: read_recent_capture(at="14:30", app_name="Cursor")'
    )
    # Spaces in app name preserved verbatim.
    out = f("[09:00-09:05, Code - Insiders] reviewed config.toml")
    assert 'app_name="Code - Insiders"' in out
    # En-dash separator (LLMs sometimes emit it) still parses.
    out2 = f("[18:00–18:30, Google Chrome] reading docs")
    assert 'at="18:00"' in out2 and 'app_name="Google Chrome"' in out2
    # Lines without the canonical prefix pass through untouched.
    plain = "no prefix at all, just text"
    assert f(plain) == plain
    # Idempotent — already-breadcrumbed lines aren't double-appended.
    crumbed = f("[14:30-14:35, Cursor] edited")
    assert f(crumbed) == crumbed


def _seed_blocks(start: datetime) -> list[timeline_store.TimelineBlock]:
    """Create 3 contiguous 5-min blocks with one entry each."""
    bs: list[timeline_store.TimelineBlock] = []
    with fts.cursor() as conn:
        for i in range(3):
            b = timeline_store.TimelineBlock(
                start_time=start + timedelta(minutes=5 * i),
                end_time=start + timedelta(minutes=5 * (i + 1)),
                timezone="+08:00",
                entries=[f"[Cursor] edited file_{i}.py, involving nothing"],
                apps_used=["Cursor"],
                capture_count=6,
            )
            timeline_store.insert(conn, b)
            bs.append(b)
    return bs


def test_reducer_happy_path_writes_event_daily(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 10, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=15)
    _seed_blocks(start)

    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(id=_SID, start_time=start, end_time=end, status="ended"),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv(
        "OPENCHRONICLE_LLM_MOCK_JSON",
        json.dumps(
            {
                "summary": "Worked on a few Python files in Cursor.",
                "sub_tasks": [
                    "[10:00-10:15, Cursor] edited three files, involving file_0.py, file_1.py, file_2.py",
                ],
            }
        ),
    )

    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id=_SID, start_time=start, end_time=end,
    )

    assert result.succeeded is True
    assert result.written is True
    assert result.entry_id
    assert result.path == "event-2026-04-21.md"
    assert len(result.sub_tasks) == 1

    md = (paths.memory_dir() / "event-2026-04-21.md").read_text()
    assert "Session sess_test0000" in md
    assert "[10:00-10:15, Cursor]" in md
    assert "file_0.py" in md
    # Drill-down breadcrumb appended by _attach_drill_down_breadcrumb.
    assert 'raw: read_recent_capture(at="10:00", app_name="Cursor")' in md
    # The result list also carries it.
    assert any('read_recent_capture(at="10:00"' in s for s in result.sub_tasks)

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, _SID)
    assert row is not None
    assert row.status == "reduced"


def test_reducer_no_blocks_marks_reduced_no_write(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 11, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=5)

    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(id="sess_empty", start_time=start, end_time=end, status="ended"),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id="sess_empty", start_time=start, end_time=end,
    )

    assert result.succeeded is True
    assert result.written is False
    assert not (paths.memory_dir() / "event-2026-04-21.md").exists()

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_empty")
    assert row is not None
    assert row.status == "reduced"


def test_reducer_llm_failure_schedules_retry(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 12, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=15)
    _seed_blocks(start)

    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(id="sess_failing", start_time=start, end_time=end, status="ended"),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    # Non-JSON output → json.JSONDecodeError in _call_reducer_llm → None → retry.
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK_JSON", "not json at all")

    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id="sess_failing", start_time=start, end_time=end,
    )

    assert result.succeeded is False
    assert result.written is False

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_failing")
    assert row is not None
    assert row.status == "failed"
    assert row.retry_count == 1
    assert row.next_retry_at is not None


def test_reducer_exhausted_retries_writes_heuristic(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 13, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=15)
    _seed_blocks(start)

    # Row begins with retry_count=4, meaning this is attempt 5/5.
    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_last_chance",
                start_time=start,
                end_time=end,
                status="failed",
                retry_count=4,
            ),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK_JSON", "still garbage")

    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id="sess_last_chance", start_time=start, end_time=end,
    )

    assert result.succeeded is False
    assert result.written is True
    md = (paths.memory_dir() / "event-2026-04-21.md").read_text()
    assert "Cursor" in md
    assert "heuristic" in md  # tag should be present on the heading

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_last_chance")
    assert row is not None
    assert row.status == "reduced"


def test_reducer_idempotent_on_already_reduced(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 14, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=15)
    _seed_blocks(start)

    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_done", start_time=start, end_time=end, status="reduced",
            ),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id="sess_done", start_time=start, end_time=end,
    )
    assert result.succeeded is True
    assert result.written is False
    assert not (paths.memory_dir() / "event-2026-04-21.md").exists()


def test_flush_active_session_writes_partial_entry(
    ac_root: Path, monkeypatch,
) -> None:
    start = datetime(2026, 4, 21, 16, 0, tzinfo=_TZ)
    _seed_blocks(start)  # 3 blocks covering 16:00-16:15
    now = start + timedelta(minutes=15)

    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_flush1", start_time=start, status="active",
            ),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv(
        "OPENCHRONICLE_LLM_MOCK_JSON",
        json.dumps(
            {
                "summary": "partial",
                "sub_tasks": [
                    "[16:00-16:15, Cursor] wip, involving files",
                ],
            }
        ),
    )

    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.flush_active_session(
        cfg, session_id="sess_flush1", session_start=start, now=now,
    )
    assert result is not None
    assert result.is_final is False
    assert result.written is True

    md = (paths.memory_dir() / "event-2026-04-21.md").read_text()
    assert "Session sess_flush1 [flush]" in md

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_flush1")
    assert row is not None
    # Still active — flush must not mark reduced.
    assert row.status == "active"
    assert row.flush_end is not None
    assert row.flush_end >= now


def test_terminal_reduce_after_flush_covers_trailing_window(
    ac_root: Path, monkeypatch,
) -> None:
    start = datetime(2026, 4, 21, 17, 0, tzinfo=_TZ)
    # Two blocks: 17:00-17:05 (flushed) and 17:05-17:10 (trailing).
    with fts.cursor() as conn:
        for i in range(2):
            timeline_store.insert(
                conn,
                timeline_store.TimelineBlock(
                    start_time=start + timedelta(minutes=5 * i),
                    end_time=start + timedelta(minutes=5 * (i + 1)),
                    timezone="+08:00",
                    entries=[f"[Cursor] step_{i}, involving nothing"],
                    apps_used=["Cursor"],
                    capture_count=3,
                ),
            )
        # Pretend a flush already consumed the first block.
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_flush2", start_time=start, status="active",
            ),
        )
        session_store.set_flush_end(
            conn, "sess_flush2", start + timedelta(minutes=5),
        )

    end = start + timedelta(minutes=10)
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv(
        "OPENCHRONICLE_LLM_MOCK_JSON",
        json.dumps(
            {
                "summary": "tail",
                "sub_tasks": [
                    "[17:05-17:10, Cursor] final slice, involving step_1",
                ],
            }
        ),
    )

    cfg = config_mod.load(ac_root / "config.toml")
    result = session_reducer.reduce_session(
        cfg, session_id="sess_flush2", start_time=start, end_time=end,
    )
    assert result.written is True
    assert result.is_final is True

    md = (paths.memory_dir() / "event-2026-04-21.md").read_text()
    # The terminal entry is NOT tagged as flush.
    assert "Session sess_flush2 [flush]" not in md
    assert "Session sess_flush2" in md
    # Trailing window header shows 17:05, not 17:00 — flush_end trimmed the start.
    assert "17:05" in md

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_flush2")
    assert row is not None
    assert row.status == "reduced"


def test_retry_due_picks_up_failed_rows(ac_root: Path, monkeypatch) -> None:
    start = datetime(2026, 4, 21, 15, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=15)
    _seed_blocks(start)

    # Already-due failed row: next_retry_at in the past.
    past = datetime.now().astimezone() - timedelta(minutes=1)
    with fts.cursor() as conn:
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_retry",
                start_time=start,
                end_time=end,
                status="failed",
                retry_count=1,
                next_retry_at=past,
            ),
        )

    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv(
        "OPENCHRONICLE_LLM_MOCK_JSON",
        json.dumps({"summary": "recovered", "sub_tasks": ["[15:00-15:15, Cursor] ok, involving —"]}),
    )

    cfg = config_mod.load(ac_root / "config.toml")
    results = session_reducer.retry_due(cfg)
    assert len(results) == 1
    assert results[0].succeeded is True

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_retry")
    assert row is not None
    assert row.status == "reduced"
