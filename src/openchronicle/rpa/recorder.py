"""MVP recorder for manual RPA action traces."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .observer import MockObserver
from .schemas import (
    ActionStep,
    ActionTrace,
    DeviceInfo,
    ElementLocator,
    StepAssertion,
    StepResult,
)
from .trace_store import append_step, create_trace, load_trace

_current_session_id: str | None = None
_current_provider: str | None = None
_observer = MockObserver()

_RISK_BY_ACTION = {
    "read_screen": "L0",
    "screenshot": "L0",
    "tap": "L1",
    "swipe": "L1",
    "input_text": "L1",
    "back": "L1",
    "install": "L3",
    "uninstall": "L3",
    "clear_data": "L3",
}


def start_recording(provider: str, device: DeviceInfo | dict, goal: str) -> ActionTrace:
    global _current_provider, _current_session_id

    if _current_session_id is not None:
        raise RuntimeError("RPA recording already active")
    info = _coerce_device(device, provider)
    session_id = _new_session_id()
    trace = create_trace(session_id=session_id, goal=goal, device=info)
    _current_session_id = trace.session_id
    _current_provider = provider
    return trace


def record_action(
    action: str,
    target: ElementLocator | dict | None = None,
    params: dict[str, Any] | None = None,
    assertion: StepAssertion | dict | None = None,
) -> ActionTrace:
    if _current_session_id is None or _current_provider is None:
        raise RuntimeError("no active RPA recording")

    current = load_trace(_current_session_id)
    step_id = f"step_{len(current.steps) + 1:03d}"
    before = _observer.observe(
        session_id=_current_session_id,
        step_id=step_id,
        phase="before",
        action=action,
    )
    after = _observer.observe(
        session_id=_current_session_id,
        step_id=step_id,
        phase="after",
        action=action,
    )
    step = ActionStep(
        step_id=step_id,
        provider=_current_provider,
        source="manual_recording",
        action=action,
        target=_coerce_target(target),
        before=before,
        after=after,
        assertion=_coerce_assertion(assertion),
        risk_level=_risk_level(action),
        result=StepResult(ok=True, status="success", error=None),
        params=params or {},
    )
    return append_step(_current_session_id, step)


def stop_recording() -> ActionTrace:
    global _current_provider, _current_session_id

    if _current_session_id is None:
        raise RuntimeError("no active RPA recording")
    trace = load_trace(_current_session_id)
    _current_session_id = None
    _current_provider = None
    return trace


def get_current_trace() -> ActionTrace | None:
    if _current_session_id is None:
        return None
    return load_trace(_current_session_id)


def _coerce_device(device: DeviceInfo | dict, provider: str) -> DeviceInfo:
    if isinstance(device, DeviceInfo):
        data = device.model_dump()
    else:
        data = dict(device)
    data.setdefault("provider", provider)
    if not data.get("provider"):
        data["provider"] = provider
    return DeviceInfo.model_validate(data)


def _coerce_target(target: ElementLocator | dict | None) -> ElementLocator:
    if isinstance(target, ElementLocator):
        return target
    if isinstance(target, dict):
        return ElementLocator.model_validate(target)
    return ElementLocator()


def _coerce_assertion(assertion: StepAssertion | dict | None) -> StepAssertion | None:
    if assertion is None or isinstance(assertion, StepAssertion):
        return assertion
    return StepAssertion.model_validate(assertion)


def _risk_level(action: str) -> str:
    return _RISK_BY_ACTION.get(action, "L1")


def _new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"recording_{stamp}"
