"""Provider manifest loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestError

REQUIRED_FIELDS = {
    "name",
    "type",
    "platform",
    "actions",
    "observe",
    "safety_level",
    "requires_confirmation",
    "memory_output",
}


@dataclass(frozen=True)
class ProviderManifest:
    name: str
    type: str
    platform: list[str]
    actions: list[str]
    observe: list[str]
    safety_level: str
    requires_confirmation: list[str]
    memory_output: list[str]
    path: Path

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path: Path) -> ProviderManifest:
        missing = sorted(REQUIRED_FIELDS - set(data))
        if missing:
            raise ManifestError(f"manifest {path} missing field(s): {', '.join(missing)}")

        for key in ("platform", "actions", "observe", "requires_confirmation", "memory_output"):
            if not isinstance(data[key], list) or not all(isinstance(v, str) for v in data[key]):
                raise ManifestError(f"manifest {path} field {key!r} must be a list of strings")

        for key in ("name", "type", "safety_level"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ManifestError(f"manifest {path} field {key!r} must be a non-empty string")

        return cls(
            name=data["name"],
            type=data["type"],
            platform=list(data["platform"]),
            actions=list(data["actions"]),
            observe=list(data["observe"]),
            safety_level=data["safety_level"],
            requires_confirmation=list(data["requires_confirmation"]),
            memory_output=list(data["memory_output"]),
            path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "platform": self.platform,
            "actions": self.actions,
            "observe": self.observe,
            "safety_level": self.safety_level,
            "requires_confirmation": self.requires_confirmation,
            "memory_output": self.memory_output,
            "path": str(self.path),
        }


def load_manifest(path: str | Path) -> ProviderManifest:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"manifest {manifest_path} must contain a JSON object")
    return ProviderManifest.from_dict(data, path=manifest_path)
