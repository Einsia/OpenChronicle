"""Denylist behavior in EventDispatcher.

The dispatcher must drop events whose bundle id matches a user-configured
fnmatch pattern *before* triggering capture, so excluded apps never reach
the buffer JSON or any LLM call.
"""

from __future__ import annotations

from typing import Any

from openchronicle.capture.event_dispatcher import EventDispatcher


def _capture_recorder() -> tuple[list[dict[str, Any]], EventDispatcher]:
    captured: list[dict[str, Any]] = []

    def fn(trigger: dict[str, Any]) -> None:
        captured.append(trigger)

    return captured, EventDispatcher(
        fn,
        # Tighten gating knobs so test events fire predictably.
        debounce_seconds=0.0,
        min_capture_gap_seconds=0.0,
        dedup_interval_seconds=0.0,
        same_window_dedup_seconds=0.0,
        exclude_bundles=["com.1password.*", "com.apple.MobileSMS"],
    )


def test_excluded_bundle_never_captures() -> None:
    captured, disp = _capture_recorder()
    disp.on_event(
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.1password.1password7",
            "window_title": "All Vaults",
        }
    )
    assert captured == []


def test_excluded_glob_pattern() -> None:
    captured, disp = _capture_recorder()
    disp.on_event(
        {
            "event_type": "UserTextInput",
            "bundle_id": "com.1password.beta",
            "window_title": "Master password",
        }
    )
    assert captured == []


def test_excluded_exact_match() -> None:
    captured, disp = _capture_recorder()
    disp.on_event(
        {
            "event_type": "AXApplicationActivated",
            "bundle_id": "com.apple.MobileSMS",
            "window_title": "Messages",
        }
    )
    assert captured == []


def test_non_excluded_bundle_still_captures() -> None:
    captured, disp = _capture_recorder()
    disp.on_event(
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.apple.Safari",
            "window_title": "Apple",
        }
    )
    assert len(captured) == 1
    assert captured[0]["bundle_id"] == "com.apple.Safari"


def test_empty_denylist_disables_filtering() -> None:
    captured: list[dict[str, Any]] = []

    disp = EventDispatcher(
        lambda t: captured.append(t),
        debounce_seconds=0.0,
        min_capture_gap_seconds=0.0,
        dedup_interval_seconds=0.0,
        same_window_dedup_seconds=0.0,
        exclude_bundles=[],
    )
    disp.on_event(
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.1password.1password7",
            "window_title": "All Vaults",
        }
    )
    assert len(captured) == 1


def test_missing_bundle_id_falls_through() -> None:
    """Empty bundle_id (e.g. transient AX failure) must not be silently dropped."""
    captured, disp = _capture_recorder()
    disp.on_event(
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "",
            "window_title": "Untitled",
        }
    )
    assert len(captured) == 1
