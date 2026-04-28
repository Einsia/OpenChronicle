"""Windows window metadata via ctypes (user32 / kernel32).

Provides the same WindowMeta fields as the macOS osascript path:
  app_name  – executable basename without extension (e.g. "Code")
  title     – foreground window title text
  bundle_id – full executable path (closest Windows analogue to macOS bundle ID)

NOTE on argtypes/restype: declaring these is mandatory on 64-bit Windows.
Without them, ctypes assumes ``c_int`` (32-bit) for every parameter and
silently truncates HWND / HANDLE pointer values, producing garbage results
or — when a 64-bit pointer is treated as a Python int parameter — an
``OverflowError`` at call time. See the comment in ``win_watcher.py`` for
context.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from pathlib import Path

from ..logger import get

logger = get("openchronicle.capture")

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND

user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE

kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


def _get_foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def _get_window_text(hwnd: int) -> str:
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_pid(hwnd: int) -> int:
    if not hwnd:
        return 0
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_process_exe(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        kernel32.CloseHandle(handle)


def get_active_window_info() -> dict[str, str]:
    """Return foreground window metadata on Windows."""
    try:
        hwnd = _get_foreground_window()
        if not hwnd:
            return {"app_name": "", "title": "", "bundle_id": ""}

        title = _get_window_text(hwnd)
        pid = _get_window_pid(hwnd)
        exe_path = _get_process_exe(pid)
        app_name = Path(exe_path).stem if exe_path else ""

        return {
            "app_name": app_name,
            "title": title,
            "bundle_id": exe_path,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("win_meta: failed to get active window info: %s", exc)
        return {"app_name": "", "title": "", "bundle_id": ""}
