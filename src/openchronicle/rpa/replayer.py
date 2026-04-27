"""Deterministic workflow replayer MVP using a mock provider."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assertions import verify_assertion as _verify_assertion
from .replay_report import save_replay_report
from .schemas import ReplayReport, WorkflowSpec, WorkflowStep


class MockReplayProvider:
    """Execute workflow steps deterministically without touching a real device."""

    def __init__(self) -> None:
        self.previous_screen_state = "initial"
        self.executed_steps: list[str] = []

    def run_step(self, step: WorkflowStep) -> dict[str, Any]:
        target = step.target or {}
        params = step.params or {}
        verify = step.verify or {}
        observation = {
            "ok": True,
            "action": step.action,
            "before_screen_state": self.previous_screen_state,
            "screen_state": f"after_{step.id}",
            "ocr_text": [],
            "resource_ids": [],
        }
        self.executed_steps.append(step.id)
        for key in ("text", "content_desc"):
            if target.get(key):
                observation["ocr_text"].append(str(target[key]))
        if target.get("resource_id"):
            observation["resource_ids"].append(str(target["resource_id"]))
        if step.action == "input_text" and params.get("value") is not None:
            observation["ocr_text"].append(str(params["value"]))
        self.previous_screen_state = str(observation["screen_state"])
        return observation


def load_workflow(path: str | Path | dict[str, Any]) -> WorkflowSpec:
    if isinstance(path, dict):
        return WorkflowSpec.model_validate(path)
    workflow_path = Path(path)
    return WorkflowSpec.model_validate(json.loads(workflow_path.read_bytes()))


def run_workflow(
    workflow: str | Path | dict[str, Any] | WorkflowSpec,
    *,
    provider: MockReplayProvider | None = None,
) -> ReplayReport:
    spec = workflow if isinstance(workflow, WorkflowSpec) else load_workflow(workflow)
    replay_provider = provider or MockReplayProvider()
    errors: list[str] = []
    failed_step: str | None = None
    executed = 0
    step_results: list[dict[str, Any]] = []

    for step in spec.steps:
        result = run_step(step, replay_provider)
        executed += 1
        ok, reason = verify_assertion(step.verify, result)
        step_results.append(
            {
                "step_id": step.id,
                "action": step.action,
                "success": ok,
                "error": None if ok else reason,
                "observation": result,
            }
        )
        if not ok:
            failed_step = step.id
            errors.append(reason)
            break

    report = generate_report(
        workflow=spec,
        ok=failed_step is None,
        executed_steps=executed,
        failed_step=failed_step,
        errors=errors,
        step_results=step_results,
    )
    report_path = save_replay_report(report)
    report.trace_path = str(report_path)
    save_replay_report(report)
    return report


def run_step(step: WorkflowStep | dict[str, Any], provider: MockReplayProvider | None = None) -> dict[str, Any]:
    model = step if isinstance(step, WorkflowStep) else WorkflowStep.model_validate(step)
    replay_provider = provider or MockReplayProvider()
    return replay_provider.run_step(model)


def verify_assertion(assertion: dict[str, Any] | None, observation: dict[str, Any]) -> tuple[bool, str]:
    return _verify_assertion(assertion, observation)


def generate_report(
    *,
    workflow: WorkflowSpec,
    ok: bool,
    executed_steps: int,
    failed_step: str | None = None,
    errors: list[str] | None = None,
    step_results: list[dict[str, Any]] | None = None,
) -> ReplayReport:
    error = (errors or [None])[0]
    return ReplayReport(
        session_id=f"replay_{workflow.id}",
        workflow_id=workflow.id,
        run_id=_new_run_id(workflow.id),
        success=ok,
        ok=ok,
        executed_steps=executed_steps,
        failed_step_id=failed_step,
        error=error,
        step_results=step_results or [],
        errors=errors or [],
    )


def _new_run_id(workflow_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{workflow_id}_{stamp}"
