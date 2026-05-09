"""OpenChronicle memory adapter for ADB control events."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .. import paths
from ..store import entries as entries_mod
from ..store import files as files_mod
from ..store import fts


def _truncate(value: str, limit: int = 1200) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... [truncated]"


def _event_daily_name(now: datetime) -> str:
    return f"event-{now.strftime('%Y-%m-%d')}.md"


def _ensure_event_file(conn, name: str, *, day: str) -> None:
    if files_mod.memory_path(name).exists():
        return
    with contextlib.suppress(FileExistsError):
        entries_mod.create_file(
            conn,
            name=name,
            description=(
                f"Activity log for {day}, including OpenChronicle sessions and "
                "Android ADB agent operations."
            ),
            tags=["event", "session", "daily", "adb"],
        )


@dataclass
class ADBMemoryRecorder:
    """Append every ADB tool attempt to the daily OpenChronicle event file."""

    preview_limit: int = 1200
    default_tags: list[str] = field(default_factory=lambda: ["adb", "android"])

    def record(
        self,
        *,
        tool_name: str,
        status: str,
        device_id: str | None,
        command: list[str],
        summary: str,
        params: dict[str, Any] | None = None,
        output_preview: str = "",
        artifact_path: str = "",
        error: str = "",
    ) -> str:
        paths.ensure_dirs()
        now = datetime.now().astimezone()
        name = _event_daily_name(now)
        command_text = " ".join(command)

        body_parts = [
            f"**ADB tool {tool_name}** ({now.strftime('%H:%M')})",
            "",
            f"- Status: {status}",
            f"- Device: {device_id or 'auto'}",
            f"- Command: `{command_text}`",
            f"- Summary: {summary}",
        ]
        if artifact_path:
            body_parts.append(f"- Artifact: `{artifact_path}`")
        if params:
            safe_params = {k: v for k, v in params.items() if v not in (None, "")}
            if safe_params:
                body_parts.append(f"- Params: `{safe_params}`")
        if output_preview:
            body_parts.extend(["", "Output preview:", "```text", _truncate(output_preview, self.preview_limit), "```"])
        if error:
            body_parts.extend(["", "Error:", "```text", _truncate(error, self.preview_limit), "```"])

        tags = [*self.default_tags, f"tool:{tool_name}"]
        with fts.cursor() as conn:
            _ensure_event_file(conn, name, day=now.strftime("%Y-%m-%d"))
            return entries_mod.append_entry(conn, name=name, content="\n".join(body_parts), tags=tags)
