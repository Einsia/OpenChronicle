"""Test CLI helper functions (status enrichment, search, version)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from openchronicle import __version__
from openchronicle.cli import (
    _daemon_uptime,
    _health_status,
    _last_capture_info,
)
from openchronicle.store import fts


# ─── _daemon_uptime ────────────────────────────────────────────────────────


def test_daemon_uptime_stopped_when_no_pid() -> None:
    """Returns "stopped" when no PID file exists."""
    assert _daemon_uptime() == "stopped"


# ─── _health_status ────────────────────────────────────────────────────────


def test_health_stopped() -> None:
    label, style = _health_status(None, None)
    assert label == "stopped"
    assert style == "red"


def test_health_running_no_captures() -> None:
    label, style = _health_status(9999, None)
    assert "no captures" in label
    assert style == "yellow"


def test_health_healthy() -> None:
    label, style = _health_status(9999, datetime.now().isoformat())
    assert label == "healthy"
    assert style == "green"


def test_health_stale() -> None:
    from datetime import timedelta

    old = (datetime.now() - timedelta(minutes=10)).isoformat()
    label, style = _health_status(9999, old)
    assert "stale" in label
    assert style == "yellow"


# ─── _last_capture_info ────────────────────────────────────────────────────


def test_last_capture_none_when_dir_missing() -> None:
    """No capture-buffer dir → returns (None, None)."""
    ts, app = _last_capture_info()
    assert ts is None
    assert app is None


def test_last_capture_finds_newest(ac_root: Path) -> None:
    """Write two capture buffer files; the newest filename-sorted is returned."""
    from openchronicle import paths as oc_paths

    buf = oc_paths.capture_buffer_dir()
    buf.mkdir(parents=True, exist_ok=True)
    (buf / "c1.json").write_text(
        json.dumps({
            "timestamp": "2026-04-22T14:00:00+08:00",
            "window_meta": {"app_name": "Cursor"},
        })
    )
    (buf / "c2.json").write_text(
        json.dumps({
            "timestamp": "2026-04-22T14:05:00+08:00",
            "window_meta": {"app_name": "Safari"},
        })
    )

    ts, app = _last_capture_info()
    # c2 sorts after c1
    assert ts == "2026-04-22T14:05:00+08:00", f"got ts={ts!r}"
    assert app == "Safari", f"got app={app!r}"


# ─── version constant ──────────────────────────────────────────────────────


def test_version_is_string() -> None:
    assert isinstance(__version__, str)
    assert "." in __version__


# ─── search integration (via fts) ──────────────────────────────────────────


def _seed_capture(conn, *, id, ts, app, title, value, text, url=""):
    fts.insert_capture(
        conn, id=id, timestamp=ts, app_name=app,
        bundle_id="com.test." + app.lower(),
        window_title=title, focused_role="AXTextArea",
        focused_value=value, visible_text=text, url=url,
    )


def test_search_finds_entries(ac_root: Path) -> None:
    from openchronicle.store import entries as entries_mod

    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="tool-vim.md", description="vim editor", tags=["tool"]
        )
        entries_mod.append_entry(
            conn, name="tool-vim.md",
            content="User uses list comprehensions in Python.",
            tags=["editor"],
        )

        results = fts.search(conn, query="list comprehensions", top_k=10)
    assert len(results) >= 1


def test_search_finds_captures(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed_capture(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
                      app="Cursor", title="main.py", value="def f()",
                      text="working on authentication flow")

        results = fts.search_captures(conn, query="authentication", limit=10)
    assert len(results) == 1
    assert results[0].id == "c1"


def test_search_returns_empty_for_nonsense(ac_root: Path) -> None:
    with fts.cursor() as conn:
        results = fts.search(conn, query="xyznonexistent12345", top_k=10)
    assert len(results) == 0
