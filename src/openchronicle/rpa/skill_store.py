"""Local storage for distilled RPA skills."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .. import paths
from .skill_builder import build_skill_yaml_from_workflow
from .schemas import WorkflowSpec

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REPLACE_ATTEMPTS = 4
_REPLACE_RETRY_SECONDS = 0.05


def skills_root(root: Path | None = None) -> Path:
    base = root or paths.root()
    return base / "data" / "rpa" / "skills"


def skill_dir(skill_name: str, *, root: Path | None = None) -> Path:
    _validate_skill_name(skill_name)
    return skills_root(root) / skill_name


def save_skill(
    skill_name: str,
    workflow: dict[str, Any],
    skill_yaml: str | None = None,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    _validate_safe_name(skill_name, "skill_name")
    spec = WorkflowSpec.model_validate(workflow)
    if spec.id != skill_name:
        raise ValueError(f"workflow id {spec.id!r} must match skill_name {skill_name!r}")
    _validate_safe_name(spec.id, "workflow id")
    workflow_data = spec.model_dump(mode="json", exclude_none=True)
    directory = skill_dir(skill_name, root=root)
    directory.mkdir(parents=True, exist_ok=True)
    yaml_text = skill_yaml if skill_yaml is not None else build_skill_yaml_from_workflow(workflow_data)
    workflow_path = directory / "workflow.json"
    yaml_path = directory / "skill.yaml"
    _atomic_write_text(
        workflow_path,
        json.dumps(workflow_data, ensure_ascii=False, indent=2) + "\n",
    )
    _atomic_write_text(yaml_path, yaml_text)
    return {"workflow": str(workflow_path), "skill_yaml": str(yaml_path)}


def load_workflow(skill_name: str, *, root: Path | None = None) -> dict[str, Any]:
    path = skill_dir(skill_name, root=root) / "workflow.json"
    return json.loads(path.read_bytes())


def load_skill_yaml(skill_name: str, *, root: Path | None = None) -> str:
    path = skill_dir(skill_name, root=root) / "skill.yaml"
    return path.read_text(encoding="utf-8")


def _validate_skill_name(skill_name: str) -> None:
    _validate_safe_name(skill_name, "skill_name")


def _validate_safe_name(name: str, label: str) -> None:
    value = str(name)
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or Path(value).is_absolute()
        or not _SAFE_NAME_RE.fullmatch(value)
    ):
        raise ValueError(f"invalid RPA {label}: {name!r}")


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
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
