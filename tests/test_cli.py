"""Test CLI commands and helper functions (status enrichment, search, version).

Every CLI command is tested via Typer's CliRunner to exercise the actual
code path the user would invoke. Helper functions have their own unit tests
for edge cases that are hard to trigger through the runner.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openchronicle import __version__
from openchronicle.cli import (
    _daemon_uptime,
    _health_status,
    _last_capture_info,
    app,
)
from openchronicle.store import fts

runner = CliRunner()

# ═══════════════════════════════════════════════════════════════════
#  CLI command integration tests (caller's perspective)
# ═══════════════════════════════════════════════════════════════════

# ─── version ──────────────────────────────────────────────────────


def test_version_command() -> None:
    """`version` prints the OpenChronicle version string."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"OpenChronicle  v{__version__}" in result.stdout
    assert "Python" in result.stdout
    assert "Platform" in result.stdout


# ─── search ───────────────────────────────────────────────────────


def _seed_entry(conn) -> None:
    from openchronicle.store import entries as entries_mod

    entries_mod.create_file(
        conn, name="tool-vim.md", description="vim editor", tags=["tool"]
    )
    entries_mod.append_entry(
        conn,
        name="tool-vim.md",
        content="User uses list comprehensions in Python.",
        tags=["editor"],
    )


def _seed_capture(conn) -> None:
    fts.insert_capture(
        conn,
        id="c1",
        timestamp="2026-04-22T14:00:00+08:00",
        app_name="Cursor",
        bundle_id="com.test.cursor",
        window_title="main.py",
        focused_role="AXTextArea",
        focused_value="def f()",
        visible_text="working on authentication flow",
        url="",
    )


def test_search_finds_entries(ac_root: Path) -> None:
    """Searching for content that exists in entries returns results."""
    with fts.cursor() as conn:
        _seed_entry(conn)

    result = runner.invoke(app, ["search", "list comprehensions"])
    assert result.exit_code == 0
    assert "list comprehensions" in result.stdout
    assert "entry" in result.stdout or "result" in result.stdout.lower()


def test_search_finds_captures(ac_root: Path) -> None:
    """Searching for content that exists in captures returns results."""
    with fts.cursor() as conn:
        _seed_capture(conn)

    result = runner.invoke(app, ["search", "authentication"])
    assert result.exit_code == 0
    assert "authentication" in result.stdout or "authentic" in result.stdout
    assert "capture" in result.stdout.lower()


def test_search_no_results(ac_root: Path) -> None:
    """Searching for nonsense shows a "No results" message."""
    result = runner.invoke(app, ["search", "xyznonexistent12345"])
    assert result.exit_code == 0
    assert "No results" in result.stdout


def test_search_json_output(ac_root: Path) -> None:
    """--json outputs valid JSON with type/timestamp/text fields."""
    # Ensure config already exists so _init() doesn't emit non-JSON to stdout
    from openchronicle import config as config_mod
    config_mod.write_default_if_missing()

    with fts.cursor() as conn:
        _seed_entry(conn)
        _seed_capture(conn)

    result = runner.invoke(app, ["search", "Python", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    for item in data:
        assert "type" in item
        assert "timestamp" in item
        assert "text" in item


def test_search_limit(ac_root: Path) -> None:
    """--limit caps the number of results returned."""
    with fts.cursor() as conn:
        _seed_entry(conn)

    result = runner.invoke(app, ["search", "Python", "-n", "1"])
    assert result.exit_code == 0
    assert "1 result" in result.stdout or "1" in result.stdout


# ═══════════════════════════════════════════════════════════════════
#  Helper function unit tests (edge cases for pure functions)
# ═══════════════════════════════════════════════════════════════════

# ─── _daemon_uptime ───────────────────────────────────────────────


def test_daemon_uptime_stopped_when_no_pid() -> None:
    """Returns "stopped" when no PID file exists."""
    assert _daemon_uptime() == "stopped"


# ─── _health_status ───────────────────────────────────────────────


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
    old = (datetime.now() - timedelta(minutes=10)).isoformat()
    label, style = _health_status(9999, old)
    assert "stale" in label
    assert style == "yellow"


# ─── _last_capture_info ───────────────────────────────────────────


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
