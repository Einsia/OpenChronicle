"""captures + captures_fts: insert / search / delete / trigger sync."""

from __future__ import annotations

from pathlib import Path

from openchronicle.store import fts


def _seed(conn, *, id, ts, app, title, value, text, url=""):
    fts.insert_capture(
        conn, id=id, timestamp=ts, app_name=app, bundle_id="com.test." + app.lower(),
        window_title=title, focused_role="AXTextArea", focused_value=value,
        visible_text=text, url=url,
    )


def test_insert_and_keyword_search(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:30:00+08:00",
              app="Cursor", title="main.py", value="def search_captures():",
              text="def search_captures(): pass")
        _seed(conn, id="c2", ts="2026-04-22T14:31:00+08:00",
              app="Safari", title="SQLite FTS5 docs", value="",
              text="SQLite FTS5 is a full-text search extension",
              url="https://example.com/fts5")

        hits = fts.search_captures(conn, query="search_captures")
        assert len(hits) == 1
        assert hits[0].id == "c1"
        assert hits[0].app_name == "Cursor"
        assert "[search_captures]" in hits[0].snippet  # snippet highlighting

        hits2 = fts.search_captures(conn, query="SQLite")
        assert len(hits2) == 1
        assert hits2[0].id == "c2"


def test_app_filter_and_time_window(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Safari", title="article", value="",
              text="machine learning is fun")
        _seed(conn, id="c2", ts="2026-04-22T15:00:00+08:00",
              app="Cursor", title="ml_notes.py", value="# machine learning",
              text="# machine learning notes")
        _seed(conn, id="c3", ts="2026-04-22T16:00:00+08:00",
              app="Safari", title="other", value="",
              text="machine learning beyond basics")

        # app_name filter narrows to Safari only.
        hits = fts.search_captures(conn, query="machine learning", app_name="Safari")
        assert {h.id for h in hits} == {"c1", "c3"}

        # time bounds keep just c1.
        hits = fts.search_captures(
            conn, query="machine learning",
            since="2026-04-22T13:00:00+08:00",
            until="2026-04-22T14:30:00+08:00",
        )
        assert {h.id for h in hits} == {"c1"}


def test_upsert_replaces_row(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Cursor", title="main.py", value="x = 1",
              text="x = 1")
        # Re-insert with the same id but new content. The FTS update trigger
        # should replace the old row so old text isn't searchable anymore.
        _seed(conn, id="c1", ts="2026-04-22T14:01:00+08:00",
              app="Cursor", title="main.py", value="y = 2",
              text="y = 2 redacted")

        old = fts.search_captures(conn, query="x = 1")
        assert len(old) == 0
        new = fts.search_captures(conn, query="redacted")
        assert len(new) == 1 and new[0].id == "c1"


def test_delete_propagates_to_fts(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Cursor", title="main.py", value="z=3", text="findme")
        assert len(fts.search_captures(conn, query="findme")) == 1

        fts.delete_capture(conn, "c1")
        assert len(fts.search_captures(conn, query="findme")) == 0
        assert fts.recent_captures(conn, limit=10) == []


def test_recent_captures_orders_newest_first(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Cursor", title="t1", value="", text="a")
        _seed(conn, id="c2", ts="2026-04-22T15:00:00+08:00",
              app="Safari", title="t2", value="", text="b")
        _seed(conn, id="c3", ts="2026-04-22T16:00:00+08:00",
              app="Cursor", title="t3", value="", text="c")

        rec = fts.recent_captures(conn, limit=10)
        assert [r.id for r in rec] == ["c3", "c2", "c1"]

        # app_name filter
        rec_cursor = fts.recent_captures(conn, limit=10, app_name="Cursor")
        assert [r.id for r in rec_cursor] == ["c3", "c1"]


def test_get_capture_visible_text(ac_root: Path) -> None:
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Cursor", title="t", value="v",
              text="full visible text content here")
        assert fts.get_capture_visible_text(conn, "c1") == "full visible text content here"
        assert fts.get_capture_visible_text(conn, "missing") == ""


def test_search_handles_fts_special_chars(ac_root: Path) -> None:
    """LLM may pass quotes / colons. _safe_fts_query should strip without crashing."""
    with fts.cursor() as conn:
        _seed(conn, id="c1", ts="2026-04-22T14:00:00+08:00",
              app="Cursor", title="t", value="", text="meeting at 18:00 about budget")

        # ":" would break FTS5 if not sanitized. Stripping it splits "18:00"
        # into "18" + "00" — neither necessarily matches the tokenized text,
        # so we only assert no crash.
        fts.search_captures(conn, query="meeting 18:00")
        # Words that DO survive sanitization should still hit.
        hits = fts.search_captures(conn, query='budget "meeting"')
        assert len(hits) == 1
        # Empty / pure-special query is a no-op, not a crash.
        assert fts.search_captures(conn, query='"":*()') == []
