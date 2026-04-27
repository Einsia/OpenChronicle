from __future__ import annotations

import json

from openchronicle.adb import ADBController, ADBNotFoundError
from openchronicle.adb.client import ADBCommandResult
from openchronicle.adb.memory import ADBMemoryRecorder
from openchronicle.rpa.ocr import EmptyOCRObserver
from openchronicle.rpa.providers.android_adb.adapter import Provider as AndroidADBProvider
from openchronicle.rpa.runner import WorkflowRunner


class MissingADBClient:
    adb_path = "missing-adb"

    def command_for_display(self, args, device_id=None):
        command = [self.adb_path]
        if device_id:
            command.extend(["-s", device_id])
        command.extend(str(a) for a in args)
        return command

    def run(self, args, *, device_id=None, timeout=30.0, binary=False, check=True):
        raise ADBNotFoundError("adb executable not found: 'missing-adb'", args=args)


class FakeTapController:
    def __init__(self) -> None:
        self.taps = []
        self.screenshots = 0
        self.client = FakeClient()

    def screenshot(self, device_id=None):
        self.screenshots += 1
        return {"ok": True, "path": "missing.png"}

    def tap(self, x, y, device_id=None):
        self.taps.append((x, y, device_id))
        return {"ok": True, "x": x, "y": y}

    def current_app(self, device_id=None):
        return {"ok": True, "package": "com.example", "activity": ".Main"}

    def dump_ui(self, device_id=None):
        return {"ok": True, "xml": "<hierarchy />"}


class FakeClient:
    def run(self, args, *, device_id=None, timeout=30.0, binary=False, check=True):
        return ADBCommandResult(args=list(args), returncode=0, stdout="Physical size: 1080x2400", stderr="")


def test_android_provider_reports_missing_adb_without_crashing(ac_root) -> None:
    controller = ADBController(client=MissingADBClient(), recorder=ADBMemoryRecorder())
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    observation = provider.observe()

    assert observation["errors"]
    assert any("adb executable not found" in error for error in observation["errors"])


def test_android_tap_text_uses_fallback_area_when_ocr_empty() -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    result = provider.act(
        {"action": "tap_text", "text": "Search", "fallback_area": [10, 20, 30, 40]}
    )

    assert result["ok"] is True
    assert result["action"]["fallback_used"] is True
    assert result["action"]["resolved_point"] == [20, 30]
    assert controller.taps == [(20, 30, None)]


def test_android_tap_text_without_fallback_fails() -> None:
    provider = AndroidADBProvider(controller=FakeTapController(), ocr=EmptyOCRObserver())

    result = provider.act({"action": "tap_text", "text": "Search"})

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "text not found" in result["message"]


def test_android_tap_text_without_fallback_failure_writes_trace(ac_root) -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())
    workflow = {
        "schema_version": "1.0",
        "id": "tap_text_fail",
        "provider": "android_adb",
        "steps": [{"id": "tap_missing", "action": "tap_text", "text": "Search"}],
    }

    result = WorkflowRunner(provider).run(workflow, task_id="tap-text-fail")

    assert result["ok"] is False
    trace_path = ac_root / "rpa" / "traces" / "tap-text-fail.trace.jsonl"
    row = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["step_id"] == "tap_missing"
    assert row["result"]["status"] == "failed"
    assert row["observation"]["screenshot"]


def test_android_observe_default_does_not_capture_screenshot() -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    observation = provider.observe()

    assert observation["ok"] is True
    assert "screenshot" not in observation
    assert controller.screenshots == 0


def test_android_observe_supports_keyframe_screenshot() -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    observation = provider.observe({"screenshot": "keyframe", "ocr": True})

    assert observation["screenshot"] == "missing.png"
    assert observation["screenshot_mode"] == "keyframe"
    assert controller.screenshots == 1


def test_android_relative_tap_uses_screen_size() -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    result = provider.act({"action": "tap_relative", "x": 500, "y": 250})

    assert result["ok"] is True
    assert controller.taps == [(540, 600, None)]


def test_android_provider_unsupported_action_has_common_result_shape() -> None:
    provider = AndroidADBProvider(controller=FakeTapController(), ocr=EmptyOCRObserver())

    result = provider.act({"action": "not_supported"})

    assert result["ok"] is False
    assert result["status"] == "unsupported"
    assert result["message"]
    assert result["action"] == {"action": "not_supported"}
