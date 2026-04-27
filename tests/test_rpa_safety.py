from __future__ import annotations

import json

import pytest

from openchronicle.rpa.errors import RPASafetyError
from openchronicle.rpa.ocr import EmptyOCRObserver
from openchronicle.rpa.provider import RPAProvider
from openchronicle.rpa.providers.android_adb.adapter import Provider as AndroidADBProvider
from openchronicle.rpa.runner import WorkflowRunner
from openchronicle.rpa.safety import assert_action_allowed, assess_action


class FakeProvider(RPAProvider):
    name = "fake"
    platform = "test"

    def __init__(self) -> None:
        self.actions: list[dict] = []

    def observe(self, options=None):
        return {"ok": True, "provider": self.name, "platform": self.platform, "errors": []}

    def act(self, action):
        self.actions.append(action)
        return {"ok": True, "status": "success", "message": "ok", "action": action}

    def capabilities(self):
        return {"actions": ["type"], "observe": ["state"]}


class FakeTapController:
    def __init__(self) -> None:
        self.taps = []

    def screenshot(self, device_id=None):
        return {"ok": True, "path": "missing.png"}

    def tap(self, x, y, device_id=None):
        self.taps.append((x, y, device_id))
        return {"ok": True, "x": x, "y": y}


@pytest.mark.parametrize(
    "action",
    [
        "adb_shell",
        "raw_shell",
        "shell",
        "exec",
        "install_apk",
        "uninstall_app",
        "factory_reset",
        "rm",
        "delete_file",
    ],
)
def test_safety_blocks_dangerous_actions(action: str) -> None:
    assessment = assess_action({"action": action, "command": "rm -rf /sdcard"})

    assert assessment["allowed"] is False
    assert assessment["risk"] == "high"


@pytest.mark.parametrize(
    "action, category",
    [
        ("delete", "delete"),
        ("payment", "payment"),
        ("order", "order"),
        ("send_message", "send_message"),
        ("login", "login"),
        ("permission_grant", "permission_grant"),
    ],
)
def test_safety_requires_confirmation_for_sensitive_actions(action: str, category: str) -> None:
    assessment = assess_action({"action": action})

    assert assessment["allowed"] is False
    assert assessment["risk"] == "high"
    assert assessment["requires_confirmation"] == [category]


def test_safety_allows_confirmed_sensitive_action() -> None:
    assessment = assert_action_allowed(
        {"action": "tap", "label": "Pay now", "confirmed": True}
    )

    assert assessment["allowed"] is True
    assert assessment["confirmed"] is True


def test_safety_assert_raises() -> None:
    with pytest.raises(RPASafetyError):
        assert_action_allowed({"action": "delete"})


def test_workflow_rejects_unknown_action_and_writes_trace(ac_root) -> None:
    provider = FakeProvider()
    workflow = {
        "schema_version": "1.0",
        "id": "unknown",
        "provider": "fake",
        "steps": [{"id": "unknown", "action": "tap_unknown"}],
    }

    result = WorkflowRunner(provider).run(workflow, task_id="unknown-task")

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert provider.actions == []
    row = _trace_row(ac_root, "unknown-task")
    assert row["action"]["action"] == "tap_unknown"
    assert row["result"]["status"] == "blocked"
    assert row["safety"]["allowed"] is False
    assert "unknown or unsupported RPA action" in row["safety"]["reason"]


def test_safety_refusal_writes_trace_before_provider_act(ac_root) -> None:
    provider = FakeProvider()
    workflow = {
        "schema_version": "1.0",
        "id": "blocked",
        "provider": "fake",
        "steps": [{"id": "shell", "action": "shell", "command": "rm -rf /sdcard"}],
    }

    result = WorkflowRunner(provider).run(workflow, task_id="blocked-task")

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert provider.actions == []
    row = _trace_row(ac_root, "blocked-task")
    assert row["step_id"] == "shell"
    assert row["result"]["status"] == "blocked"
    assert row["safety"]["allowed"] is False
    assert "blocked dangerous RPA action" in row["safety"]["reason"]


def test_android_provider_does_not_expose_arbitrary_adb_shell_entrypoint() -> None:
    provider = AndroidADBProvider(controller=FakeTapController(), ocr=EmptyOCRObserver())
    actions = set(provider.capabilities()["actions"])

    assert actions.isdisjoint({"adb_shell", "raw_shell", "shell", "exec"})

    for action in ("adb_shell", "raw_shell", "shell", "exec"):
        result = provider.act({"action": action, "command": "rm -rf /sdcard"})
        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert "blocked dangerous RPA action" in result["message"]


def test_fallback_area_does_not_bypass_safety() -> None:
    controller = FakeTapController()
    provider = AndroidADBProvider(controller=controller, ocr=EmptyOCRObserver())

    result = provider.act(
        {"action": "tap_text", "text": "Pay now", "fallback_area": [10, 20, 30, 40]}
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["safety"]["requires_confirmation"] == ["payment"]
    assert controller.taps == []


def _trace_row(ac_root, task_id: str) -> dict:
    trace_path = ac_root / "rpa" / "traces" / f"{task_id}.trace.jsonl"
    return json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
