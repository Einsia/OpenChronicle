"""Workflow loading, validation, and template rendering."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import WorkflowError

_TEMPLATE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
SUPPORTED_SCHEMA_VERSION = "1.0"


def load_workflow(path: str | Path) -> dict[str, Any]:
    workflow_path = Path(path)
    try:
        data = json.loads(workflow_path.read_bytes())
    except OSError as exc:
        raise WorkflowError(f"cannot read workflow {workflow_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid workflow JSON {workflow_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"workflow {workflow_path} must contain a JSON object")
    validate_workflow(data)
    return data


def validate_workflow(workflow: dict[str, Any]) -> None:
    for key in ("schema_version", "id", "provider", "steps"):
        if key not in workflow:
            raise WorkflowError(f"workflow missing required field: {key}")
    if workflow["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise WorkflowError(
            f"unsupported workflow schema_version: {workflow['schema_version']!r}"
        )
    if not isinstance(workflow["id"], str) or not workflow["id"].strip():
        raise WorkflowError("workflow id must be a non-empty string")
    if not isinstance(workflow["provider"], str) or not workflow["provider"].strip():
        raise WorkflowError("workflow provider must be a non-empty string")
    if not isinstance(workflow["steps"], list) or not workflow["steps"]:
        raise WorkflowError("workflow steps must be a non-empty list")
    for index, step in enumerate(workflow["steps"]):
        if not isinstance(step, dict):
            raise WorkflowError(f"workflow step {index} must be an object")
        if not isinstance(step.get("id"), str) or not step["id"].strip():
            raise WorkflowError(f"workflow step {index} missing non-empty id")
        if not isinstance(step.get("action"), str) or not step["action"].strip():
            raise WorkflowError(f"workflow step {step.get('id', index)!r} missing action")
        verify = step.get("verify")
        if verify is not None and not isinstance(verify, dict):
            raise WorkflowError(f"workflow step {step['id']!r} verify must be an object")


def render_workflow(workflow: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    validate_inputs(workflow, inputs)
    rendered = _render(deepcopy(workflow), inputs)
    validate_workflow(rendered)
    return rendered


def validate_inputs(workflow: dict[str, Any], inputs: dict[str, Any]) -> None:
    specs = workflow.get("inputs") or {}
    if not isinstance(specs, dict):
        raise WorkflowError("workflow inputs must be an object")
    for name, spec in specs.items():
        if isinstance(spec, dict) and spec.get("required") and name not in inputs:
            raise WorkflowError(f"missing required workflow input: {name}")


def _render(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in inputs:
                raise WorkflowError(f"missing template input: {key}")
            return str(inputs[key])

        return _TEMPLATE_RE.sub(replace, value)
    if isinstance(value, list):
        return [_render(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, inputs) for key, item in value.items()}
    return value
