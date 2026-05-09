"""JSONL trace writer for RPA workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths


def rpa_root() -> Path:
    return paths.root() / "rpa"


def traces_dir() -> Path:
    path = rpa_root() / "traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def screens_dir() -> Path:
    path = rpa_root() / "screens"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workflows_dir() -> Path:
    path = rpa_root() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    return datetime.now().astimezone().isoformat()


@dataclass
class TraceWriter:
    task_id: str
    workflow_id: str
    provider: str
    trace_path: Path | None = None

    def __post_init__(self) -> None:
        if self.trace_path is None:
            name = f"{self.task_id}.trace.jsonl"
            self.trace_path = traces_dir() / name
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def write_step(
        self,
        *,
        step_id: str,
        observation: dict[str, Any],
        action: dict[str, Any],
        result: dict[str, Any],
        safety: dict[str, Any],
    ) -> None:
        record = {
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "provider": self.provider,
            "step_id": step_id,
            "timestamp": timestamp(),
            "observation": _compact_observation(observation),
            "action": action,
            "result": result,
            "safety": safety,
        }
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _compact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    ocr_items = observation.get("ocr") or []
    return {
        "app": observation.get("app") or observation.get("current_app") or "",
        "window_title": observation.get("window_title", ""),
        "screen_size": observation.get("screen_size") or [],
        "ocr_texts": [str(item.get("text", "")) for item in ocr_items if item.get("text")],
        "screenshot": observation.get("screenshot", ""),
        "errors": observation.get("errors") or [],
    }
