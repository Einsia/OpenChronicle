"""Unit tests for the S1 app parser registry."""

from __future__ import annotations

from typing import Any

from openchronicle.capture.app_parsers.base import (
    FocusedElement,
    ParseContext,
    S1Fields,
    S1Patch,
)
from openchronicle.capture.app_parsers import apply_parsers, register


def _capture(app: dict[str, Any]) -> dict[str, Any]:
    return {
        "ax_tree": {"apps": [app]},
        "window_meta": {},
    }


def _ctx(app: dict[str, Any]) -> ParseContext:
    return ParseContext(capture=_capture(app), app=app, window_meta={})


def _fields() -> S1Fields:
    return S1Fields(
        focused_element=FocusedElement(),
        visible_text="baseline text",
        url=None,
    )


# ── Priority ordering ────────────────────────────────────────────────


def test_parsers_run_in_priority_order() -> None:
    """Higher priority (lower number) runs first; later parsers compose."""
    calls: list[str] = []

    class P1:
        name = "p1"
        priority = 10

        def matches(self, ctx, fields):
            calls.append("p1.match")
            return True

        def parse(self, ctx, fields):
            calls.append("p1.parse")
            return S1Patch(visible_text="p1")

    class P2:
        name = "p2"
        priority = 20

        def matches(self, ctx, fields):
            calls.append("p2.match")
            return True

        def parse(self, ctx, fields):
            calls.append("p2.parse")
            return S1Patch(url="p2_url")

    register(P1())
    register(P2())

    fields = _fields()
    ctx = _ctx({"bundle_id": "x"})
    apply_parsers(ctx, fields)

    assert calls == ["p1.match", "p1.parse", "p2.match", "p2.parse"]
    assert fields.visible_text == "p1"
    assert fields.url == "p2_url"


# ── Composition across parsers ───────────────────────────────────────


def test_multiple_parsers_compose_patches() -> None:
    class URLExtractor:
        name = "url"
        priority = 10

        def matches(self, ctx, fields):
            return True

        def parse(self, ctx, fields):
            return S1Patch(url="https://linear.app/issue/LIN-1")

    class LinearMeta:
        name = "linear"
        priority = 20

        def matches(self, ctx, fields):
            return "linear.app" in (fields.url or "")

        def parse(self, ctx, fields):
            return S1Patch(app_context={"linear": {"issue_id": "LIN-1"}})

    register(URLExtractor())
    register(LinearMeta())

    fields = _fields()
    ctx = _ctx({"bundle_id": "com.linear"})
    apply_parsers(ctx, fields)

    assert fields.url == "https://linear.app/issue/LIN-1"
    assert fields.app_context == {"linear": {"issue_id": "LIN-1"}}


# ── Exception resilience ─────────────────────────────────────────────


def test_parser_exception_does_not_break_baseline() -> None:
    class BrokenParser:
        name = "broken"
        priority = 10

        def matches(self, ctx, fields):
            return True

        def parse(self, ctx, fields):
            raise RuntimeError("simulated failure")

    class HealthyParser:
        name = "healthy"
        priority = 20

        def matches(self, ctx, fields):
            return True

        def parse(self, ctx, fields):
            return S1Patch(url="still_works")

    register(BrokenParser())
    register(HealthyParser())

    fields = _fields()
    ctx = _ctx({"bundle_id": "x"})
    apply_parsers(ctx, fields)

    # Baseline fields survive the broken parser.
    assert fields.visible_text == "baseline text"
    assert fields.focused_element.role == ""
    # Healthy parser still runs after the broken one.
    assert fields.url == "still_works"


# ── app_context handling ─────────────────────────────────────────────


def test_empty_app_context_not_written_to_capture() -> None:
    """app_context is only written when non-empty."""
    from openchronicle.capture import s1_parser

    capture = {
        "ax_tree": {
            "apps": [
                {
                    "name": "App",
                    "bundle_id": "test.app",
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": "T",
                            "focused": True,
                            "elements": [
                                {"role": "AXStaticText", "value": "hello"}
                            ],
                        }
                    ],
                }
            ]
        }
    }
    s1_parser.enrich(capture)
    assert "app_context" not in capture


def test_non_empty_app_context_written_to_capture() -> None:
    """app_context appears when a parser provides it."""
    class MetadataParser:
        name = "meta"
        priority = 10

        def matches(self, ctx, fields):
            return True

        def parse(self, ctx, fields):
            return S1Patch(app_context={"key": "value"})

    register(MetadataParser())

    from openchronicle.capture import s1_parser

    capture = {
        "ax_tree": {
            "apps": [
                {
                    "name": "App",
                    "bundle_id": "test.app",
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": "T",
                            "focused": True,
                            "elements": [
                                {"role": "AXStaticText", "value": "hello"}
                            ],
                        }
                    ],
                }
            ]
        }
    }
    s1_parser.enrich(capture)
    assert capture["app_context"] == {"key": "value"}
