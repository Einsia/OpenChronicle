"""Foreground app / window metadata via osascript. macOS only in v1.

Extracted from Einsia-Partner's capture_service.get_active_window_macos().
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from ..logger import get

logger = get("openchronicle.capture")

_SCRIPT = """
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


def active_window() -> WindowMeta:
    if platform.system() != "Darwin":
        return WindowMeta()
    try:
        proc = subprocess.run(
            ["osascript", "-e", _SCRIPT], capture_output=True, text=True, timeout=5
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
