"""Local JSON storage for RPA action traces."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from .. import paths
from .schemas import ActionStep, ActionTrace, DeviceInfo

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REPLACE_ATTEMPTS = 4
_REPLACE_RETRY_SECONDS = 0.05


def traces_root(root: Path | None = None) -> Path:
    base = root or paths.root()
    return base / "data" / "rpa" / "traces"


def trace_dir(session_id: str, *, root: Path | None = None) -> Path:
    _validate_session_id(session_id)
    return traces_root(root) / session_id


def trace_path(session_id: str, *, root: Path | None = None) -> Path:
    return trace_dir(session_id, root=root) / "trace.json"


def create_trace(
    *,
    session_id: str,
    goal: str = "",
    device: DeviceInfo | dict | None = None,
    root: Path | None = None,
) -> ActionTrace:
    info = _coerce_device(device)
    trace = ActionTrace(session_id=session_id, goal=goal, provider=info.provider, device=info)
    save_trace(trace, root=root)
    return trace


def append_step(
    session_id: str,
    step: ActionStep | dict,
    *,
    root: Path | None = None,
) -> ActionTrace:
    trace = load_trace(session_id, root=root)
    trace.steps.append(_coerce_step(step))
    trace.updated_at = _timestamp()
    save_trace(trace, root=root)
    return trace


def load_trace(session_id: str, *, root: Path | None = None) -> ActionTrace:
    path = trace_path(session_id, root=root)
    data = json.loads(path.read_bytes())
    return ActionTrace.model_validate(data)


def save_trace(trace: ActionTrace | dict, *, root: Path | None = None) -> Path:
    model = trace if isinstance(trace, ActionTrace) else ActionTrace.model_validate(trace)
    model.updated_at = _timestamp()
    path = trace_path(model.session_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json")
    _atomic_write_json(path, payload)
    return path


def list_traces(*, root: Path | None = None) -> list[ActionTrace]:
    base = traces_root(root)
    if not base.exists():
        return []
    traces: list[ActionTrace] = []
    for path in sorted(base.glob("*/trace.json")):
        try:
            traces.append(ActionTrace.model_validate(json.loads(path.read_bytes())))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return sorted(traces, key=lambda trace: trace.updated_at, reverse=True)


def _coerce_device(device: DeviceInfo | dict | None) -> DeviceInfo:
    if isinstance(device, DeviceInfo):
        return device
    if isinstance(device, dict):
        return DeviceInfo.model_validate(device)
    return DeviceInfo(provider="", platform="")


def _coerce_step(step: ActionStep | dict) -> ActionStep:
    if isinstance(step, ActionStep):
        return step
    return ActionStep.model_validate(step)


def _validate_session_id(session_id: str) -> None:
    value = str(session_id)
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or Path(value).is_absolute()
        or not _SESSION_ID_RE.fullmatch(value)
    ):
        raise ValueError(f"invalid trace session_id: {session_id!r}")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat()


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    last_exc: PermissionError | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt == _REPLACE_ATTEMPTS - 1:
                break
            time.sleep(_REPLACE_RETRY_SECONDS)
    try:
        tmp_path.unlink()
    except OSError:
        pass
    if last_exc is not None:
        raise last_exc
