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
