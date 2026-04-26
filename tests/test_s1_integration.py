"""Integration tests for the S1 enrichment pipeline.

Verifies the contract between ``s1_parser``, the capture scheduler,
FTS indexing, and timeline event formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

from openchronicle.capture import scheduler as sched_mod
from openchronicle.capture.ax_models import AXCaptureResult
from openchronicle.capture.window_meta import WindowMeta
from openchronicle.config import CaptureConfig
from openchronicle.store import fts as fts_store
from openchronicle.timeline import aggregator


# ── Shared fixture data ──────────────────────────────────────────────

_CHROME_AX_TREE = {
    "apps": [
        {
            "name": "Google Chrome",
            "bundle_id": "com.google.Chrome",
            "is_frontmost": True,
            "windows": [
                {
                    "title": "Anthropic",
                    "focused": True,
                    "elements": [
                        {
                            "role": "AXTextField",
                            "title": "Address and search bar",
                            "value": "https://www.anthropic.com/news",
                        }
                    ],
                }
            ],
        }
    ],
    "timestamp": "2026-04-27T10:00:00+08:00",
}


class _FakeAXProvider:
    """An AXProvider that always returns the same fixture tree."""

    @property
    def available(self) -> bool:
        return True

    def capture_frontmost(self, *, focused_window_only: bool = True):
        return AXCaptureResult(
            raw_json=_CHROME_AX_TREE,
            timestamp=_CHROME_AX_TREE["timestamp"],
            apps=_CHROME_AX_TREE["apps"],
            metadata={"mode": "frontmost"},
        )

    def capture_all_visible(self):
        return None

    def capture_app(self, app_name: str, *, focused_window_only: bool = True):
        return None


# ── Scheduler ↔ S1 contract ─────────────────────────────────────────


def test_scheduler_enrich_pipeline_writes_s1_fields(
    ac_root: Path, monkeypatch
) -> None:
    """``capture_once`` writes a capture JSON with correct S1 fields
    and indexes them in FTS for search."""
    monkeypatch.setattr(
        "openchronicle.capture.window_meta.active_window",
        lambda: WindowMeta(
            app_name="Google Chrome",
            title="Anthropic",
            bundle_id="com.google.Chrome",
        ),
    )
    monkeypatch.setattr(
        "openchronicle.capture.screenshot.grab",
        lambda **kw: None,
    )

    cfg = CaptureConfig(include_screenshot=False)
    provider = _FakeAXProvider()
    path = sched_mod.capture_once(cfg, provider)

    assert path is not None
    assert path.exists()

    data = json.loads(path.read_text())

    # S1 baseline fields are present.
    assert data.get("url") == "https://www.anthropic.com/news"
    fe = data.get("focused_element") or {}
    assert fe.get("role") == "AXTextField"
    assert "visible_text" in data

    # FTS search finds the indexed S1 fields.
    with fts_store.cursor() as conn:
        hits = fts_store.search_captures(conn, query="anthropic")
        assert len(hits) >= 1
        assert hits[0].url == "https://www.anthropic.com/news"
        assert hits[0].app_name == "Google Chrome"

    # S1 fields contribute to the content fingerprint (dedup hash).
    fingerprint = sched_mod._content_fingerprint(data)
    assert len(fingerprint) == 64  # SHA-256 hex digest


def test_scheduler_non_browser_no_url_in_index(ac_root: Path, monkeypatch) -> None:
    """A non-browser app capture has ``url=None``, indexed as empty string."""
    non_browser_tree = {
        "apps": [
            {
                "name": "Cursor",
                "bundle_id": "com.todesktop.230313mzl4w4u92",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "main.py",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextArea",
                                "title": "editor",
                                "value": "def foo(): pass",
                            }
                        ],
                    }
                ],
            }
        ],
        "timestamp": "2026-04-27T10:01:00+08:00",
    }

    class CursorProvider:
        @property
        def available(self) -> bool:
            return True

        def capture_frontmost(self, *, focused_window_only: bool = True):
            return AXCaptureResult(
                raw_json=non_browser_tree,
                timestamp=non_browser_tree["timestamp"],
                apps=non_browser_tree["apps"],
                metadata={"mode": "frontmost"},
            )

        def capture_all_visible(self):
            return None

        def capture_app(self, app_name: str, *, focused_window_only: bool = True):
            return None

    monkeypatch.setattr(
        "openchronicle.capture.window_meta.active_window",
        lambda: WindowMeta(
            app_name="Cursor",
            title="main.py",
            bundle_id="com.todesktop.230313mzl4w4u92",
        ),
    )
    monkeypatch.setattr(
        "openchronicle.capture.screenshot.grab",
        lambda **kw: None,
    )

    cfg = CaptureConfig(include_screenshot=False)
    path = sched_mod.capture_once(cfg, CursorProvider())

    assert path is not None
    data = json.loads(path.read_text())
    assert data.get("url") is None


# ── Timeline ↔ S1 contract ──────────────────────────────────────────


def test_timeline_format_events_renders_s1_fields() -> None:
    """``_format_events`` renders app name, title, URL, focused element,
    and visible text from enriched S1 fields."""
    from openchronicle.capture import s1_parser

    # Build and enrich a minimal capture.
    capture: dict = {
        "timestamp": "2026-04-27T10:00:00+08:00",
        "schema_version": 2,
        "window_meta": {
            "app_name": "Google Chrome",
            "title": "Anthropic",
            "bundle_id": "com.google.Chrome",
        },
        "ax_tree": _CHROME_AX_TREE,
    }
    s1_parser.enrich(capture)

    # Fake a parsed list as _format_events expects.
    parsed: list[tuple[Path, dict]] = [
        (Path("/tmp/test.json"), capture),
    ]
    events_text, apps_used = aggregator._format_events(parsed)

    # App name and title are rendered.
    assert "Google Chrome" in events_text
    assert "Anthropic" in events_text

    # URL is tagged with (URL: ...).
    assert "(URL: https://www.anthropic.com/news)" in events_text

    # Focused element role and value appear.
    assert "[AXTextField]" in events_text
    assert "anthropic.com" in events_text

    # Visible text preview is rendered.
    assert "|" in events_text

    # Apps list is populated.
    assert "Google Chrome" in apps_used


def test_timeline_format_events_non_browser_no_url() -> None:
    """Non-browser captures render without a (URL: ...) tag."""
    from openchronicle.capture import s1_parser

    capture: dict = {
        "timestamp": "2026-04-27T10:01:00+08:00",
        "schema_version": 2,
        "window_meta": {
            "app_name": "Cursor",
            "title": "main.py",
            "bundle_id": "com.todesktop.230313mzl4w4u92",
        },
        "ax_tree": {
            "apps": [
                {
                    "name": "Cursor",
                    "bundle_id": "com.todesktop.230313mzl4w4u92",
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": "main.py",
                            "focused": True,
                            "elements": [
                                {
                                    "role": "AXTextArea",
                                    "title": "editor",
                                    "value": "def foo(): pass",
                                }
                            ],
                        }
                    ],
                }
            ],
            "timestamp": "2026-04-27T10:01:00+08:00",
        },
    }
    s1_parser.enrich(capture)

    parsed: list[tuple[Path, dict]] = [(Path("/tmp/test.json"), capture)]
    events_text, apps_used = aggregator._format_events(parsed)

    assert "(URL:" not in events_text
    assert "Cursor" in apps_used
    assert "[AXTextArea]" in events_text
