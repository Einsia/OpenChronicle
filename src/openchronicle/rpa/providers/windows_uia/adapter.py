"""Windows UIA RPA provider skeleton."""

from __future__ import annotations

import time
from typing import Any

from ....capture.window_meta import active_window
from ....capture.windows_uia import WindowsUIAProvider
from ...provider import RPAProvider
from ...safety import assess_action


class Provider(RPAProvider):
    name = "windows_uia"
    platform = "windows"

    def __init__(self, *, depth: int = 3, timeout: int = 3) -> None:
        self._depth = depth
        self._timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        return {
            "actions": ["click", "type", "hotkey", "wait"],
            "observe": ["window_title", "process_name", "control_tree"],
            "safety": {"requires_confirmation": ["payment", "order", "delete", "send_message", "login"]},
        }

    def observe(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        del options
        meta = active_window()
        observation: dict[str, Any] = {
            "provider": self.name,
            "platform": self.platform,
            "window_title": meta.title,
            "process_name": meta.bundle_id,
            "app": meta.app_name,
            "errors": [],
            "ocr": [],
        }
        provider = WindowsUIAProvider(depth=self._depth, timeout=self._timeout)
        capture = provider.capture_frontmost()
        if capture is not None:
            observation["control_tree"] = capture.raw_json
        elif provider.reason:
            observation["errors"].append(provider.reason)
        observation["ok"] = not observation["errors"]
        return observation

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        safety = assess_action(action)
        if not safety["allowed"]:
            return {
                "ok": False,
                "status": "blocked",
                "message": safety["reason"],
                "action": action,
                "safety": safety,
            }
        kind = str(action.get("action") or action.get("type") or "")
        if kind == "wait":
            seconds = min(max(float(action.get("seconds", action.get("duration", 1))), 0), 60)
            time.sleep(seconds)
            return {"ok": True, "status": "success", "message": f"waited {seconds:g}s", "action": action}
        return {
            "ok": False,
            "status": "unsupported",
            "message": f"windows_uia action {kind!r} is registered but not implemented yet",
            "action": action,
        }
