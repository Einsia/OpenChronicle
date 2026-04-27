"""Foreground app / window metadata — cross-platform.

macOS: osascript (AppleScript via System Events)
Windows: ctypes (user32 / kernel32)
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from ..logger import get

logger = get("openchronicle.capture")

_MACOS_SCRIPT = """
tell application "System Events"
    set frontProc to first application process whose frontmost is true
    set appName to name of frontProc
    try
        set bundleId to bundle identifier of frontProc
    on error
        set bundleId to ""
    end try
    try
        set winTitle to name of front window of frontProc
    on error
        set winTitle to ""
    end try
    return appName & "\\n" & winTitle & "\\n" & bundleId
end tell
"""


@dataclass
class WindowMeta:
    app_name: str = ""
    title: str = ""
    bundle_id: str = ""


def _active_window_darwin() -> WindowMeta:
    try:
        proc = subprocess.run(
            ["osascript", "-e", _MACOS_SCRIPT], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("osascript failed: %s", exc)
        return WindowMeta()

    if proc.returncode != 0:
        logger.debug("osascript rc=%d stderr=%s", proc.returncode, proc.stderr.strip()[:200])
        return WindowMeta()

    parts = proc.stdout.strip().split("\n")
    return WindowMeta(
        app_name=parts[0] if len(parts) > 0 else "",
        title=parts[1] if len(parts) > 1 else "",
        bundle_id=parts[2] if len(parts) > 2 else "",
    )


def _active_window_windows() -> WindowMeta:
    try:
        from .win_meta import get_active_window_info

        info = get_active_window_info()
        return WindowMeta(
            app_name=info.get("app_name", ""),
            title=info.get("title", ""),
            bundle_id=info.get("bundle_id", ""),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("win_meta failed: %s", exc)
        return WindowMeta()


_SYSTEM = platform.system()


def active_window() -> WindowMeta:
    if _SYSTEM == "Darwin":
        return _active_window_darwin()
    if _SYSTEM == "Windows":
        return _active_window_windows()
    return WindowMeta()
