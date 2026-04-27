from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from openchronicle.rpa.schemas import (
    ActionStep,
    DeviceInfo,
    ElementLocator,
    StepAssertion,
    StepResult,
    StepSnapshot,
)
from openchronicle.rpa.trace_store import append_step, create_trace, list_traces, load_trace


def test_create_trace(ac_root) -> None:
    trace = create_trace(
        session_id="phone_demo_20260427_001",
        goal="open taobao and search cat food",
        device=DeviceInfo(
            provider="android_adb",
            device_id="emulator-5554",
            platform="android",
            name="Pixel 6 Pro",
            resolution="1440x3120",
        ),
    )

    path = ac_root / "data" / "rpa" / "traces" / trace.session_id / "trace.json"
    assert path.exists()
    assert trace.schema_version == "1.0"
    assert trace.steps == []
    assert trace.provider == "android_adb"


def test_append_step_and_reload_trace(ac_root) -> None:
    create_trace(
        session_id="phone_demo_20260427_002",
        goal="search product",
        device={"provider": "android_adb", "platform": "android"},
    )
    step = ActionStep(
        step_id="step_001",
        timestamp="2026-04-27T10:24:01.123Z",
        provider="android_adb",
        action="tap",
        target=ElementLocator(
            text="Taobao",
            class_name="android.widget.TextView",
            fallback_area=[300, 800, 360, 880],
            fallback_xy=[326, 842],
        ),
        before=StepSnapshot(
            screenshot="screens/001_before.png",
            ui_tree="ui/001_before.xml",
            ocr_text=["Taobao", "Settings"],
            screen_state="home_screen",
        ),
        after=StepSnapshot(
            screenshot="screens/001_after.png",
            ui_tree="ui/001_after.xml",
            ocr_text=["Search", "Category"],
            screen_state="taobao_home",
        ),
        assertion=StepAssertion(type="text_exists", value="Search"),
        risk_level="L1",
        result=StepResult(ok=True, status="success"),
    )

    append_step("phone_demo_20260427_002", step)
    loaded = load_trace("phone_demo_20260427_002")

    assert loaded.schema_version == "1.0"
    assert len(loaded.steps) == 1
    assert loaded.steps[0].step_id == "step_001"
    assert loaded.steps[0].source == "manual_recording"
    assert loaded.steps[0].target.fallback_area == [300, 800, 360, 880]
    assert loaded.steps[0].target.fallback_xy == [326, 842]
    assert loaded.steps[0].risk_level == "L1"
    assert loaded.steps[0].result.status == "success"
    assert loaded.steps[0].result.error is None
    assert loaded.steps[0].assertion is not None
    assert loaded.steps[0].assertion.type == "text_exists"


def test_list_traces(ac_root) -> None:
    create_trace(session_id="phone_demo_20260427_003", device={"provider": "android_adb"})
    create_trace(session_id="phone_demo_20260427_004", device={"provider": "android_adb"})

    traces = list_traces()

    assert [trace.session_id for trace in traces] == [
        "phone_demo_20260427_004",
        "phone_demo_20260427_003",
    ]


def test_invalid_risk_level_rejected() -> None:
    with pytest.raises(ValidationError):
        ActionStep(
            step_id="step_001",
            provider="android_adb",
            action="tap",
            risk_level="low",
            result=StepResult(ok=True, status="success"),
        )


def test_invalid_session_id_rejected(ac_root) -> None:
    invalid = ["../escape", "/absolute", "C:\\escape", "bad/session", "bad session", ""]
    for session_id in invalid:
        with pytest.raises(ValueError):
            create_trace(session_id=session_id, device={"provider": "android_adb"})


def test_assertion_none_round_trips(ac_root) -> None:
    create_trace(session_id="phone_demo_20260427_005", device={"provider": "android_adb"})
    append_step(
        "phone_demo_20260427_005",
        ActionStep(
            step_id="step_001",
            provider="android_adb",
            action="wait",
            assertion=None,
            result=StepResult(ok=True, status="waiting"),
        ),
    )

    loaded = load_trace("phone_demo_20260427_005")

    assert loaded.steps[0].assertion is None
    assert loaded.steps[0].result.status == "waiting"


def test_list_traces_ignores_damaged_trace(ac_root) -> None:
    create_trace(session_id="phone_demo_20260427_006", device={"provider": "android_adb"})
    damaged = ac_root / "data" / "rpa" / "traces" / "broken" / "trace.json"
    damaged.parent.mkdir(parents=True)
    damaged.write_text("{not-json", encoding="utf-8")

    traces = list_traces()

    assert [trace.session_id for trace in traces] == ["phone_demo_20260427_006"]


def test_trace_can_full_read_write(ac_root) -> None:
    create_trace(
        session_id="phone_demo_20260427_007",
        goal="search product",
        device={
            "provider": "android_adb",
            "device_id": "emulator-5554",
            "platform": "android",
            "name": "Pixel 6 Pro",
            "resolution": "1440x3120",
        },
    )
    append_step(
        "phone_demo_20260427_007",
        {
            "step_id": "step_001",
            "timestamp": "2026-04-27T10:24:01.123Z",
            "provider": "android_adb",
            "action": "tap",
            "target": {"text": "Taobao", "fallback_xy": [326, 842]},
            "before": {"screenshot": "screens/001_before.png", "screen_state": "home_screen"},
            "after": {"screenshot": "screens/001_after.png", "screen_state": "taobao_home"},
            "assertion": {"type": "text_exists", "value": "Search"},
            "risk_level": "L1",
            "result": {"ok": True, "status": "success", "error": None},
        },
    )

    loaded = load_trace("phone_demo_20260427_007")
    path = ac_root / "data" / "rpa" / "traces" / "phone_demo_20260427_007" / "trace.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.device.name == "Pixel 6 Pro"
    assert loaded.steps[0].result.ok is True
    assert raw["steps"][0]["result"] == {"ok": True, "status": "success", "error": None}
    assert raw["steps"][0]["source"] == "manual_recording"
