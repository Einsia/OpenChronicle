from __future__ import annotations

import json

from openchronicle import cli


def test_clean_captures_removes_matching_index_rows(ac_root) -> None:
    from openchronicle import paths
    from openchronicle.store import fts

    capture = {
        "timestamp": "2026-04-25T22:01:00+08:00",
        "window_meta": {"app_name": "Chrome", "title": "Python docs"},
        "visible_text": "urllib.parse docs",
    }
    capture_path = paths.capture_buffer_dir() / "normal.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    with fts.cursor() as conn:
        fts.insert_capture(
            conn,
            id="normal",
            timestamp=capture["timestamp"],
            app_name="Chrome",
            bundle_id="",
            window_title="Python docs",
            focused_role="",
            focused_value="",
            visible_text="urllib.parse docs",
            url="https://docs.python.org",
        )

    deleted = cli._clean_captures()

    assert deleted == 1
    assert not capture_path.exists()
    with fts.cursor() as conn:
        rows = conn.execute("SELECT id FROM captures").fetchall()
    assert rows == []


def test_rebuild_captures_index_drops_rows_for_missing_files(ac_root, monkeypatch) -> None:
    from openchronicle import paths
    from openchronicle.store import fts

    monkeypatch.setattr(cli, "_init", lambda: None)

    kept_capture = {
        "timestamp": "2026-04-25T22:01:00+08:00",
        "window_meta": {"app_name": "Chrome", "title": "Python docs"},
        "visible_text": "urllib.parse docs",
    }
    kept_path = paths.capture_buffer_dir() / "kept.json"
    kept_path.write_text(json.dumps(kept_capture), encoding="utf-8")
    with fts.cursor() as conn:
        fts.insert_capture(
            conn,
            id="kept",
            timestamp=kept_capture["timestamp"],
            app_name="Chrome",
            bundle_id="",
            window_title="Old title",
            focused_role="",
            focused_value="",
            visible_text="old text",
            url="",
        )
        fts.insert_capture(
            conn,
            id="stale",
            timestamp="2026-04-25T22:00:00+08:00",
            app_name="Chrome",
            bundle_id="",
            window_title="Deleted page",
            focused_role="",
            focused_value="",
            visible_text="deleted text",
            url="",
        )

    cli.rebuild_captures_index()

    with fts.cursor() as conn:
        rows = conn.execute(
            "SELECT id, window_title, visible_text FROM captures ORDER BY id"
        ).fetchall()
    assert [(row["id"], row["window_title"], row["visible_text"]) for row in rows] == [
        ("kept", "Python docs", "urllib.parse docs")
    ]
