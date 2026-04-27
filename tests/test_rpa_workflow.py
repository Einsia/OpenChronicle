from __future__ import annotations

import json

import pytest

from openchronicle.rpa.errors import WorkflowError
from openchronicle.rpa.provider import RPAProvider
from openchronicle.rpa.runner import WorkflowRunner, verify_step
from openchronicle.rpa.workflow import load_workflow, render_workflow, validate_workflow


class FakeProvider(RPAProvider):
    name = "fake"
    platform = "test"

    def __init__(self) -> None:
        self.actions = []
        self.observe_options = []

    def observe(self, options=None):
        self.observe_options.append(options or {})
        return {"ocr": [{"text": "Search shoes", "box": [0, 0, 10, 10]}]}

    def act(self, action):
        self.actions.append(action)
        return {"ok": True, "action": action}

    def capabilities(self):
        return {"actions": ["tap", "type"], "observe": ["ocr"]}


def test_workflow_parameter_rendering() -> None:
    workflow = {
        "schema_version": "1.0",
        "id": "search",
        "provider": "fake",
        "inputs": {"keyword": {"type": "string", "required": True}},
        "steps": [{"id": "input", "action": "type", "value": "{{keyword}}"}],
    }

    rendered = render_workflow(workflow, {"keyword": "shoes"})

    assert rendered["steps"][0]["value"] == "shoes"


def test_workflow_step_validation_success() -> None:
    validate_workflow(
        {
            "schema_version": "1.0",
            "id": "ok",
            "provider": "fake",
            "steps": [{"id": "wait", "action": "wait", "verify": {"ocr_any": ["Search"]}}],
        }
    )


def test_verify_ocr_any() -> None:
    ok, message = verify_step(
        {"verify": {"ocr_any": ["Search"]}},
        {"ocr": [{"text": "Search shoes"}]},
    )

    assert ok is True
    assert message == ""


def test_runner_executes_workflow_and_writes_trace(ac_root) -> None:
    provider = FakeProvider()
    workflow = {
        "schema_version": "1.0",
        "id": "search",
        "provider": "fake",
        "inputs": {"keyword": {"type": "string", "required": True}},
        "steps": [
            {
                "id": "input",
                "action": "type",
                "value": "{{keyword}}",
                "verify": {"ocr_any": ["Search"]},
            }
        ],
    }

    result = WorkflowRunner(provider).run(workflow, inputs={"keyword": "shoes"}, task_id="task1")

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["message"] == "workflow completed"
    assert provider.actions[0]["value"] == "shoes"
    trace_path = ac_root / "rpa" / "traces" / "task1.trace.jsonl"
    row = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["task_id"] == "task1"
    assert row["step_id"] == "input"
    assert row["observation"]["errors"] == []
    assert row["result"]["ok"] is True
    assert row["result"]["provider_result"]["status"] == "success"
    assert provider.observe_options == [{}, {"screenshot": "keyframe", "ocr": True}]


def test_runner_does_not_request_screenshot_for_simple_steps(ac_root) -> None:
    provider = FakeProvider()
    workflow = {
        "schema_version": "1.0",
        "id": "simple",
        "provider": "fake",
        "steps": [{"id": "tap", "action": "tap", "x": 1, "y": 2}],
    }

    result = WorkflowRunner(provider).run(workflow, task_id="task-simple")

    assert result["ok"] is True
    assert provider.observe_options == [{}]


def test_workflow_missing_schema_version_errors() -> None:
    with pytest.raises(WorkflowError, match="schema_version"):
        validate_workflow(
            {
                "id": "missing_version",
                "provider": "fake",
                "steps": [{"id": "wait", "action": "wait"}],
            }
        )


def test_workflow_unsupported_schema_version_errors() -> None:
    with pytest.raises(WorkflowError, match="unsupported workflow schema_version"):
        validate_workflow(
            {
                "schema_version": "2.0",
                "id": "future_version",
                "provider": "fake",
                "steps": [{"id": "wait", "action": "wait"}],
            }
        )


def test_builtin_example_workflow_loads() -> None:
    workflow = load_workflow("examples/rpa/workflows/android_open_app.workflow.json")

    assert workflow["id"] == "android_open_app"
    assert workflow["schema_version"] == "1.0"
