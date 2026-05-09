"""Foreground app / window metadata.

Extracted from Einsia-Partner's capture_service.get_active_window_macos().
"""

from __future__ import annotations

import ctypes
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

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

_WINDOWS_DISPLAY_NAMES = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
}


@dataclass
class WindowMeta:
    app_name: str = ""
    title: str = ""
    bundle_id: str = ""


def active_window() -> WindowMeta:
    system = platform.system()
    if system == "Windows":
        return _active_window_windows()
    if system != "Darwin":
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


def _active_window_windows() -> WindowMeta:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return WindowMeta()

    title_length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe_name = _process_exe_name(pid.value)
    bundle_id = exe_name.lower()
    app_name = _WINDOWS_DISPLAY_NAMES.get(bundle_id) or (
        Path(exe_name).stem if exe_name else ""
    )
    return WindowMeta(app_name=app_name, title=title_buffer.value, bundle_id=bundle_id)


def _process_exe_name(pid: int) -> str:
    if not pid:
        return ""

    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""

    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        if not ok:
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)
