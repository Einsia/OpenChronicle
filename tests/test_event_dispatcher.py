from __future__ import annotations

from openchronicle.capture.event_dispatcher import EventDispatcher


def test_dispatcher_preserves_safe_target_metadata_only() -> None:
    captures: list[dict] = []
    dispatcher = EventDispatcher(
        captures.append,
        min_capture_gap_seconds=0,
        dedup_interval_seconds=0,
        same_window_dedup_seconds=0,
    )
    dispatcher.on_event(
        {
            "event_type": "UserTextInput",
            "bundle_id": "com.example.App",
            "window_title": "Document",
            "details": {
                "reason": "debounce",
                "x": 12,
                "y": 34,
                "element": {
                    "role": "AXTextArea",
                    "subrole": "AXStandardTextArea",
                    "identifier": "editor",
                    "title": "private title",
                    "value": "secret contents",
                },
            },
        }
    )

    assert captures == [
        {
            "event_type": "UserTextInput",
            "bundle_id": "com.example.App",
            "window_title": "Document",
            "details": {
                "reason": "debounce",
                "element": {
                    "role": "AXTextArea",
                    "subrole": "AXStandardTextArea",
                    "identifier": "editor",
                },
            },
        }
    ]
