"""Windows event watcher using SetWinEventHook + low-level input hooks.

Emits the same event_type names used by the macOS AX watcher so the
downstream EventDispatcher works unchanged:

  EVENT_SYSTEM_FOREGROUND   → AXApplicationActivated + AXFocusedWindowChanged
  EVENT_OBJECT_FOCUS        → AXFocusedWindowChanged
  EVENT_OBJECT_NAMECHANGE   → AXTitleChanged
  EVENT_OBJECT_VALUECHANGE  → AXValueChanged
  WH_MOUSE_LL click         → UserMouseClick (with x/y/button + element details)
  WH_KEYBOARD_LL key        → UserTextInput (debounced, modifier/nav filtered)

Parity with mac-ax-watcher.swift:

  * 5s typing debounce (matches kTextInputDebounceSeconds), with a 60s
    safety cap that force-flushes on continuous typing.
  * Ctrl / Win held → treated as shortcut, does NOT reset the debounce
    timer (matches mac's Cmd/Ctrl filter; Alt is allowed through for
    AltGr / international layouts).
  * Navigation keys (arrows, F1–F24, Home/End/PgUp/PgDn, Esc, etc.) are
    filtered out so they don't count as "typing".
  * Pending UserTextInput is flushed on focus change and on mouse
    click, so typed text is attributed to the *outgoing* field rather
    than the new one the user just moved to.
  * Each emitted event carries a local-tz ISO 8601 ``timestamp``.
  * UserMouseClick events carry ``details = {button, x, y, element}``,
    matching the mac shape exactly. ``button`` is one of
    ``left | right | other`` (mac doesn't distinguish middle clicks —
    middle/X-buttons collapse to ``other``).
  * UserTextInput events carry ``details = {reason, element}``.
  * The ``details.element`` dict is populated best-effort via the
    GUI-thread focus query (``GetGUIThreadInfo``) plus a class-name
    lookup. Mac's element comes from a synchronous AX hit-test which
    Windows can't do from inside a low-level hook callback (the system
    disables hooks if the callback exceeds LowLevelHooksTimeout ≈
    300ms). When we can't resolve a meaningful element we still emit
    the field with empty strings so the JSON schema is identical to
    mac's; downstream consumers tolerate empty values.
  * Window-title and element redaction kicks in when the focused
    control's class name looks like a password field (Edit + ES_PASSWORD
    style), matching mac's ``isFocusedSecure`` AX-subrole check.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..logger import get

logger = get("openchronicle.capture")

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

# ─── WinEvent constants ──────────────────────────────────────────────────
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_VALUECHANGE = 0x800E

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

OBJID_WINDOW = 0

# Low-level input hook constants
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13

WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B

WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# ─── Virtual-key codes used for the "is this a typing key?" filter ──
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt
VK_PAUSE = 0x13
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SELECT = 0x29
VK_PRINT = 0x2A
VK_EXECUTE = 0x2B
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_HELP = 0x2F
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_F1 = 0x70
VK_F24 = 0x87
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91

# Held-modifier mask returned by GetAsyncKeyState's high bit.
_HIGH_BIT = 0x8000

# ─── ctypes pointer-sized aliases ───────────────────────────────────────
# LRESULT / LONG_PTR / ULONG_PTR are pointer-sized on 64-bit Windows.
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


# ─── Win32 prototypes (argtypes/restype are mandatory on 64-bit) ─────
# Without these, ctypes assumes c_int for every parameter, silently
# truncating 64-bit handles (HWND, HHOOK, HANDLE) and pointer values.
# That's the root cause of the OverflowError previously seen on
# CallNextHookEx, but the same bug lurks in every other call.
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wt.HWND

user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD

user32.SetWinEventHook.argtypes = [
    wt.DWORD, wt.DWORD, wt.HMODULE,
    ctypes.c_void_p,  # WINEVENTPROC – ctypes will accept the WINFUNCTYPE callable
    wt.DWORD, wt.DWORD, wt.DWORD,
]
user32.SetWinEventHook.restype = wt.HANDLE

user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.UnhookWinEvent.restype = wt.BOOL

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, ctypes.c_void_p, wt.HINSTANCE, wt.DWORD,
]
user32.SetWindowsHookExW.restype = wt.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.UnhookWindowsHookEx.restype = wt.BOOL

user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT,
]
user32.GetMessageW.restype = wt.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.restype = wt.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE

kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


# ─── Focused-element discovery (best-effort, no UIA) ────────────────────
# These are used to populate ``details.element`` for parity with the
# mac watcher's describeElement(). Pure Win32 — no COM, no UIA — so
# they're cheap enough to call from the message loop after a hook fires.

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("flags", wt.DWORD),
        ("hwndActive", wt.HWND),
        ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND),
        ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND),
        ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wt.BOOL

user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

# GetWindowLongPtrW only exists as a function on 64-bit Windows; on 32-bit
# Python (rare) it's GetWindowLongW. Use getattr so the import doesn't
# explode in the (currently unsupported) 32-bit case.
_GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_GetWindowLongPtr.argtypes = [wt.HWND, ctypes.c_int]
_GetWindowLongPtr.restype = ctypes.c_ssize_t

# WindowFromPoint / ScreenToClient — used to identify the element under
# the mouse on click, matching mac's AXUIElementCopyElementAtPosition.
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wt.HWND

# Style bits that indicate a password Edit control (ES_PASSWORD = 0x0020).
GWL_STYLE = -16
ES_PASSWORD = 0x0020
WS_EX_NOREDIRECTIONBITMAP = 0x00200000  # not used directly, kept for ref


# ─── Callback type for SetWinEventHook ─────────────────────────────────
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wt.HANDLE,     # hWinEventHook
    wt.DWORD,      # event
    wt.HWND,       # hwnd
    ctypes.c_long, # idObject
    ctypes.c_long, # idChild
    wt.DWORD,      # idEventThread
    wt.DWORD,      # dwmsEventTime
)

# Low-level hook callback type
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wt.WPARAM,
    wt.LPARAM,
)


# ─── Tunables (matched to mac-ax-watcher.swift) ─────────────────────
_TEXT_INPUT_DEBOUNCE_SECONDS = 5.0
_TEXT_INPUT_MAX_CONTINUOUS_SECONDS = 60.0


def _now_iso_local() -> str:
    """Local-tz ISO 8601 with milliseconds, matching mac-ax-watcher."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _is_typing_vk(vk: int) -> bool:
    """Return True for keys that produce text content the user is typing.

    Modifiers, navigation keys, function keys, and lock keys are excluded
    so they don't reset the debounce timer (mirrors the mac watcher's
    private-use-area + modifier-flag filter).
    """
    if vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_APPS):
        return False
    if vk in (VK_CAPITAL, VK_NUMLOCK, VK_SCROLL, VK_PAUSE):
        return False
    if vk == VK_ESCAPE:
        return False
    if VK_PRIOR <= vk <= VK_HELP:
        # 0x21-0x2F: page up/down, end, home, arrows, select/print/exec,
        # snapshot, insert, delete, help. None of these are "typing".
        return False
    if VK_F1 <= vk <= VK_F24:
        return False
    return True


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


def _get_exe_path(pid: int) -> str:
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


def _window_context(hwnd: int) -> tuple[int, str, str, str]:
    """Resolve (pid, app_name, bundle_id, window_title) for a window.

    ``bundle_id`` is the full executable path — Windows' closest analogue
    to a macOS bundle identifier. ``app_name`` is the executable basename
    without extension, matching ``window_meta.active_window``.
    """
    title = _get_window_text(hwnd)
    pid = _get_window_pid(hwnd)
    exe = _get_exe_path(pid)
    app_name = Path(exe).stem if exe else ""
    return pid, app_name, exe, title


def _get_class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if n > 0 else ""


# Map common Win32 window class names to mac AX role strings. The pool is
# tiny on purpose — only common controls have stable, well-known classes.
# Anything else falls back to ``AX<ClassName>`` so the role at least
# carries some signal for debugging without polluting the mac AX
# vocabulary with garbage.
_CLASSNAME_TO_ROLE = {
    "Edit":              "AXTextField",
    "RICHEDIT50W":       "AXTextArea",
    "RICHEDIT60":        "AXTextArea",
    "RichEditA":         "AXTextArea",
    "RichEditW":         "AXTextArea",
    "Static":            "AXStaticText",
    "Button":            "AXButton",
    "ComboBox":          "AXComboBox",
    "ListBox":           "AXList",
    "SysListView32":     "AXList",
    "SysTreeView32":     "AXOutline",
    "SysHeader32":       "AXHeading",
    "SysTabControl32":   "AXTabGroup",
    "msctls_progress32": "AXProgressIndicator",
    "msctls_trackbar32": "AXSlider",
    "msctls_updown32":   "AXIncrementor",
    "ToolbarWindow32":   "AXToolbar",
    "ScrollBar":         "AXScrollBar",
    "#32768":            "AXMenu",
    "#32770":            "AXGroup",
}


def _classname_to_role(class_name: str) -> str:
    if not class_name:
        return ""
    if class_name in _CLASSNAME_TO_ROLE:
        return _CLASSNAME_TO_ROLE[class_name]
    return f"AX{class_name}"


def _is_secure_hwnd(hwnd: int) -> bool:
    """True if ``hwnd`` is a password edit control (Edit + ES_PASSWORD)."""
    if not hwnd:
        return False
    if _get_class_name(hwnd) != "Edit":
        return False
    try:
        style = _GetWindowLongPtr(hwnd, GWL_STYLE)
    except OSError:
        return False
    return bool(style & ES_PASSWORD)


def _focused_hwnd_for_window(hwnd: int) -> int:
    """Return the GUI focus HWND owned by the same thread as ``hwnd``.

    We pull the *thread*'s focus rather than ``GetFocus`` (which only
    returns a focus owned by the calling thread). This lines up with
    mac's ``AXUIElementCopyAttributeValue(app, kAXFocusedUIElementAttribute)``.
    """
    if not hwnd:
        return 0
    pid = wt.DWORD(0)
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not tid:
        return 0
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)


def _empty_element() -> dict[str, str]:
    """Schema-stable empty element matching mac describeElement()."""
    return {
        "role": "",
        "subrole": "",
        "title": "",
        "identifier": "",
        "value": "",
    }


def _describe_hwnd(hwnd: int) -> dict[str, str]:
    """Describe a HWND as a mac-watcher-style element dict.

    Mirrors describeElement() in mac-ax-watcher.swift. Subrole / identifier
    don't have direct Win32 equivalents — we leave them empty rather than
    fabricate values, so consumers can tell "missing on Windows" apart
    from "this control simply has none".
    """
    if not hwnd:
        return _empty_element()
    class_name = _get_class_name(hwnd)
    is_secure = _is_secure_hwnd(hwnd)
    title = _get_window_text(hwnd)
    if len(title) > 200:
        title = title[:200] + "…"
    return {
        "role": _classname_to_role(class_name),
        "subrole": "AXSecureTextField" if is_secure else "",
        "title": title,
        "identifier": "",
        "value": "[REDACTED]" if is_secure else "",
    }


def _is_focused_secure(window_hwnd: int) -> bool:
    """True if the focused control inside the foreground window is a secure
    edit. Matches mac-ax-watcher's ``isFocusedSecure``."""
    return _is_secure_hwnd(_focused_hwnd_for_window(window_hwnd))


def _build_event(
    event_type: str,
    hwnd: int,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an event dict matching mac-ax-watcher's JSONL shape.

    The ``hwnd`` field is Windows-specific: it carries the foreground
    HWND observed at the moment the hook fired. Downstream code uses it
    to anchor the win-uia-helper subprocess (which is session-isolated
    and can't see the desktop on its own). It has no mac counterpart —
    on mac the helper uses NSWorkspace.frontmostApplication, which is
    always available — so consumers of the cross-platform schema simply
    ignore the field outside of Windows.
    """
    pid, app_name, bundle_id, title = _window_context(hwnd)
    if _is_focused_secure(hwnd):
        title = "[REDACTED]"
    event: dict[str, Any] = {
        "event_type": event_type,
        "pid": pid,
        "app_name": app_name,
        "bundle_id": bundle_id,
        "window_title": title,
        "timestamp": _now_iso_local(),
        "hwnd": int(hwnd) if hwnd else 0,
    }
    if details is not None:
        event["details"] = details
    return event


def _ctrl_or_win_held() -> bool:
    """True if any Ctrl or Win key is currently down (shortcut indicator)."""
    return bool(
        user32.GetAsyncKeyState(VK_CONTROL) & _HIGH_BIT
        or user32.GetAsyncKeyState(VK_LWIN) & _HIGH_BIT
        or user32.GetAsyncKeyState(VK_RWIN) & _HIGH_BIT
    )


class _TextInputAggregator:
    """Debounces raw keystrokes into a single ``UserTextInput`` event.

    Mirrors ``InteractionTapper`` from mac-ax-watcher.swift: every typing
    keyDown resets a 5s debounce timer; the first keystroke of a burst
    captures the foreground window so a flush triggered by a focus
    change still attributes the text to the *outgoing* field. A 60s
    safety cap force-flushes during very long uninterrupted typing.

    A pending burst is flushed on focus change, mouse click, or
    watcher shutdown — ensuring the order of events downstream is
    "typed A, then clicked B" rather than "clicked B, typed A".
    """

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._typing_started_at: float | None = None
        self._typing_hwnd: int = 0

    def on_keystroke(self) -> None:
        """Record one keystroke. Resets the debounce timer."""
        force_flush = False
        with self._lock:
            if self._typing_started_at is None:
                self._typing_started_at = time.monotonic()
                # Capture the target window on the first keystroke of a
                # burst. We deliberately don't re-capture mid-burst — a
                # transient focus blip shouldn't reattribute the text.
                self._typing_hwnd = user32.GetForegroundWindow() or 0
            else:
                elapsed = time.monotonic() - self._typing_started_at
                if elapsed >= _TEXT_INPUT_MAX_CONTINUOUS_SECONDS:
                    force_flush = True

            if not force_flush:
                self._cancel_timer_locked()
                t = threading.Timer(
                    _TEXT_INPUT_DEBOUNCE_SECONDS,
                    lambda: self.flush("debounce"),
                )
                t.daemon = True
                self._timer = t
                t.start()

        if force_flush:
            self.flush("max_duration")

    def flush(self, reason: str) -> None:
        """Emit a pending UserTextInput. Idempotent if nothing buffered."""
        with self._lock:
            if self._typing_started_at is None:
                return
            hwnd = self._typing_hwnd
            self._typing_started_at = None
            self._typing_hwnd = 0
            self._cancel_timer_locked()

        # Resolve the focused HWND of the burst-target window. This is
        # the closest Win32 analogue to mac's ``focusedElement`` AX call.
        # When the control is a password edit, _describe_hwnd returns
        # role=AXTextField + subrole=AXSecureTextField + value=[REDACTED]
        # so the schema matches mac's secure-field redaction exactly.
        focus_hwnd = _focused_hwnd_for_window(hwnd) or hwnd
        element = _describe_hwnd(focus_hwnd)
        details = {"reason": reason, "element": element}
        try:
            self._emit(_build_event("UserTextInput", hwnd, details=details))
        except Exception as exc:  # noqa: BLE001
            logger.warning("UserTextInput emit failed: %s", exc)

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer_locked()
            self._typing_started_at = None
            self._typing_hwnd = 0

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class WinWatcherThread:
    """Windows event watcher running in a dedicated message-loop thread.

    Mirrors the AXWatcherProcess interface (``available``, ``running``,
    ``on_event``, ``start``, ``stop``) so the scheduler can use either
    interchangeably.
    """

    def __init__(self) -> None:
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._hooks: list[int] = []
        self._ll_hooks: list[int] = []

        # Must hold strong refs to the C callback objects so they're not
        # garbage-collected while a Win32 hook still has their pointer.
        self._winevent_proc: WINEVENTPROC | None = None
        self._mouse_proc: HOOKPROC | None = None
        self._keyboard_proc: HOOKPROC | None = None

        self._text_input = _TextInputAggregator(self._dispatch_safe)

    @property
    def available(self) -> bool:
        return True

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="win-watcher",
        )
        self._thread.start()
        logger.info("Windows event watcher started")

    def stop(self, *, join_timeout: float = 5.0) -> None:
        self._stop_event.set()
        # Flush any pending typing before tearing down so no UserTextInput
        # is silently dropped on shutdown.
        self._text_input.flush("shutdown")

        if self._thread and self._thread.is_alive():
            tid = self._thread.ident
            if tid:
                # Posting WM_QUIT unblocks GetMessageW; without it the
                # message loop sits forever and join() times out.
                user32.PostThreadMessageW(wt.DWORD(tid), WM_QUIT, 0, 0)
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                logger.warning(
                    "Windows watcher thread did not exit within %.1fs",
                    join_timeout,
                )
        self._thread = None
        logger.info("Windows event watcher stopped")

    # ─── Internal: message loop & dispatch ────────────────────────────

    def _dispatch_safe(self, event: dict[str, Any]) -> None:
        cb = self._callback
        if cb is None:
            return
        try:
            cb(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher event callback error: %s", exc)

    def _emit_internal(self, event_type: str) -> None:
        """Log a watcher-internal status event.

        Mirrors mac-ax-watcher's ``_*``-prefixed events: useful for
        diagnostics, but never forwarded to the dispatcher (which only
        understands semantic AX/Interaction events).
        """
        logger.debug("Watcher internal event: %s", event_type)

    def _run_loop(self) -> None:
        try:
            self._install_hooks()
            self._emit_internal("_watcher_started")

            msg = wt.MSG()
            while not self._stop_event.is_set():
                # Pump messages. WM_QUIT (posted by stop()) makes
                # GetMessageW return 0; -1 indicates an error.
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:  # noqa: BLE001
            logger.error("Windows watcher loop error: %s", exc)
        finally:
            self._text_input.shutdown()
            self._remove_hooks()
            self._emit_internal("_watcher_stopped")

    # ─── Hook install / remove ────────────────────────────────────────

    def _install_hooks(self) -> None:
        # WinEvent hooks for window / focus events. ``OUTOFCONTEXT``
        # delivers events on this thread via the message loop.
        self._winevent_proc = WINEVENTPROC(self._winevent_callback)
        winevent_proc_ptr = ctypes.cast(self._winevent_proc, ctypes.c_void_p)
        events = (
            EVENT_SYSTEM_FOREGROUND,
            EVENT_OBJECT_FOCUS,
            EVENT_OBJECT_NAMECHANGE,
            EVENT_OBJECT_VALUECHANGE,
        )
        for ev in events:
            hook = user32.SetWinEventHook(
                ev, ev,
                None,
                winevent_proc_ptr,
                0, 0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            )
            if hook:
                self._hooks.append(hook)
            else:
                logger.warning("SetWinEventHook failed for event 0x%04X", ev)

        # Low-level mouse hook for click detection.
        self._mouse_proc = HOOKPROC(self._mouse_callback)
        mhook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            ctypes.cast(self._mouse_proc, ctypes.c_void_p),
            None, 0,
        )
        if mhook:
            self._ll_hooks.append(mhook)
        else:
            logger.warning("SetWindowsHookExW(WH_MOUSE_LL) failed")

        # Low-level keyboard hook for typing detection.
        self._keyboard_proc = HOOKPROC(self._keyboard_callback)
        khook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            ctypes.cast(self._keyboard_proc, ctypes.c_void_p),
            None, 0,
        )
        if khook:
            self._ll_hooks.append(khook)
        else:
            logger.warning("SetWindowsHookExW(WH_KEYBOARD_LL) failed")

    def _remove_hooks(self) -> None:
        for hook in self._hooks:
            try:
                user32.UnhookWinEvent(hook)
            except OSError as exc:
                logger.debug("UnhookWinEvent error: %s", exc)
        self._hooks.clear()
        for hook in self._ll_hooks:
            try:
                user32.UnhookWindowsHookEx(hook)
            except OSError as exc:
                logger.debug("UnhookWindowsHookEx error: %s", exc)
        self._ll_hooks.clear()
        # Drop the C callbacks last so they outlive the hooks they're
        # attached to. (Order matters: an in-flight callback that fires
        # between Unhook and refcount-drop would otherwise crash.)
        self._winevent_proc = None
        self._mouse_proc = None
        self._keyboard_proc = None

    # ─── Callbacks ────────────────────────────────────────────────────

    def _winevent_callback(
        self,
        hook: int, event: int, hwnd: int,
        id_object: int, id_child: int,
        thread_id: int, event_time: int,
    ) -> None:
        if id_object != OBJID_WINDOW:
            return

        # Mac flushes any pending UserTextInput on focus / app
        # activation so typed text is attributed to the *outgoing*
        # field. We do the same here.
        if event in (EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_FOCUS):
            self._text_input.flush("focus_change")

        if event == EVENT_SYSTEM_FOREGROUND:
            self._dispatch_safe(_build_event("AXApplicationActivated", hwnd))
            self._dispatch_safe(_build_event("AXFocusedWindowChanged", hwnd))
        elif event == EVENT_OBJECT_FOCUS:
            self._dispatch_safe(_build_event("AXFocusedWindowChanged", hwnd))
        elif event == EVENT_OBJECT_NAMECHANGE:
            self._dispatch_safe(_build_event("AXTitleChanged", hwnd))
        elif event == EVENT_OBJECT_VALUECHANGE:
            self._dispatch_safe(_build_event("AXValueChanged", hwnd))

    def _mouse_callback(self, ncode: int, wparam: int, lparam: int) -> int:
        # Always chain to the next hook, no matter what — failing to do
        # so makes mouse input feel laggy / dropped system-wide.
        try:
            if ncode >= 0 and wparam in (
                WM_LBUTTONDOWN, WM_RBUTTONDOWN,
                WM_MBUTTONDOWN, WM_XBUTTONDOWN,
            ):
                self._handle_mouse_down(wparam, lparam)
        except Exception as exc:  # noqa: BLE001
            logger.debug("mouse callback error: %s", exc)
        return user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _handle_mouse_down(self, wparam: int, lparam: int) -> None:
        # Flush pending typing first so order is "typed, then clicked"
        # (matches mac-ax-watcher's flushText(reason: "mouse_click")).
        self._text_input.flush("mouse_click")

        # mac collapses middle/X-button into "other" via .otherMouseDown.
        # Match that exactly so downstream code doesn't need per-OS branches.
        button = {
            WM_LBUTTONDOWN: "left",
            WM_RBUTTONDOWN: "right",
            WM_MBUTTONDOWN: "other",
            WM_XBUTTONDOWN: "other",
        }.get(wparam, "other")

        try:
            data = ctypes.cast(
                ctypes.c_void_p(lparam),
                ctypes.POINTER(MSLLHOOKSTRUCT),
            ).contents
            x, y = data.pt.x, data.pt.y
        except (ValueError, OSError):
            x = y = 0

        # Resolve the HWND under the cursor; that's the click target for
        # the mac equivalent (AXUIElementCopyElementAtPosition). Fall back
        # to the foreground window when WindowFromPoint can't resolve.
        try:
            click_hwnd = user32.WindowFromPoint(POINT(x, y)) or 0
        except (ValueError, OSError):
            click_hwnd = 0
        hwnd = user32.GetForegroundWindow() or 0
        target_hwnd = click_hwnd or hwnd
        element = _describe_hwnd(target_hwnd)
        details: dict[str, Any] = {
            "button": button,
            "x": x,
            "y": y,
            "element": element,
        }
        self._dispatch_safe(
            _build_event("UserMouseClick", hwnd, details=details)
        )

    def _keyboard_callback(self, ncode: int, wparam: int, lparam: int) -> int:
        try:
            if ncode >= 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                self._handle_key_down(lparam)
        except Exception as exc:  # noqa: BLE001
            logger.debug("keyboard callback error: %s", exc)
        return user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _handle_key_down(self, lparam: int) -> None:
        try:
            data = ctypes.cast(
                ctypes.c_void_p(lparam),
                ctypes.POINTER(KBDLLHOOKSTRUCT),
            ).contents
            vk = data.vkCode
        except (ValueError, OSError):
            return

        # Ctrl / Cmd-equivalent (Win) held = shortcut, not typing.
        # Alt is allowed through because AltGr (right Alt) on
        # international layouts produces real characters.
        if _ctrl_or_win_held():
            return

        if not _is_typing_vk(vk):
            return

        self._text_input.on_keystroke()
