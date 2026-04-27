from __future__ import annotations

import pytest

from openchronicle.rpa.recorder import (
    get_current_trace,
    record_action,
    start_recording,
    stop_recording,
)
from openchronicle.rpa.trace_store import load_trace


def test_can_start_recording(ac_root) -> None:
    trace = start_recording(
        "android_adb",
        {"device_id": "emulator-5554", "platform": "android", "name": "Pixel"},
        "search product",
    )

    assert trace.provider == "android_adb"
    assert trace.goal == "search product"
    assert get_current_trace() is not None

    stop_recording()


def test_can_record_tap(ac_root) -> None:
    trace = start_recording("android_adb", {"platform": "android"}, "tap demo")

    updated = record_action(
        "tap",
        {"text": "Taobao", "fallback_xy": [326, 842]},
        {"x": 326, "y": 842},
        {"type": "text_exists", "value": "Search"},
    )

    assert len(updated.steps) == 1
    step = updated.steps[0]
    assert step.step_id == "step_001"
    assert step.action == "tap"
    assert step.source == "manual_recording"
    assert step.risk_level == "L1"
    assert step.before.screenshot.endswith("step_001_before.png")
    assert step.before.ui_tree.endswith("step_001_before.xml")
    assert step.before.ocr_text
    assert step.after.screenshot.endswith("step_001_after.png")
    assert step.after.ui_tree.endswith("step_001_after.xml")
    assert step.after.ocr_text
    assert step.result.status == "success"

    persisted = load_trace(trace.session_id)
    assert len(persisted.steps) == 1
    stop_recording()


def test_can_record_input_text(ac_root) -> None:
    start_recording("android_adb", {"platform": "android"}, "input demo")

    updated = record_action("input_text", {"resource_id": "search_box"}, {"value": "cat food"}, None)

    assert len(updated.steps) == 1
    assert updated.steps[0].action == "input_text"
    assert updated.steps[0].risk_level == "L1"
    assert updated.steps[0].assertion is None
    assert updated.steps[0].params["value"] == "cat food"

    trace = stop_recording()
    loaded = load_trace(trace.session_id)

    assert loaded.steps[0].params["value"] == "cat food"


def test_can_stop_recording(ac_root) -> None:
    start_recording("android_adb", {"platform": "android"}, "stop demo")
    record_action("tap", {"text": "Taobao"}, {"x": 1, "y": 2}, None)

    trace = stop_recording()

    assert len(trace.steps) == 1
    assert get_current_trace() is None


def test_trace_steps_count(ac_root) -> None:
    trace = start_recording("android_adb", {"platform": "android"}, "multi demo")
    record_action("tap", {"text": "Taobao"}, {"x": 1, "y": 2}, None)
    record_action("input_text", {"resource_id": "search_box"}, {"text": "cat food"}, None)

    stopped = stop_recording()
    loaded = load_trace(trace.session_id)

    assert len(stopped.steps) == 2
    assert len(loaded.steps) == 2


def test_record_action_requires_active_recording(ac_root) -> None:
    with pytest.raises(RuntimeError):
        record_action("tap", {}, {}, None)


def test_start_recording_rejects_existing_recording(ac_root) -> None:
    start_recording("android_adb", {"platform": "android"}, "first")

    with pytest.raises(RuntimeError):
        start_recording("android_adb", {"platform": "android"}, "second")

    stop_recording()


def test_record_action_after_stop_raises(ac_root) -> None:
    start_recording("android_adb", {"platform": "android"}, "stopped")
    stop_recording()

    with pytest.raises(RuntimeError):
        record_action("tap", {"text": "Taobao"}, {"x": 1, "y": 2}, None)


def test_source_manual_recording_persists(ac_root) -> None:
    trace = start_recording("android_adb", {"platform": "android"}, "source")
    record_action("tap", {"text": "Taobao"}, {"x": 1, "y": 2}, None)
    stop_recording()

    loaded = load_trace(trace.session_id)

    assert loaded.steps[0].source == "manual_recording"
