"""Windows UI Automation capture and polling event source.

This module adapts Windows UI Automation controls into the same AX-shaped JSON
that the macOS helper emits, so the existing S1 parser and downstream memory
pipeline do not need a Windows-specific path.
"""

from __future__ import annotations

import contextlib
import platform
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..logger import get
from .ax_models import AXCaptureResult
from .window_meta import WindowMeta, active_window

logger = get("openchronicle.capture")

_MAX_CHILDREN_PER_NODE = 80
_MAX_TOTAL_NODES = 2_000


def _import_uia() -> tuple[Any | None, str | None]:
    if platform.system() != "Windows":
        return None, f"unsupported platform: {platform.system()}"
    try:
        import uiautomation as auto  # type: ignore[import-not-found]
    except ImportError as exc:
        return None, f"missing optional dependency 'uiautomation': {exc}"
    return auto, None


def _call_or_value(obj: Any, name: str, default: Any = "") -> Any:
    try:
        value = getattr(obj, name)
    except Exception:  # noqa: BLE001 - third-party COM wrappers raise varied errors
        return default
    if callable(value):
        try:
            return value()
        except Exception:  # noqa: BLE001
            return default
    return value


def _text(value: Any, *, limit: int = 2_000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "").strip()
    if len(value) > limit:
        return value[:limit] + "...(truncated)"
    return value


def _control_value(control: Any) -> str:
    for attr in ("Value", "value"):
        value = _text(_call_or_value(control, attr, default=""))
        if value:
            return value

    for method in ("GetValuePattern", "GetLegacyIAccessiblePattern"):
        getter = getattr(control, method, None)
        if not callable(getter):
            continue
        try:
            pattern = getter()
        except Exception:  # noqa: BLE001
            continue
        for attr in ("Value", "Name", "Description"):
            value = _text(_call_or_value(pattern, attr, default=""))
            if value:
                return value
    return ""


def _control_name(control: Any) -> str:
    return _text(_call_or_value(control, "Name", default=""), limit=1_000)


def _control_type(control: Any) -> str:
    return _text(_call_or_value(control, "ControlTypeName", default=""), limit=200)


def _automation_id(control: Any) -> str:
    return _text(_call_or_value(control, "AutomationId", default=""), limit=200)


def _class_name(control: Any) -> str:
    return _text(_call_or_value(control, "ClassName", default=""), limit=200)


def _role_for_control(control_type: str) -> str:
    compact = control_type.replace(" ", "").lower()
    if "edit" in compact:
        return "AXTextField"
    if "document" in compact:
        return "AXWebArea"
    if "text" in compact:
        return "AXStaticText"
    if "button" in compact:
        return "AXButton"
    if "combobox" in compact:
        return "AXComboBox"
    if "menuitem" in compact:
        return "AXMenuItem"
    if "tabitem" in compact:
        return "AXTab"
    if "listitem" in compact:
        return "AXRow"
    if "window" in compact:
        return "AXWindow"
    if "pane" in compact or "group" in compact:
        return "AXGroup"
    return f"AX{control_type}" if control_type else "AXUnknown"


def _iter_children(control: Any) -> Iterable[Any]:
    get_children = getattr(control, "GetChildren", None)
    if callable(get_children):
        try:
            yield from list(get_children())[:_MAX_CHILDREN_PER_NODE]
            return
        except Exception:  # noqa: BLE001
            pass

    first_child = getattr(control, "GetFirstChildControl", None)
    if not callable(first_child):
        return
    try:
        child = first_child()
    except Exception:  # noqa: BLE001
        return

    count = 0
    while child is not None and count < _MAX_CHILDREN_PER_NODE:
        yield child
        count += 1
        next_sibling = getattr(child, "GetNextSiblingControl", None)
        if not callable(next_sibling):
            break
        try:
            child = next_sibling()
        except Exception:  # noqa: BLE001
            break


@dataclass
class _Budget:
    remaining: int = _MAX_TOTAL_NODES

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _element_from_control(control: Any, *, depth: int, budget: _Budget) -> dict[str, Any] | None:
    if depth < 0 or not budget.take():
        return None

    control_type = _control_type(control)
    name = _control_name(control)
    value = _control_value(control)
    role = _role_for_control(control_type)

    children: list[dict[str, Any]] = []
    if depth > 0:
        for child in _iter_children(control):
            child_el = _element_from_control(child, depth=depth - 1, budget=budget)
            if child_el is not None:
                children.append(child_el)

    element: dict[str, Any] = {
        "role": role,
        "title": name,
        "value": value,
    }
    automation_id = _automation_id(control)
    class_name = _class_name(control)
    if automation_id:
        element["identifier"] = automation_id
    if class_name:
        element["class_name"] = class_name
    with contextlib.suppress(Exception):
        if bool(_call_or_value(control, "HasKeyboardFocus", default=False)):
            element["focused"] = True
    if children:
        element["children"] = children

    if not name and not value and not children:
        return None
    return element


def _safe_foreground_control(auto: Any) -> Any | None:
    getter = getattr(auto, "GetForegroundControl", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Windows UIA foreground control failed: %s", exc)
        return None


def _safe_focused_control(auto: Any) -> Any | None:
    getter = getattr(auto, "GetFocusedControl", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:  # noqa: BLE001
        return None


def _control_identity(control: Any | None) -> tuple[str, str, str, str]:
    if control is None:
        return ("", "", "", "")
    return (
        _text(_call_or_value(control, "ProcessId", default=""), limit=50),
        _control_type(control),
        _automation_id(control),
        _control_name(control),
    )


class WindowsUIAProvider:
    """One-shot Windows UI Automation provider."""

    def __init__(self, *, depth: int, timeout: int, auto_module: Any | None = None) -> None:
        auto, reason = (auto_module, None) if auto_module is not None else _import_uia()
        self._auto = auto
        self.reason = reason or ""
        self._depth = max(depth, 0)
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return self._auto is not None

    def capture_frontmost(self, *, focused_window_only: bool = True) -> AXCaptureResult | None:
        return self._capture()

    def capture_all_visible(self) -> AXCaptureResult | None:
        return self._capture()

    def capture_app(
        self, app_name: str, *, focused_window_only: bool = True
    ) -> AXCaptureResult | None:
        return self._capture()

    def _capture(self) -> AXCaptureResult | None:
        if self._auto is None:
            return None

        meta = active_window()
        foreground = _safe_foreground_control(self._auto)
        if foreground is None:
            return None

        budget = _Budget()
        root_el = _element_from_control(foreground, depth=self._depth, budget=budget)
        elements: list[dict[str, Any]] = []
        focused = _safe_focused_control(self._auto)
        focused_el = None
        if focused is not None and _control_identity(focused) != _control_identity(foreground):
            focused_el = _element_from_control(focused, depth=min(self._depth, 3), budget=budget)
        if focused_el is not None:
            elements.append(focused_el)
        if root_el is not None:
            elements.extend(root_el.pop("children", []) or [root_el])

        title = meta.title or _control_name(foreground)
        app_name = meta.app_name or "Windows App"
        bundle_id = meta.bundle_id or "unknown.exe"
        tree = {
            "timestamp": "",
            "apps": [
                {
                    "name": app_name,
                    "bundle_id": bundle_id,
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": title,
                            "focused": True,
                            "elements": elements,
                        }
                    ],
                }
            ],
        }
        return AXCaptureResult(
            raw_json=tree,
            timestamp="",
            apps=tree["apps"],
            metadata={
                "mode": "frontmost",
                "depth": self._depth,
                "platform": "windows",
                "provider": "uiautomation",
                "timeout": self._timeout,
            },
        )


class WindowsPollingWatcher:
    """Polling event source for Windows.

    It emits macOS-style event names so the existing EventDispatcher can keep
    applying the same debounce and dedup rules.
    """

    def __init__(self, *, interval_seconds: float = 5.0) -> None:
        self._interval = max(interval_seconds, 1.0)
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last: WindowMeta | None = None

    @property
    def available(self) -> bool:
        return platform.system() == "Windows"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        if not self.available:
            logger.warning("Windows polling watcher unavailable on %s", platform.system())
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="windows-uia-poller"
        )
        self._thread.start()
        logger.info("Windows polling capture started (interval=%.1fs)", self._interval)

    def stop(self, *, join_timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                logger.warning("Windows polling watcher did not exit within %.1fs", join_timeout)
        self._thread = None
        logger.info("Windows polling capture stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._interval)

    def _poll_once(self) -> None:
        meta = active_window()
        if not meta.app_name and not meta.title and not meta.bundle_id:
            return

        event_type = "AXValueChanged"
        if self._last is None or meta.bundle_id != self._last.bundle_id:
            event_type = "AXApplicationActivated"
        elif meta.title != self._last.title:
            event_type = "AXFocusedWindowChanged"
        self._last = meta

        if self._callback is not None:
            self._callback(
                {
                    "event_type": event_type,
                    "app": meta.app_name,
                    "bundle_id": meta.bundle_id,
                    "window_title": meta.title,
                }
            )


def create_provider(*, depth: int = 8, timeout: int = 3, raw: bool = False) -> WindowsUIAProvider:
    return WindowsUIAProvider(depth=depth, timeout=timeout)
