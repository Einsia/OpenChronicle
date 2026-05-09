"""Android ADB implementation of the RPA provider contract."""

from __future__ import annotations

import re
import time
from typing import Any

from ....adb import ADBController
from ....adb.client import ADBError
from ...ocr import OCRObserver, create_ocr_observer
from ...provider import RPAProvider
from ...trace import screens_dir
from .input import center_of_box, relative_to_absolute
from .safety import assess_android_action
from .screenshot import crop_region

_SIZE_RE = re.compile(r"Physical size:\s*(?P<width>\d+)x(?P<height>\d+)")


class Provider(RPAProvider):
    name = "android_adb"
    platform = "android"

    def __init__(
        self,
        *,
        controller: ADBController | None = None,
        ocr: OCRObserver | None = None,
        device_id: str | None = None,
    ) -> None:
        self.controller = controller or ADBController()
        self.ocr = ocr or create_ocr_observer()
        self.device_id = device_id
        self._last_screen_size: list[int] = [0, 0]

    def capabilities(self) -> dict[str, Any]:
        return {
            "actions": [
                "tap",
                "tap_relative",
                "tap_text",
                "type",
                "swipe",
                "back",
                "home",
                "launch_app",
                "wait",
                "takeover",
            ],
            "observe": ["screenshot", "ocr", "current_app", "screen_size", "ui_xml"],
            "screenshot_modes": ["keyframe", "region", "full"],
            "safety": {
                "no_raw_adb_shell": True,
                "requires_confirmation": [
                    "payment",
                    "order",
                    "delete",
                    "send_message",
                    "login",
                    "permission_grant",
                ],
            },
        }

    def observe(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        observation: dict[str, Any] = {
            "provider": self.name,
            "platform": self.platform,
            "errors": [],
            "ocr": [],
        }
        screenshot_mode = str(options.get("screenshot") or "none")
        if screenshot_mode in {"keyframe", "region", "full"}:
            screenshot = self._capture_screenshot(screenshot_mode, options.get("region"))
            if screenshot.get("ok"):
                observation["screenshot"] = screenshot.get("path", "")
                observation["screenshot_mode"] = screenshot_mode
                if options.get("ocr", screenshot_mode in {"keyframe", "region"}):
                    region = options.get("region") if screenshot_mode == "region" else None
                    observation["ocr"] = self.ocr.recognize(str(screenshot.get("path", "")), region)
            else:
                observation["errors"].append(_error_message(screenshot))

        current_app = self.controller.current_app(device_id=self.device_id)
        if current_app.get("ok"):
            observation["current_app"] = current_app.get("package", "")
            observation["app"] = current_app.get("package", "")
            observation["activity"] = current_app.get("activity", "")
        else:
            observation["errors"].append(_error_message(current_app))

        size = self.screen_size()
        if size.get("ok"):
            observation["screen_size"] = [size["width"], size["height"]]
            self._last_screen_size = observation["screen_size"]
        else:
            observation["errors"].append(_error_message(size))

        ui = self.controller.dump_ui(device_id=self.device_id)
        if ui.get("ok"):
            observation["ui_xml"] = ui.get("xml", "")
        else:
            observation["errors"].append(_error_message(ui))
        observation["ok"] = not observation["errors"]
        return observation

    def _capture_screenshot(self, mode: str, region: Any = None) -> dict[str, Any]:
        screenshot = self.controller.screenshot(device_id=self.device_id)
        if not screenshot.get("ok") or mode != "region":
            return screenshot
        if not region:
            return {"ok": False, "error": "region screenshot requires region"}
        try:
            out_path = screens_dir() / f"android-region-{time.time_ns()}.png"
            path = crop_region(str(screenshot.get("path", "")), list(region), str(out_path))
        except Exception as exc:  # noqa: BLE001 - region crop is best-effort
            return {"ok": False, "error": str(exc), "source_path": screenshot.get("path", "")}
        return {**screenshot, "path": path, "source_path": screenshot.get("path", "")}

    def screen_size(self) -> dict[str, Any]:
        command = ["shell", "wm", "size"]
        try:
            result = self.controller.client.run(command, device_id=self.device_id, timeout=10)
        except ADBError as exc:
            return {"ok": False, "error": str(exc)}
        match = _SIZE_RE.search(result.stdout_text)
        if not match:
            return {"ok": False, "error": "could not parse Android screen size"}
        return {
            "ok": True,
            "width": int(match.group("width")),
            "height": int(match.group("height")),
        }

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        safety = assess_android_action(action)
        if not safety["allowed"]:
            return {
                "ok": False,
                "status": "blocked",
                "message": safety["reason"],
                "action": action,
                "safety": safety,
            }

        kind = str(action.get("action") or action.get("type") or "")
        if kind == "tap":
            return self._with_action(self.controller.tap(action["x"], action["y"], self.device_id), action)
        if kind == "tap_relative":
            x, y = self._resolve_relative(action)
            resolved = {**action, "action": "tap", "x": x, "y": y, "resolved_point": [x, y]}
            return self._with_action(self.controller.tap(x, y, self.device_id), resolved)
        if kind == "tap_text":
            return self._tap_text(action)
        if kind == "swipe":
            return self._with_action(
                self.controller.swipe(
                    action["x1"],
                    action["y1"],
                    action["x2"],
                    action["y2"],
                    action.get("duration_ms", 300),
                    self.device_id,
                ),
                action,
            )
        if kind == "type":
            value = str(action.get("value") or action.get("text") or "")
            return self._with_action(self.controller.input_text(value, self.device_id), action)
        if kind == "back":
            return self._with_action(self.controller.keyevent("BACK", self.device_id), action)
        if kind == "home":
            return self._with_action(self.controller.keyevent("HOME", self.device_id), action)
        if kind == "launch_app":
            package = str(action.get("package") or action.get("package_name") or "")
            return self._with_action(
                self.controller.open_app(package, action.get("activity"), self.device_id),
                action,
            )
        if kind == "wait":
            seconds = min(max(float(action.get("seconds", action.get("duration", 1))), 0), 60)
            time.sleep(seconds)
            return {"ok": True, "status": "success", "message": f"waited {seconds:g}s", "action": action}
        if kind == "takeover":
            return {
                "ok": True,
                "status": "takeover",
                "message": "manual takeover requested",
                "action": action,
            }
        return {
            "ok": False,
            "status": "unsupported",
            "message": f"unsupported action: {kind}",
            "action": action,
        }

    def _tap_text(self, action: dict[str, Any]) -> dict[str, Any]:
        target = str(action.get("text") or "")
        screenshot = self.controller.screenshot(device_id=self.device_id)
        ocr_items = []
        if screenshot.get("ok"):
            ocr_items = self.ocr.recognize(str(screenshot.get("path", "")))
        for item in ocr_items:
            if target and target in str(item.get("text", "")) and item.get("box"):
                x, y = center_of_box(item["box"])
                resolved = {**action, "resolved_point": [x, y], "ocr_text": item.get("text", "")}
                return self._with_action(self.controller.tap(x, y, self.device_id), resolved)
        fallback = action.get("fallback_area")
        if fallback:
            x, y = center_of_box(list(fallback))
            resolved = {**action, "resolved_point": [x, y], "fallback_used": True}
            return self._with_action(self.controller.tap(x, y, self.device_id), resolved)
        return {
            "ok": False,
            "status": "failed",
            "message": f"text not found by OCR: {target}",
            "action": action,
        }

    def _resolve_relative(self, action: dict[str, Any]) -> tuple[int, int]:
        screen_size = self._last_screen_size
        if not all(screen_size):
            size = self.screen_size()
            if size.get("ok"):
                screen_size = [size["width"], size["height"]]
                self._last_screen_size = screen_size
        if not all(screen_size):
            return int(action["x"]), int(action["y"])
        return relative_to_absolute(int(action["x"]), int(action["y"]), screen_size)

    def _with_action(self, result: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        status = "success" if result.get("ok") else ("blocked" if result.get("blocked") else "failed")
        message = str(result.get("message") or result.get("error") or "")
        return {**result, "status": status, "message": message, "action": action}


def _error_message(result: dict[str, Any]) -> str:
    return str(result.get("error") or result.get("message") or result)
