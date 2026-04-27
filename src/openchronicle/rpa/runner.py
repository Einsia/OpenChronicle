"""Workflow runner for provider-neutral RPA playback."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .errors import WorkflowError
from .provider import RPAProvider
from .registry import discover_providers
from .safety import action_type, assess_action
from .trace import TraceWriter
from .workflow import load_workflow, render_workflow, validate_workflow


class WorkflowRunner:
    def __init__(self, provider: RPAProvider, *, trace_writer: TraceWriter | None = None) -> None:
        self.provider = provider
        self.trace_writer = trace_writer

    def run(
        self,
        workflow: str | Path | dict[str, Any],
        *,
        inputs: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        data = load_workflow(workflow) if isinstance(workflow, str | Path) else workflow
        validate_workflow(data)
        rendered = render_workflow(data, inputs or {})
        workflow_id = rendered["id"]
        task = task_id or uuid.uuid4().hex
        trace = self.trace_writer or TraceWriter(
            task_id=task,
            workflow_id=workflow_id,
            provider=self.provider.name,
        )
        retry_count = int((rendered.get("failure_policy") or {}).get("retry", 0))
        completed: list[str] = []

        for step in rendered["steps"]:
            step_result = self._run_step(step, retry_count=retry_count, trace=trace)
            if step_result.get("status") != "success":
                status = str(step_result.get("status") or "failed")
                return {
                    "ok": False,
                    "status": status,
                    "message": str(step_result.get("message") or f"workflow failed at step {step['id']}"),
                    "task_id": task,
                    "workflow_id": workflow_id,
                    "provider": self.provider.name,
                    "failed_step": step["id"],
                    "result": step_result,
                    "trace_path": str(trace.trace_path),
                }
            completed.append(step["id"])

        return {
            "ok": True,
            "status": "success",
            "message": "workflow completed",
            "task_id": task,
            "workflow_id": workflow_id,
            "provider": self.provider.name,
            "completed_steps": completed,
            "trace_path": str(trace.trace_path),
        }

    def _run_step(
        self,
        step: dict[str, Any],
        *,
        retry_count: int,
        trace: TraceWriter,
    ) -> dict[str, Any]:
        attempts = retry_count + 1
        last_result: dict[str, Any] = {}
        action = dict(step)
        for attempt in range(1, attempts + 1):
            observation = _observe(self.provider, _observe_options(step, phase="before"))
            safety = _assess_step_action(self.provider, action)
            if not safety["allowed"]:
                result = {
                    "ok": False,
                    "status": "blocked",
                    "message": safety["reason"],
                    "attempt": attempt,
                    "action": action,
                }
                trace.write_step(
                    step_id=step["id"],
                    observation=observation,
                    action=action,
                    result=result,
                    safety=safety,
                )
                return result

            act_result = _normalize_action_result(action, self.provider.act(action))
            verify_options = _observe_options(step, phase="verify")
            verify_observation = _observe(self.provider, verify_options) if verify_options else {}
            verified, message = verify_step(step, verify_observation)
            status = "success" if act_result.get("ok") and verified else "failed"
            trace_observation = _merge_observations(observation, verify_observation)
            if status != "success":
                error_observation = _observe(
                    self.provider,
                    {"screenshot": "keyframe", "ocr": False, "reason": "exception"},
                )
                trace_observation = _merge_observations(trace_observation, error_observation)
            result = {
                "ok": status == "success",
                "status": status,
                "message": message or act_result.get("message", ""),
                "attempt": attempt,
                "provider_result": act_result,
            }
            trace.write_step(
                step_id=step["id"],
                observation=trace_observation,
                action=act_result.get("action") or action,
                result=result,
                safety=safety,
            )
            if status == "success":
                return result
            last_result = result
        return last_result or {"ok": False, "status": "failed", "message": "step did not run"}


def verify_step(step: dict[str, Any], observation: dict[str, Any]) -> tuple[bool, str]:
    verify = step.get("verify") or {}
    if not verify:
        return True, ""
    if "ocr_any" in verify:
        expected = [str(item) for item in verify.get("ocr_any") or []]
        texts = [str(item.get("text", "")) for item in observation.get("ocr") or []]
        haystack = "\n".join(texts)
        if any(item and item in haystack for item in expected):
            return True, ""
        return False, "OCR verification failed"
    return True, ""


def _normalize_observation(provider: RPAProvider, observation: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(observation)
    errors = normalized.get("errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]
    normalized["errors"] = errors
    normalized.setdefault("provider", provider.name)
    normalized.setdefault("platform", getattr(provider, "platform", ""))
    normalized.setdefault("ok", not errors)
    return normalized


def _observe(provider: RPAProvider, options: dict[str, Any]) -> dict[str, Any]:
    return _normalize_observation(provider, provider.observe(options))


def _assess_step_action(provider: RPAProvider, action: dict[str, Any]) -> dict[str, Any]:
    assessment = assess_action(action)
    if not assessment["allowed"]:
        return assessment

    kind = action_type(action)
    capabilities = provider.capabilities()
    supported = capabilities.get("actions") or []
    if kind not in supported:
        return {
            **assessment,
            "allowed": False,
            "risk": "high",
            "reason": f"unknown or unsupported RPA action for provider {provider.name}: {kind}",
        }
    return assessment


def _observe_options(step: dict[str, Any], *, phase: str) -> dict[str, Any]:
    observe = step.get("observe")
    if isinstance(observe, dict):
        phase_options = observe.get(phase)
        if isinstance(phase_options, dict):
            return dict(phase_options)
        if phase == "before":
            return dict(observe)
    if phase == "verify" and "ocr_any" in (step.get("verify") or {}):
        return {"screenshot": "keyframe", "ocr": True}
    return {}


def _merge_observations(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    if not second:
        return first
    merged = dict(first)
    for key, value in second.items():
        if key == "errors":
            merged["errors"] = [*(merged.get("errors") or []), *(value or [])]
        elif value not in (None, "", [], {}):
            merged[key] = value
    merged["ok"] = not merged.get("errors")
    return merged


def _normalize_action_result(action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    ok = bool(normalized.get("ok"))
    normalized["ok"] = ok
    normalized.setdefault("status", "success" if ok else "failed")
    normalized.setdefault("message", str(normalized.get("error") or ""))
    normalized.setdefault("action", action)
    return normalized


def run_workflow_file(
    path: str | Path,
    *,
    provider_name: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow = load_workflow(path)
    name = provider_name or workflow["provider"]
    registry = discover_providers()
    provider = registry.load(name)
    if provider.name != workflow["provider"] and provider_name is None:
        raise WorkflowError(f"provider mismatch: workflow requires {workflow['provider']}")
    return WorkflowRunner(provider).run(workflow, inputs=inputs)
