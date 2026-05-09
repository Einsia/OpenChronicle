from __future__ import annotations

from openchronicle.rpa.replay_report import load_replay_report, report_path
from openchronicle.rpa.replayer import (
    MockReplayProvider,
    generate_report,
    load_workflow,
    run_step,
    run_workflow,
    verify_assertion,
)


def _workflow() -> dict:
    return {
        "schema_version": "1.0",
        "id": "search_product",
        "provider": "mock",
        "goal": "Search product",
        "source_trace": "trace_001",
        "created_at": "2026-04-28T10:00:00+08:00",
        "inputs": {},
        "risk_level": "L1",
        "steps": [
            {
                "id": "step_001",
                "action": "tap",
                "target": {"text": "Search"},
                "params": {},
                "risk_level": "L1",
                "verify": {"type": "text_exists", "value": "Search"},
            },
            {
                "id": "step_002",
                "action": "input_text",
                "target": {"resource_id": "search_box"},
                "params": {"value": "cat food"},
                "risk_level": "L1",
                "verify": {"type": "ocr_contains", "value": "cat food"},
            },
        ],
    }


def test_load_workflow_from_dict() -> None:
    workflow = load_workflow(_workflow())

    assert workflow.id == "search_product"
    assert len(workflow.steps) == 2


def test_run_step_with_mock_provider() -> None:
    workflow = load_workflow(_workflow())
    observation = run_step(workflow.steps[0], MockReplayProvider())

    assert "Search" in observation["ocr_text"]


def test_verify_assertion_types() -> None:
    assert verify_assertion({"type": "text_exists", "value": "Search"}, {"ocr_text": ["Search"]})[0]
    assert verify_assertion({"type": "resource_id_exists", "value": "box"}, {"resource_ids": ["box"]})[0]
    assert verify_assertion({"type": "ocr_contains", "value": "cat"}, {"ocr_text": ["cat food"]})[0]
    assert verify_assertion(
        {"type": "screen_changed"},
        {"before_screen_state": "home", "screen_state": "search"},
    )[0]
    assert not verify_assertion(
        {"type": "screen_changed"},
        {"before_screen_state": "home", "screen_state": "home"},
    )[0]


def test_verify_value_is_not_injected_by_mock_provider() -> None:
    workflow = _workflow()
    workflow["steps"][0]["verify"] = {"type": "text_exists", "value": "Injected"}

    observation = run_step(load_workflow(workflow).steps[0], MockReplayProvider())

    assert "Injected" not in observation["ocr_text"]
    assert verify_assertion(workflow["steps"][0]["verify"], observation) == (
        False,
        "text not found: Injected",
    )


def test_run_workflow_success_writes_report(ac_root) -> None:
    report = run_workflow(_workflow())

    assert report.ok is True
    assert report.success is True
    assert report.workflow_id == "search_product"
    assert report.run_id.startswith("search_product_")
    assert report.executed_steps == 2
    assert report.failed_step_id is None
    assert report.error is None
    assert [step["step_id"] for step in report.step_results] == ["step_001", "step_002"]
    assert report_path(report.session_id).exists()
    loaded = load_replay_report(report.session_id)
    assert loaded.success is True
    assert loaded.workflow_id == "search_product"


def test_run_workflow_stops_on_failed_assertion(ac_root) -> None:
    workflow = _workflow()
    workflow["steps"][0]["verify"] = {"type": "text_exists", "value": "Missing"}
    provider = MockReplayProvider()

    report = run_workflow(workflow, provider=provider)

    assert report.ok is False
    assert report.success is False
    assert report.executed_steps == 1
    assert report.failed_step_id == "step_001"
    assert report.error == "text not found: Missing"
    assert report.errors == ["text not found: Missing"]
    assert provider.executed_steps == ["step_001"]
    assert [step["step_id"] for step in report.step_results] == ["step_001"]


def test_screen_changed_success_and_failure() -> None:
    assert verify_assertion(
        {"type": "screen_changed"},
        {"before_screen_state": "before", "screen_state": "after"},
    ) == (True, "")
    assert verify_assertion(
        {"type": "screen_changed"},
        {"before_screen_state": "same", "screen_state": "same"},
    ) == (False, "screen did not change")


def test_generate_report() -> None:
    workflow = load_workflow(_workflow())

    report = generate_report(
        workflow=workflow,
        ok=False,
        executed_steps=1,
        failed_step="step_001",
        errors=["failed"],
    )

    assert report.session_id == "replay_search_product"
    assert report.workflow_id == "search_product"
    assert report.success is False
    assert report.failed_step_id == "step_001"
    assert report.error == "failed"
