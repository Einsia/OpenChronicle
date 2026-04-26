"""High-level Android ADB operations exposed through MCP."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths
from . import safety
from .client import ADBClient, ADBError
from .memory import ADBMemoryRecorder

_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_ACTIVITY_RE = re.compile(r"^[A-Za-z0-9_.$/]+$")
_COMPONENT_RE = re.compile(r"(?P<package>[A-Za-z0-9_.$]+)/(?P<activity>[A-Za-z0-9_.$]+)")


def _parse_devices(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        qualifiers: dict[str, str] = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                qualifiers[key] = value
        devices.append(
            {
                "serial": parts[0],
                "state": parts[1],
                "qualifiers": qualifiers,
                "raw": line,
            }
        )
    return devices


def _artifact_dir(name: str) -> Path:
    path = paths.root() / "adb" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_non_negative_int(name: str, value: int) -> int:
    integer = int(value)
    if integer < 0:
        raise safety.ADBSafetyError(f"{name} must be non-negative")
    if integer > 10000:
        raise safety.ADBSafetyError(f"{name} is implausibly large: {integer}")
    return integer


def _bounded_lines(lines: int) -> int:
    value = int(lines)
    if value < 1:
        return 1
    return min(value, 2000)


def _command_with_redacted_tail(command: list[str]) -> list[str]:
    if not command:
        return command
    return [*command[:-1], "<redacted>"]


def _parse_component(text: str) -> dict[str, str]:
    match = _COMPONENT_RE.search(text)
    if not match:
        return {"package": "", "activity": "", "raw": text.strip()}
    return {
        "package": match.group("package"),
        "activity": match.group("activity"),
        "raw": text.strip(),
    }


@dataclass
class ADBController:
    """ADB operation facade that always records into OpenChronicle memory."""

    client: ADBClient = field(default_factory=ADBClient)
    recorder: ADBMemoryRecorder = field(default_factory=ADBMemoryRecorder)

    def _record_success(
        self,
        *,
        tool_name: str,
        device_id: str | None,
        command: list[str],
        summary: str,
        params: dict[str, Any] | None = None,
        output_preview: str = "",
        artifact_path: str = "",
    ) -> str:
        return self.recorder.record(
            tool_name=tool_name,
            status="ok",
            device_id=device_id,
            command=command,
            summary=summary,
            params=params,
            output_preview=output_preview,
            artifact_path=artifact_path,
        )

    def _record_failure(
        self,
        *,
        tool_name: str,
        status: str,
        device_id: str | None,
        command: list[str],
        summary: str,
        params: dict[str, Any] | None = None,
        error: str = "",
    ) -> str:
        return self.recorder.record(
            tool_name=tool_name,
            status=status,
            device_id=device_id,
            command=command,
            summary=summary,
            params=params,
            error=error,
        )

    def _adb_error_payload(
        self,
        *,
        tool_name: str,
        device_id: str | None,
        command: list[str],
        params: dict[str, Any] | None,
        exc: ADBError,
    ) -> dict[str, Any]:
        entry_id = self._record_failure(
            tool_name=tool_name,
            status="error",
            device_id=device_id,
            command=command,
            summary=f"{tool_name} failed",
            params=params,
            error=str(exc),
        )
        return {
            "ok": False,
            "tool": tool_name,
            "error": str(exc),
            "returncode": exc.returncode,
            "memory_entry_id": entry_id,
        }

    def _blocked_payload(
        self,
        *,
        tool_name: str,
        device_id: str | None,
        command: list[str],
        params: dict[str, Any] | None,
        exc: safety.ADBSafetyError,
    ) -> dict[str, Any]:
        entry_id = self._record_failure(
            tool_name=tool_name,
            status="blocked",
            device_id=device_id,
            command=command,
            summary=f"{tool_name} blocked by safety policy",
            params=params,
            error=str(exc),
        )
        return {
            "ok": False,
            "tool": tool_name,
            "blocked": True,
            "error": str(exc),
            "memory_entry_id": entry_id,
        }

    def list_devices(self) -> dict[str, Any]:
        tool = "adb_list_devices"
        command = ["devices", "-l"]
        try:
            result = self.client.run(command, timeout=15)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=None, command=command, params=None, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=None, command=command, params=None, exc=exc
            )
        devices = _parse_devices(result.stdout_text)
        entry_id = self._record_success(
            tool_name=tool,
            device_id=None,
            command=self.client.command_for_display(command),
            summary=f"Listed {len(devices)} Android device(s).",
            output_preview=result.stdout_text,
        )
        return {"ok": True, "tool": tool, "count": len(devices), "devices": devices, "memory_entry_id": entry_id}

    def screenshot(self, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_screenshot"
        command = ["exec-out", "screencap", "-p"]
        params = {"device_id": device_id}
        display = self.client.command_for_display(command, device_id)
        try:
            result = self.client.run(command, device_id=device_id, timeout=20, binary=True)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )

        now = datetime.now().astimezone()
        out_path = _artifact_dir("screenshots") / f"{now.strftime('%Y%m%d-%H%M%S-%f')}.png"
        out_path.write_bytes(result.stdout_bytes)
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Captured Android screenshot ({len(result.stdout_bytes)} bytes).",
            params=params,
            artifact_path=str(out_path),
        )
        return {
            "ok": True,
            "tool": tool,
            "path": str(out_path),
            "bytes": len(result.stdout_bytes),
            "memory_entry_id": entry_id,
        }

    def dump_ui(self, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_dump_ui"
        dump_path = "/sdcard/window.xml"
        command = ["shell", "uiautomator", "dump", dump_path]
        cat_command = ["exec-out", "cat", dump_path]
        params = {"device_id": device_id}
        display = self.client.command_for_display(command, device_id)
        try:
            dump_result = self.client.run(command, device_id=device_id, timeout=20)
            xml_result = self.client.run(cat_command, device_id=device_id, timeout=20)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        xml = xml_result.stdout_text.strip()
        preview = dump_result.stdout_text + "\n" + xml[:1000]
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Dumped Android UI XML ({len(xml)} characters).",
            params=params,
            output_preview=preview,
        )
        return {"ok": True, "tool": tool, "xml": xml, "memory_entry_id": entry_id}

    def tap(self, x: int, y: int, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_tap"
        params = {"x": x, "y": y, "device_id": device_id}
        try:
            sx = _require_non_negative_int("x", x)
            sy = _require_non_negative_int("y", y)
            command = ["shell", "input", "tap", str(sx), str(sy)]
            display = self.client.command_for_display(command, device_id)
            result = self.client.run(command, device_id=device_id, timeout=10)
        except safety.ADBSafetyError as exc:
            command = ["shell", "input", "tap", str(x), str(y)]
            display = self.client.command_for_display(command, device_id)
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Tapped Android screen at ({sx}, {sy}).",
            params=params,
            output_preview=result.stdout_text,
        )
        return {"ok": True, "tool": tool, "x": sx, "y": sy, "memory_entry_id": entry_id}

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        tool = "adb_swipe"
        params = {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": duration_ms,
            "device_id": device_id,
        }
        try:
            sx1 = _require_non_negative_int("x1", x1)
            sy1 = _require_non_negative_int("y1", y1)
            sx2 = _require_non_negative_int("x2", x2)
            sy2 = _require_non_negative_int("y2", y2)
            duration = min(max(int(duration_ms), 0), 60000)
            command = [
                "shell",
                "input",
                "swipe",
                str(sx1),
                str(sy1),
                str(sx2),
                str(sy2),
                str(duration),
            ]
            display = self.client.command_for_display(command, device_id)
            result = self.client.run(command, device_id=device_id, timeout=15)
        except safety.ADBSafetyError as exc:
            command = ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)]
            display = self.client.command_for_display(command, device_id)
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Swiped Android screen from ({sx1}, {sy1}) to ({sx2}, {sy2}).",
            params=params,
            output_preview=result.stdout_text,
        )
        return {
            "ok": True,
            "tool": tool,
            "x1": sx1,
            "y1": sy1,
            "x2": sx2,
            "y2": sy2,
            "duration_ms": duration,
            "memory_entry_id": entry_id,
        }

    def input_text(self, text: str, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_input_text"
        params = {"text_length": len(text), "device_id": device_id}
        try:
            encoded = safety.validate_input_text(text)
            command = ["shell", "input", "text", encoded]
            display = self.client.command_for_display(_command_with_redacted_tail(command), device_id)
            result = self.client.run(command, device_id=device_id, timeout=10)
        except safety.ADBSafetyError as exc:
            command = ["shell", "input", "text", "<redacted>"]
            display = self.client.command_for_display(command, device_id)
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Entered {len(text)} character(s) of text on Android device.",
            params=params,
            output_preview=result.stdout_text,
        )
        return {"ok": True, "tool": tool, "text_length": len(text), "memory_entry_id": entry_id}

    def keyevent(self, keyevent: str | int, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_keyevent"
        key = str(keyevent).strip()
        params = {"keyevent": key, "device_id": device_id}
        command = ["shell", "input", "keyevent", key]
        display = self.client.command_for_display(command, device_id)
        try:
            if not key:
                raise safety.ADBSafetyError("keyevent is required")
            result = self.client.run(command, device_id=device_id, timeout=10)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Sent Android keyevent {key}.",
            params=params,
            output_preview=result.stdout_text,
        )
        return {"ok": True, "tool": tool, "keyevent": key, "memory_entry_id": entry_id}

    def current_app(self, device_id: str | None = None) -> dict[str, Any]:
        tool = "adb_current_app"
        command = ["shell", "dumpsys", "window"]
        params = {"device_id": device_id}
        display = self.client.command_for_display(command, device_id)
        try:
            result = self.client.run(command, device_id=device_id, timeout=20)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )

        raw_line = ""
        for line in result.stdout_text.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                raw_line = line.strip()
                break
        parsed = _parse_component(raw_line)
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Read current Android app: {parsed.get('package') or 'unknown'}.",
            params=params,
            output_preview=raw_line,
        )
        return {"ok": True, "tool": tool, **parsed, "memory_entry_id": entry_id}

    def open_app(
        self,
        package_name: str,
        activity: str | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        tool = "adb_open_app"
        params = {"package_name": package_name, "activity": activity, "device_id": device_id}
        try:
            if not _PACKAGE_RE.match(package_name):
                raise safety.ADBSafetyError(f"invalid Android package name: {package_name!r}")
            if activity:
                if not _ACTIVITY_RE.match(activity):
                    raise safety.ADBSafetyError(f"invalid Android activity name: {activity!r}")
                component = activity if "/" in activity else f"{package_name}/{activity}"
                command = ["shell", "am", "start", "-n", component]
            else:
                command = [
                    "shell",
                    "monkey",
                    "-p",
                    package_name,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ]
            display = self.client.command_for_display(command, device_id)
            result = self.client.run(command, device_id=device_id, timeout=20)
        except safety.ADBSafetyError as exc:
            command = ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
            display = self.client.command_for_display(command, device_id)
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Opened Android app {package_name}.",
            params=params,
            output_preview=result.stdout_text,
        )
        return {
            "ok": True,
            "tool": tool,
            "package_name": package_name,
            "activity": activity or "",
            "memory_entry_id": entry_id,
        }

    def read_logcat(
        self,
        lines: int = 200,
        filter_expr: str | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        tool = "adb_read_logcat"
        line_count = _bounded_lines(lines)
        params = {"lines": line_count, "filter_expr": filter_expr, "device_id": device_id}
        command = ["logcat", "-d", "-t", str(line_count)]
        if filter_expr:
            if not re.match(r"^[A-Za-z0-9_.*:\-\s]+$", filter_expr):
                exc = safety.ADBSafetyError("filter_expr contains unsupported characters")
                display = self.client.command_for_display(command, device_id)
                return self._blocked_payload(
                    tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
                )
            command.extend(filter_expr.split())
        display = self.client.command_for_display(command, device_id)
        try:
            result = self.client.run(command, device_id=device_id, timeout=30)
        except safety.ADBSafetyError as exc:
            return self._blocked_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        except ADBError as exc:
            return self._adb_error_payload(
                tool_name=tool, device_id=device_id, command=display, params=params, exc=exc
            )
        entry_id = self._record_success(
            tool_name=tool,
            device_id=device_id,
            command=display,
            summary=f"Read last {line_count} Android logcat line(s).",
            params=params,
            output_preview=result.stdout_text,
        )
        return {
            "ok": True,
            "tool": tool,
            "lines": line_count,
            "logcat": result.stdout_text,
            "memory_entry_id": entry_id,
        }
