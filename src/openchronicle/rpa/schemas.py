"""Pydantic schemas for provider-neutral RPA action traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION: Literal["1.0"] = "1.0"
RiskLevel = Literal["L0", "L1", "L2", "L3"]
ActionStatus = Literal["success", "failed", "waiting", "skipped"]


class DeviceInfo(BaseModel):
    provider: str
    device_id: str = ""
    platform: str = ""
    name: str = ""
    resolution: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ElementLocator(BaseModel):
    text: str | None = None
    resource_id: str | None = None
    content_desc: str | None = None
    class_name: str | None = None
    fallback_area: list[int] | None = None
    fallback_xy: list[int] | None = None


class StepSnapshot(BaseModel):
    screenshot: str = ""
    ui_tree: str = ""
    ocr_text: list[str] = Field(default_factory=list)
    screen_state: str = ""
    app: str = ""
    activity: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepAssertion(BaseModel):
    type: str
    value: Any = None
    expected: Any = None
    actual: Any = None
    message: str = ""


class StepResult(BaseModel):
    ok: bool
    status: ActionStatus
    error: str | None = None


class ActionStep(BaseModel):
    step_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    provider: str
    source: str = "manual_recording"
    action: str
    target: ElementLocator = Field(default_factory=ElementLocator)
    before: StepSnapshot = Field(default_factory=StepSnapshot)
    after: StepSnapshot = Field(default_factory=StepSnapshot)
    assertion: StepAssertion | None = None
    risk_level: RiskLevel = "L0"
    result: StepResult
    params: dict[str, Any] = Field(default_factory=dict)


class ActionTrace(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    session_id: str
    goal: str = ""
    provider: str = ""
    device: DeviceInfo
    steps: list[ActionStep] = Field(default_factory=list)
    summary: str = ""
    reusable_skill: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayReport(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    session_id: str
    workflow_id: str = ""
    run_id: str = ""
    success: bool = False
    ok: bool
    executed_steps: int = 0
    failed_step_id: str | None = None
    error: str | None = None
    step_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_path: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())


class WorkflowInput(BaseModel):
    type: str = "string"
    required: bool = True
    default: Any = None


class WorkflowStep(BaseModel):
    id: str
    action: str
    source: str = "manual_recording"
    target: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = "L0"
    result_status: ActionStatus | None = None
    verify: dict[str, Any] | None = None
    value: Any = None


class WorkflowSpec(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str
    provider: str
    goal: str = ""
    source_trace: str
    created_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    inputs: dict[str, WorkflowInput] = Field(default_factory=dict)
    risk_level: RiskLevel = "L0"
    steps: list[WorkflowStep] = Field(default_factory=list)
