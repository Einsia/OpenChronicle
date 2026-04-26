"""Test MCP tool functions directly (bypassing FastMCP wiring)."""

from pathlib import Path

from openchronicle.mcp import captures as captures_mod
from openchronicle.mcp import server as mcp_server
from openchronicle.store import entries as entries_mod
from openchronicle.store import fts
from openchronicle.timeline import store as timeline_store


def test_list_memories(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="user-profile.md", description="identity facts", tags=["identity"]
        )
        entries_mod.create_file(
            conn, name="project-foo.md", description="Foo project", tags=["project"]
        )
        out = mcp_server._list_memories(conn)
    assert out["count"] == 2
    paths = {f["path"] for f in out["files"]}
    assert paths == {"user-profile.md", "project-foo.md"}


def test_read_memory_with_tail(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="topic-x.md", description="Topic X", tags=["topic"]
        )
        for i in range(3):
            entries_mod.append_entry(
                conn, name="topic-x.md", content=f"fact {i}", tags=["x"]
            )
        out = mcp_server._read_memory(conn, path="topic-x.md", tail_n=2)
    assert len(out["entries"]) == 2


def test_search(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="tool-vim.md", description="vim", tags=["tool"]
        )
        entries_mod.append_entry(
            conn, name="tool-vim.md", content="User uses vim for editing.", tags=["editor"]
        )
        out = mcp_server._search(conn, query="vim", top_k=3)
    assert out["results"]
    assert out["results"][0]["path"] == "tool-vim.md"


def test_recent_activity(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(conn, name="event-2026-04-22.md",
                                description="week", tags=["event"])
        entries_mod.append_entry(
            conn, name="event-2026-04-22.md", content="Did a thing.", tags=["x"]
        )
        out = mcp_server._recent_activity(conn, limit=5)
    assert out["count"] >= 1


def test_get_schema() -> None:
    out = mcp_server._get_schema()
    assert "Memory Organization Spec" in out["schema"]


# ─── search_captures + current_context ────────────────────────────────────


def _seed_capture(conn, *, id, ts, app, title, value, text, url=""):
    fts.insert_capture(
        conn, id=id, timestamp=ts, app_name=app,
        bundle_id="com.test." + app.lower(),
        window_title=title, focused_role="AXTextArea",
        focused_value=value, visible_text=text, url=url,
    )


def test_search_captures_returns_bm25_hits_with_snippet(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed_capture(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
                      app="Cursor", title="main.py", value="def foo()",
                      text="def foo(): return 1")
        _seed_capture(conn, id="c2", ts="2026-04-22T14:05:00+08:00",
                      app="Safari", title="docs", value="",
                      text="reading about rate limiter design")

    results = captures_mod.search_captures(query="rate limiter")
    assert len(results) == 1
    r = results[0]
    assert r["file_stem"] == "c2"
    assert r["app_name"] == "Safari"
    assert "[rate]" in r["snippet"] and "[limiter]" in r["snippet"]


def test_search_captures_app_and_time_filters(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed_capture(conn, id="c1", ts="2026-04-22T13:00:00+08:00",
                      app="Cursor", title="a.py", value="", text="login flow stuff")
        _seed_capture(conn, id="c2", ts="2026-04-22T14:00:00+08:00",
                      app="Safari", title="docs", value="", text="login flow stuff")
        _seed_capture(conn, id="c3", ts="2026-04-22T15:00:00+08:00",
                      app="Cursor", title="b.py", value="", text="login flow stuff")

    cursor_only = captures_mod.search_captures(query="login flow", app_name="Cursor")
    assert {h["file_stem"] for h in cursor_only} == {"c1", "c3"}

    bounded = captures_mod.search_captures(
        query="login flow",
        since="2026-04-22T13:30:00+08:00",
        until="2026-04-22T14:30:00+08:00",
    )
    assert {h["file_stem"] for h in bounded} == {"c2"}


def test_current_context_shape(ac_root: Path) -> None:
    """Headlines newest-first, fulltext deduped by (app,window), timeline blocks ordered."""
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    with fts.cursor() as conn:
        # Five captures, two from the same (app, window) pair so dedup should drop one.
        _seed_capture(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
                      app="Cursor", title="main.py", value="x=1", text="A")
        _seed_capture(conn, id="c2", ts="2026-04-22T14:01:00+08:00",
                      app="Safari", title="docs", value="", text="B")
        _seed_capture(conn, id="c3", ts="2026-04-22T14:02:00+08:00",
                      app="Cursor", title="main.py", value="x=2", text="C")
        _seed_capture(conn, id="c4", ts="2026-04-22T14:03:00+08:00",
                      app="Slack", title="#general", value="", text="D")
        _seed_capture(conn, id="c5", ts="2026-04-22T14:04:00+08:00",
                      app="Mail", title="Inbox", value="", text="E")

        # Two timeline blocks
        timeline_store.insert(conn, timeline_store.TimelineBlock(
            start_time=datetime(2026, 4, 22, 14, 0, tzinfo=tz),
            end_time=datetime(2026, 4, 22, 14, 1, tzinfo=tz),
            entries=["[Cursor] editing main.py"], apps_used=["Cursor"], capture_count=2,
        ))
        timeline_store.insert(conn, timeline_store.TimelineBlock(
            start_time=datetime(2026, 4, 22, 14, 1, tzinfo=tz),
            end_time=datetime(2026, 4, 22, 14, 2, tzinfo=tz),
            entries=["[Safari] reading docs"], apps_used=["Safari"], capture_count=1,
        ))

    ctx = captures_mod.current_context(
        headline_limit=5, fulltext_limit=3, timeline_limit=10,
    )
    # Headlines: newest-first, all 5 captures.
    assert [h["file_stem"] for h in ctx["recent_captures_headline"]] == \
        ["c5", "c4", "c3", "c2", "c1"]

    # Fulltext: top 3 distinct (app, window) — c5(Mail), c4(Slack), c3(Cursor/main.py).
    # c1 dedupes against c3 (same Cursor/main.py).
    fulltext_stems = [r["file_stem"] for r in ctx["recent_captures_fulltext"]]
    assert fulltext_stems == ["c5", "c4", "c3"]
    # Fulltext carries the actual visible_text.
    assert ctx["recent_captures_fulltext"][2]["visible_text"] == "C"

    # Timeline blocks present and ordered chronologically.
    assert len(ctx["recent_timeline_blocks"]) == 2
    assert ctx["recent_timeline_blocks"][0]["entries"] == ["[Cursor] editing main.py"]


def test_current_context_app_filter(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed_capture(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
                      app="Cursor", title="a", value="", text="A")
        _seed_capture(conn, id="c2", ts="2026-04-22T14:01:00+08:00",
                      app="Safari", title="b", value="", text="B")

    ctx = captures_mod.current_context(app_filter="Safari", headline_limit=5)
    assert [h["file_stem"] for h in ctx["recent_captures_headline"]] == ["c2"]


# ── S1 editor / terminal fields exposed through MCP tools ───────────────────


def _write_capture_json(ac_root: Path, stem: str, capture: dict) -> None:
    """Write a capture JSON to the buffer directory with the given stem."""
    import json

    from openchronicle import paths

    buf = paths.capture_buffer_dir()
    filepath = buf / f"{stem}.json"
    filepath.write_text(json.dumps(capture, ensure_ascii=False))


def test_read_recent_capture_exposes_editor_fields(ac_root: Path) -> None:
    """Agent calls read_recent_capture → response includes editor_file etc."""
    _write_capture_json(ac_root, "2026-04-26T14-30-00p08-00", {
        "timestamp": "2026-04-26T14:30:00+08:00",
        "schema_version": 2,
        "window_meta": {
            "app_name": "Code",
            "title": "main.py — openchronicle [git:main] - Visual Studio Code",
            "bundle_id": "com.microsoft.VSCode",
        },
        "ax_tree": {},
        "focused_element": {
            "role": "AXTextArea", "title": "editor",
            "value": "def foo(): pass", "is_editable": True,
            "value_length": 16,
        },
        "visible_text": "## Code\n### main.py\n- [AXTextArea] editor — def foo(): pass",
        "url": None,
        "editor_file": "main.py",
        "editor_project": "openchronicle",
        "editor_git_branch": "git:main",
        "terminal_cwd": None,
        "screenshot_stripped": True,
    })

    result = captures_mod.read_recent_capture(
        at="2026-04-26T14:30:00+08:00", app_name="Code",
    )
    assert result is not None, "should find the VS Code capture"
    assert result["editor_file"] == "main.py"
    assert result["editor_project"] == "openchronicle"
    assert result["editor_git_branch"] == "git:main"
    assert result["terminal_cwd"] is None


def test_read_recent_capture_exposes_terminal_cwd(ac_root: Path) -> None:
    """Agent calls read_recent_capture on iTerm2 → response includes terminal_cwd."""
    import os
    home = os.path.expanduser("~")

    _write_capture_json(ac_root, "2026-04-26T14-35-00p08-00", {
        "timestamp": "2026-04-26T14:35:00+08:00",
        "schema_version": 2,
        "window_meta": {
            "app_name": "iTerm2",
            "title": "vim — ~/projects/foo — zsh",
            "bundle_id": "com.googlecode.iterm2",
        },
        "ax_tree": {},
        "focused_element": {
            "role": "AXTextArea", "title": "terminal",
            "value": "$ ls", "is_editable": False,
            "value_length": 4,
        },
        "visible_text": "## iTerm2\n### vim — ~/projects/foo — zsh\n- [AXTextArea] terminal — $ ls",
        "url": None,
        "editor_file": None,
        "editor_project": None,
        "editor_git_branch": None,
        "terminal_cwd": f"{home}/projects/foo",
        "screenshot_stripped": True,
    })

    result = captures_mod.read_recent_capture(
        at="2026-04-26T14:35:00+08:00", app_name="iTerm2",
    )
    assert result is not None, "should find the iTerm2 capture"
    assert result["terminal_cwd"] == f"{home}/projects/foo"
    assert result["editor_file"] is None
    assert result["editor_project"] is None


def test_read_recent_capture_non_editor_has_null_fields(ac_root: Path) -> None:
    """Agent calls read_recent_capture on a non-editor app → fields are None."""
    _write_capture_json(ac_root, "2026-04-26T14-40-00p08-00", {
        "timestamp": "2026-04-26T14:40:00+08:00",
        "schema_version": 2,
        "window_meta": {
            "app_name": "Safari",
            "title": "Example",
            "bundle_id": "com.apple.Safari",
        },
        "ax_tree": {},
        "focused_element": {
            "role": "AXStaticText", "title": "",
            "value": "some content", "is_editable": False,
            "value_length": 12,
        },
        "visible_text": "## Safari\n### Example\n- some content",
        "url": "https://example.com",
        "editor_file": None,
        "editor_project": None,
        "editor_git_branch": None,
        "terminal_cwd": None,
        "screenshot_stripped": True,
    })

    result = captures_mod.read_recent_capture(
        at="2026-04-26T14:40:00+08:00", app_name="Safari",
    )
    assert result is not None, "should find the Safari capture"
    assert result["url"] == "https://example.com"
    assert result["editor_file"] is None
    assert result["editor_project"] is None
    assert result["editor_git_branch"] is None
    assert result["terminal_cwd"] is None
