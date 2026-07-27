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


def test_text_input_preserves_v2_enter_relationship() -> None:
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
            "event_id": "text-event",
            "correlation_id": "interaction",
            "related_signal_id": "enter-association",
            "bundle_id": "com.apple.TextEdit",
            "details": {"reason": "enter"},
        }
    )

    assert captures[0]["event_id"] == "text-event"
    assert captures[0]["correlation_id"] == "interaction"
    assert captures[0]["related_signal_id"] == "enter-association"


def test_user_enter_persists_before_capture_and_bypasses_dedup(ac_root) -> None:
    captures: list[dict] = []

    def capture(trigger: dict) -> None:
        captures.append(trigger)
        trigger["_capture_complete"](
            {"status": "new", "quality_status": "good", "snapshot_ref": "shared.json"}
        )

    store = SignalStore()
    dispatcher = EventDispatcher(
        capture,
        signal_store=store,
        enter_capture_delay_seconds=0.05,
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
    while len(captures) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    dispatcher.shutdown()

    assert len(list((ac_root / "signal-buffer").glob("*.json"))) == 5
    assert len(captures) == 1
    assert set(captures[0]["member_signal_ids"]) == {
        "sig-0",
        "sig-1",
        "sig-2",
        "sig-3",
        "sig-4",
    }
    for index in range(5):
        signal = json.loads(
            (ac_root / "signal-buffer" / f"sig-{index}.json").read_text()
        )
        assert signal["post_capture_status"] == "new"
        assert signal["result_snapshot_ref"] == "shared.json"
        assert signal["capture_attempts"][0]["association_mode"] == "coalesced"


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
            trigger["_capture_complete"](
                {
                    "status": "reused",
                    "quality_status": "good",
                    "snapshot_ref": "before.json",
                }
            )
        else:
            trigger["_capture_complete"](
                {
                    "status": "new",
                    "quality_status": "good",
                    "snapshot_ref": "after.json",
                }
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
    assert attempts == ["initial", "follow_up"]
    assert signal["post_capture_status"] == "new"
    assert signal["result_snapshot_ref"] == "after.json"


def test_high_quality_primary_cancels_followup(ac_root) -> None:
    attempts: list[str] = []

    def capture(trigger: dict) -> None:
        attempts.append(trigger["enter_attempt"])
        trigger["_capture_complete"](
            {"status": "new", "quality_status": "good", "snapshot_ref": "new.json"}
        )

    dispatcher = EventDispatcher(
        capture,
        signal_store=SignalStore(),
        enter_capture_delay_seconds=0,
        enter_followup_delay_seconds=0.02,
    )
    dispatcher.on_event(
        {
            "event_type": "UserEnter",
            "signal_id": "primary-good",
            "bundle_id": "com.apple.TextEdit",
            "key_variant": "return",
        }
    )
    time.sleep(0.08)
    dispatcher.shutdown()

    assert attempts == ["initial"]


def test_shutdown_marks_unstarted_primary_deferred(ac_root) -> None:
    dispatcher = EventDispatcher(
        lambda trigger: None,
        signal_store=SignalStore(),
        enter_capture_delay_seconds=10,
        enter_followup_delay_seconds=None,
    )
    dispatcher.on_event(
        {
            "event_type": "UserEnter",
            "signal_id": "shutdown-pending",
            "bundle_id": "com.apple.TextEdit",
            "key_variant": "return",
        }
    )
    dispatcher.shutdown()

    signal = json.loads(
        (ac_root / "signal-buffer" / "shutdown-pending.json").read_text()
    )
    assert signal["post_capture_status"] == "deferred_shutdown"
    assert signal["capture_attempts"][-1]["status"] == "cancelled_shutdown"


def test_capture_group_allows_only_one_natural_event_attempt(ac_root) -> None:
    attempts: list[str] = []

    def capture(trigger: dict) -> None:
        attempt = trigger["enter_attempt"]
        attempts.append(attempt)
        if attempt == "follow_up":
            outcome = {
                "status": "new",
                "quality_status": "good",
                "snapshot_ref": "after.json",
            }
        else:
            outcome = {
                "status": "reused",
                "quality_status": "good",
                "snapshot_ref": "before.json",
            }
        trigger["_capture_complete"](outcome)

    dispatcher = EventDispatcher(
        capture,
        signal_store=SignalStore(),
        enter_capture_delay_seconds=0,
        enter_followup_delay_seconds=0.08,
        debounce_seconds=10,
    )
    dispatcher.on_event(
        {
            "event_type": "UserEnter",
            "signal_id": "natural-once",
            "pid": 42,
            "bundle_id": "com.apple.TextEdit",
            "key_variant": "return",
        }
    )
    deadline = time.monotonic() + 1
    while attempts != ["initial"] and time.monotonic() < deadline:
        time.sleep(0.005)
    natural = {
        "event_type": "AXValueChanged",
        "pid": 42,
        "bundle_id": "com.apple.TextEdit",
    }
    dispatcher.on_event(natural)
    dispatcher.on_event(natural)
    deadline = time.monotonic() + 1
    while len(attempts) < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    dispatcher.shutdown()

    assert attempts == ["initial", "natural_event", "follow_up"]
