"""Rule-based trace to workflow/skill distillation for the RPA harness."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .schemas import ActionStep, ActionTrace, RiskLevel, WorkflowSpec

_RISK_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
_SEARCH_HINTS = ("search", "query", "keyword", "搜索", "search_box", "searchbox")


def build_workflow_from_trace(trace: ActionTrace) -> dict[str, Any]:
    """Convert a recorded action trace into a provider-neutral workflow."""
    skill_name = _skill_name(trace.goal or trace.session_id)
    inputs: dict[str, dict[str, Any]] = {}
    steps = []
    used_input_names: set[str] = set()
    generic_input_count = 0

    for index, step in enumerate(trace.steps, start=1):
        workflow_step = _workflow_step(step, input_template=None)
        if step.action == "input_text":
            input_name, generic_input_count = _input_name(
                step,
                used_input_names,
                generic_input_count,
            )
            used_input_names.add(input_name)
            value = _input_value(step)
            template = f"{{{{{input_name}}}}}"
            workflow_step = _workflow_step(step, input_template=template)
            workflow_step["params"]["value"] = template
            workflow_step["value"] = template
            inputs[input_name] = {
                "type": "string",
                "required": True,
                "default": value,
            }
        steps.append(workflow_step)

    workflow = {
        "schema_version": "1.0",
        "id": skill_name,
        "provider": trace.provider or trace.device.provider,
        "goal": trace.goal,
        "source_trace": trace.session_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "inputs": inputs,
        "risk_level": _highest_risk(trace),
        "steps": steps,
    }
    return WorkflowSpec.model_validate(workflow).model_dump(mode="json", exclude_none=True)


def build_skill_yaml_from_workflow(workflow: dict[str, Any]) -> str:
    """Render a small human-readable YAML skill description."""
    spec = WorkflowSpec.model_validate(workflow)
    workflow = spec.model_dump(mode="json", exclude_none=True)
    lines = [
        f"name: {_yaml_scalar(str(workflow['id']))}",
        'version: "1.0"',
        f"provider: {_yaml_scalar(str(workflow.get('provider', '')))}",
        f"risk_level: {_yaml_scalar(str(workflow.get('risk_level', 'L0')))}",
        f"description: {_yaml_scalar(str(workflow.get('goal', '')))}",
        f"source_trace: {_yaml_scalar(str(workflow.get('source_trace', '')))}",
        "inputs:",
    ]
    inputs = workflow.get("inputs") or {}
    if inputs:
        for name, spec in inputs.items():
            lines.append(f"  {name}:")
            lines.append(f"    type: {_yaml_scalar(str(spec.get('type', 'string')))}")
            lines.append(f"    required: {str(bool(spec.get('required'))).lower()}")
            if "default" in spec:
                lines.append(f"    default: {_yaml_scalar(str(spec.get('default', '')))}")
    else:
        lines.append("  {}")
    lines.append("steps:")
    for step in workflow.get("steps") or []:
        lines.append(f"  - id: {_yaml_scalar(str(step.get('id', '')))}")
        lines.append(f"    action: {_yaml_scalar(str(step.get('action', '')))}")
        lines.append(f"    risk_level: {_yaml_scalar(str(step.get('risk_level', 'L0')))}")
        target = step.get("target") or {}
        if target:
            lines.append("    target:")
            for key, value in target.items():
                lines.append(f"      {key}: {_yaml_value(value)}")
        params = step.get("params") or {}
        if params:
            lines.append("    params:")
            for key, value in params.items():
                lines.append(f"      {key}: {_yaml_value(value)}")
        verify = step.get("verify")
        if verify:
            lines.append("    verify:")
            for key, value in verify.items():
                lines.append(f"      {key}: {_yaml_value(value)}")
    return "\n".join(lines) + "\n"


def _workflow_step(step: ActionStep, *, input_template: str | None) -> dict[str, Any]:
    workflow_step: dict[str, Any] = {
        "id": step.step_id,
        "action": step.action,
        "source": step.source,
        "target": _target(step),
        "params": dict(step.params),
        "risk_level": step.risk_level,
        "result_status": step.result.status,
    }
    if step.assertion is not None:
        assertion = step.assertion.model_dump(mode="json", exclude_none=True)
        if input_template is not None and assertion.get("value") == _input_value(step):
            assertion["value"] = input_template
        workflow_step["verify"] = assertion
    return workflow_step


def _target(step: ActionStep) -> dict[str, Any]:
    locator = step.target.model_dump(mode="json", exclude_none=True)
    preferred = {
        key: locator[key]
        for key in ("resource_id", "text", "content_desc", "class_name")
        if key in locator
    }
    if "fallback_area" in locator:
        preferred["fallback_area"] = locator["fallback_area"]
    fallback_xy = locator.get("fallback_xy") or step.params.get("fallback_xy")
    if fallback_xy is None and {"x", "y"} <= set(step.params):
        fallback_xy = [step.params["x"], step.params["y"]]
    if fallback_xy is not None:
        preferred["fallback_xy"] = fallback_xy
    return preferred


def _input_name(
    step: ActionStep,
    used: set[str],
    generic_count: int,
) -> tuple[str, int]:
    if _looks_like_search(step) and "keyword" not in used:
        return "keyword", generic_count
    while True:
        generic_count += 1
        name = f"input_{generic_count}"
        if name not in used:
            return name, generic_count


def _looks_like_search(step: ActionStep) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            step.target.resource_id,
            step.target.text,
            step.target.content_desc,
            step.target.class_name,
        )
    ).lower()
    return any(hint in haystack for hint in _SEARCH_HINTS)


def _input_value(step: ActionStep) -> str:
    value = step.params.get("value", step.params.get("text", ""))
    return str(value)


def _highest_risk(trace: ActionTrace) -> RiskLevel:
    risk: RiskLevel = "L0"
    for step in trace.steps:
        if _RISK_ORDER[step.risk_level] > _RISK_ORDER[risk]:
            risk = step.risk_level
    return risk


def _skill_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value.lower()).strip("_")
    return name or "recorded_skill"


def _yaml_value(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_scalar(str(item)) for item in value) + "]"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return _yaml_scalar(str(value))


def _yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
