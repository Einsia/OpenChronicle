from __future__ import annotations

import json
import time

from openchronicle.capture.event_dispatcher import EventDispatcher
from openchronicle.capture.signal_store import SignalStore


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


def test_text_input_preserves_enter_association_id() -> None:
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
            "signal_id": "enter-association",
            "bundle_id": "com.apple.TextEdit",
            "details": {"reason": "enter"},
        }
    )

    assert captures[0]["signal_id"] == "enter-association"


def test_user_enter_persists_before_capture_and_bypasses_dedup(ac_root) -> None:
    captures: list[dict] = []
    store = SignalStore()
    dispatcher = EventDispatcher(
        captures.append,
        signal_store=store,
        enter_capture_delay_seconds=0,
        enter_followup_delay_seconds=None,
        dedup_interval_seconds=60,
        same_window_dedup_seconds=60,
    )

    for index in range(5):
        dispatcher.on_event(
            {
                "event_type": "UserEnter",
                "signal_id": f"sig-{index}",
                "timestamp": "2026-07-25T12:00:00+08:00",
                "pid": 42,
                "app_name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "window_title": "private",
                "key_variant": "return",
                "modifiers": [],
                "input_target": {"role": "AXTextArea", "value": "secret"},
            }
        )

    deadline = time.monotonic() + 1
    while len(captures) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    dispatcher.shutdown()

    assert len(list((ac_root / "signal-buffer").glob("*.json"))) == 5
    assert len(captures) == 5
    assert {capture["signal_id"] for capture in captures} == {
        "sig-0",
        "sig-1",
        "sig-2",
        "sig-3",
        "sig-4",
    }


def test_duplicate_signal_id_does_not_request_second_capture(ac_root) -> None:
    captures: list[dict] = []
    dispatcher = EventDispatcher(
        captures.append,
        signal_store=SignalStore(),
        enter_capture_delay_seconds=0,
        enter_followup_delay_seconds=None,
    )
    event = {
        "event_type": "UserEnter",
        "signal_id": "same-id",
        "timestamp": "2026-07-25T12:00:00+08:00",
        "bundle_id": "com.apple.TextEdit",
        "key_variant": "return",
    }

    dispatcher.on_event(event)
    dispatcher.on_event(event)
    deadline = time.monotonic() + 1
    while len(captures) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    dispatcher.shutdown()

    assert len(captures) == 1


def test_enter_followup_can_upgrade_late_snapshot(ac_root) -> None:
    store = SignalStore()
    attempts: list[str] = []

    def capture(trigger: dict) -> None:
        attempt = trigger["enter_attempt"]
        attempts.append(attempt)
        if attempt == "initial":
            store.update_snapshot(
                trigger["signal_id"], status="reused", snapshot_ref="before.json"
            )
        else:
            store.update_snapshot(
                trigger["signal_id"], status="captured", snapshot_ref="after.json"
            )

    dispatcher = EventDispatcher(
        capture,
        signal_store=store,
        enter_capture_delay_seconds=0,
        enter_followup_delay_seconds=0.05,
    )
    dispatcher.on_event(
        {
            "event_type": "UserEnter",
            "signal_id": "late-update",
            "timestamp": "2026-07-25T12:00:00+08:00",
            "bundle_id": "com.google.Chrome",
            "key_variant": "return",
        }
    )
    deadline = time.monotonic() + 1
    while len(attempts) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    dispatcher.shutdown()

    signal = json.loads((ac_root / "signal-buffer" / "late-update.json").read_text())
    assert attempts == ["initial", "followup"]
    assert signal["snapshot_status"] == "captured"
    assert signal["snapshot_ref"] == "after.json"
