"""Replay report persistence for deterministic RPA workflow runs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .schemas import ReplayReport
from .trace_store import trace_dir

_REPLACE_ATTEMPTS = 4
_REPLACE_RETRY_SECONDS = 0.05


def report_path(session_id: str, *, root: Path | None = None) -> Path:
    return trace_dir(session_id, root=root) / "replay_report.json"


def save_replay_report(report: ReplayReport, *, root: Path | None = None) -> Path:
    path = report_path(report.session_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, report.model_dump(mode="json"))
    return path


def load_replay_report(session_id: str, *, root: Path | None = None) -> ReplayReport:
    return ReplayReport.model_validate(json.loads(report_path(session_id, root=root).read_bytes()))


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
