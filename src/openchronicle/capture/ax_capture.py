"""Cross-platform AX / UI Automation tree capture.

macOS: vendored ``mac-ax-helper`` Swift binary
Windows: vendored ``win-uia-helper.ps1`` PowerShell script (uses .NET UIAutomation)

Ported from Einsia-Partner's backend/core/capture/ax_capture_service.py with
resource resolution adapted for a uv/pip-installable package.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Protocol

from ..logger import get
from .ax_models import AXCaptureResult

logger = get("openchronicle.capture")

_SUBPROCESS_TIMEOUT = 10  # seconds (covers --timeout 3 + overhead)
_WIN_SUBPROCESS_TIMEOUT = 15  # PowerShell startup overhead


def _foreground_hwnd_pid() -> tuple[int, int]:
    """Resolve (hwnd, pid) of the current foreground window.

    Used on Windows to anchor the win-uia-helper subprocess to the user's
    actual foreground app (the helper itself can't see the desktop —
    see _run() for the why). On non-Windows or if the call fails we
    return (0, 0); the helper falls back to its own GetForegroundWindow.
    """
    if platform.system() != "Windows":
        return (0, 0)
    try:
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wt.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wt.HWND, ctypes.POINTER(wt.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wt.DWORD
        hwnd = user32.GetForegroundWindow() or 0
        if not hwnd:
            return (0, 0)
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return (int(hwnd), int(pid.value))
    except Exception as exc:  # noqa: BLE001
        logger.debug("foreground HWND query failed: %s", exc)
        return (0, 0)


def _strip_frame_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_frame_fields(v) for k, v in value.items() if k != "frame"}
    if isinstance(value, list):
        return [_strip_frame_fields(item) for item in value]
    return value


def _maybe_compile(swift_path: Path, binary_path: Path) -> None:
    """Dev/first-run: compile the helper if missing or stale."""
    if not swift_path.is_file():
        return
    if binary_path.is_file():
        if binary_path.stat().st_mtime >= swift_path.stat().st_mtime:
            return
        logger.info("mac-ax-helper: source newer than binary, recompiling")
    else:
        logger.info("mac-ax-helper: binary missing, compiling from source")

    cache = Path("/tmp/clang-module-cache")
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(cache)
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "x86_64"
    target = f"{arch}-apple-macos12.0"
    try:
        result = subprocess.run(
            [
                "swiftc",
                str(swift_path),
                "-o",
                str(binary_path),
                "-O",
                "-target",
                target,
                "-swift-version",
                "5",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("mac-ax-helper compile failed: %s (install Xcode CLT?)", exc)
        return
    if result.returncode != 0:
        logger.warning(
            "mac-ax-helper compile failed (%d): %s",
            result.returncode,
            result.stderr.strip()[:300],
        )


def _resolve_helper_path() -> Path | None:
    """Find or build the mac-ax-helper binary.

    Search order:
      1. OPENCHRONICLE_AX_HELPER env var (absolute path)
      2. Packaged resource shipped with the wheel (_bundled/)
      3. Dev source tree (../../../resources/ relative to this file)
    """
    if platform.system() != "Darwin":
        return None

    override = os.environ.get("OPENCHRONICLE_AX_HELPER")
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file() and os.access(p, os.X_OK):
            return p
        logger.warning("OPENCHRONICLE_AX_HELPER set but not executable: %s", p)

    candidates: list[Path] = []

    # 1. Bundled inside the installed package (wheel ships .swift; binary built on demand)
    try:
        from importlib.resources import files as _pkg_files

        bundled_dir = Path(str(_pkg_files("openchronicle").joinpath("_bundled")))
        candidates.append(bundled_dir / "mac-ax-helper")
    except (ModuleNotFoundError, ValueError):
        pass

    # 2. Dev source tree
    dev_root = Path(__file__).resolve().parents[3]  # .../OpenChronicle/
    candidates.append(dev_root / "resources" / "mac-ax-helper")

    for binary_path in candidates:
        swift_path = binary_path.with_suffix(".swift")
        if swift_path.is_file():
            _maybe_compile(swift_path, binary_path)
        if binary_path.is_file() and os.access(binary_path, os.X_OK):
            return binary_path

    return None


class AXProvider(Protocol):
    @property
    def available(self) -> bool: ...

    def capture_frontmost(
        self,
        *,
        focused_window_only: bool = True,
        anchor_hwnd: int = 0,
        anchor_pid: int = 0,
    ) -> AXCaptureResult | None: ...

    def capture_all_visible(self) -> AXCaptureResult | None: ...

    def capture_app(
        self, app_name: str, *, focused_window_only: bool = True
    ) -> AXCaptureResult | None: ...


class UnavailableAXProvider:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    @property
    def available(self) -> bool:
        return False

    def capture_frontmost(
        self,
        *,
        focused_window_only: bool = True,
        anchor_hwnd: int = 0,
        anchor_pid: int = 0,
    ) -> AXCaptureResult | None:
        return None

    def capture_all_visible(self) -> AXCaptureResult | None:
        return None

    def capture_app(
        self, app_name: str, *, focused_window_only: bool = True
    ) -> AXCaptureResult | None:
        return None


class MacAXHelperProvider:
    """Subprocess wrapper around the vendored mac-ax-helper Swift binary."""

    def __init__(self, *, helper_path: Path, depth: int, timeout: int, raw: bool = False) -> None:
        self._helper_path = str(helper_path)
        self._depth = depth
        self._timeout = timeout
        self._raw = raw

    @property
    def available(self) -> bool:
        return True

    def capture_frontmost(
        self,
        *,
        focused_window_only: bool = True,
        anchor_hwnd: int = 0,
        anchor_pid: int = 0,
    ) -> AXCaptureResult | None:
        # mac-ax-helper resolves the frontmost app via NSWorkspace; the
        # anchor_hwnd / anchor_pid hints are Windows-only and ignored here.
        del anchor_hwnd, anchor_pid
        return self._run(all_visible=False, focused_window_only=focused_window_only)

    def capture_all_visible(self) -> AXCaptureResult | None:
        return self._run(all_visible=True)

    def capture_app(
        self, app_name: str, *, focused_window_only: bool = True
    ) -> AXCaptureResult | None:
        return self._run(
            all_visible=False, app_name=app_name, focused_window_only=focused_window_only
        )

    def _run(
        self,
        *,
        all_visible: bool,
        app_name: str | None = None,
        focused_window_only: bool = False,
    ) -> AXCaptureResult | None:
        args: list[str] = [self._helper_path]
        if app_name:
            args.extend(["--app-name", app_name])
        elif all_visible:
            args.append("--all-visible")
        if focused_window_only:
            args.append("--focused-window-only")
        if self._raw:
            args.append("--raw")
        if self._depth > 0:
            args.extend(["--depth", str(self._depth)])
        args.extend(["--timeout", str(self._timeout)])

        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            logger.warning("mac-ax-helper timed out after %ds", _SUBPROCESS_TIMEOUT)
            return None
        except OSError as exc:
            logger.error("Failed to run mac-ax-helper: %s", exc)
            return None

        if proc.returncode == 2:
            logger.warning(
                "Accessibility permission not granted. "
                "Grant access to your terminal in System Settings → Privacy & Security → Accessibility."
            )
            return None
        if proc.returncode != 0:
            logger.warning(
                "mac-ax-helper exited %d: %s", proc.returncode, proc.stderr.strip()[:200]
            )
            return None

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse mac-ax-helper JSON: %s", exc)
            return None

        data = _strip_frame_fields(data)
        mode = "all-visible" if all_visible else "frontmost"
        return AXCaptureResult(
            raw_json=data,
            timestamp=data.get("timestamp", ""),
            apps=data.get("apps", []),
            metadata={"mode": mode, "depth": self._depth, "platform": "macos", "raw": self._raw},
        )


class WinUIAutomationProvider:
    """Subprocess wrapper around the vendored win-uia-helper.ps1 PowerShell script."""

    def __init__(self, *, script_path: Path, depth: int, timeout: int, raw: bool = False) -> None:
        self._script_path = str(script_path)
        self._depth = depth
        self._timeout = timeout
        self._raw = raw

    @property
    def available(self) -> bool:
        return True

    def capture_frontmost(
        self,
        *,
        focused_window_only: bool = True,
        anchor_hwnd: int = 0,
        anchor_pid: int = 0,
    ) -> AXCaptureResult | None:
        return self._run(
            all_visible=False,
            focused_window_only=focused_window_only,
            anchor_hwnd=anchor_hwnd,
            anchor_pid=anchor_pid,
        )

    def capture_all_visible(self) -> AXCaptureResult | None:
        return self._run(all_visible=True)

    def capture_app(
        self, app_name: str, *, focused_window_only: bool = True
    ) -> AXCaptureResult | None:
        return self._run(
            all_visible=False, app_name=app_name, focused_window_only=focused_window_only
        )

    def _run(
        self,
        *,
        all_visible: bool,
        app_name: str | None = None,
        focused_window_only: bool = False,
        anchor_hwnd: int = 0,
        anchor_pid: int = 0,
    ) -> AXCaptureResult | None:
        args: list[str] = [
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile",
            "-File", self._script_path,
        ]
        if app_name:
            args.extend(["-AppName", app_name])
        elif all_visible:
            args.append("-AllVisible")
        if focused_window_only:
            args.append("-FocusedWindowOnly")
        if self._raw:
            args.append("-Raw")
        args.extend(["-Depth", str(self._depth)])

        # Anchor the helper to the user's foreground window. Required
        # because the helper subprocess runs in a session-isolated state
        # (no console, no desktop access — see Windows session/desktop
        # isolation rules) where its own GetForegroundWindow / UIA
        # FocusedElement always return zero.
        #
        # Source priority:
        #   1. Caller-supplied anchor (anchor_hwnd / anchor_pid) — comes
        #      from the watcher event that triggered this capture, so
        #      it's the *exact* HWND that fired the event.
        #   2. Daemon-process GetForegroundWindow — usable for heartbeat
        #      captures or whenever no triggering event exists.
        #
        # mac's NSWorkspace.frontmostApplication is the moral equivalent;
        # it just doesn't need the explicit hand-off because the helper
        # has its own desktop access there.
        if not all_visible and not app_name:
            hwnd, pid = anchor_hwnd, anchor_pid
            if not hwnd:
                hwnd, pid = _foreground_hwnd_pid()
            if hwnd:
                args.extend(["-ForegroundHwnd", str(hwnd)])
                args.extend(["-ForegroundPid", str(pid)])

        # CREATE_NO_WINDOW: when the daemon runs detached (no console of
        # its own), every subprocess.run that launches powershell.exe
        # would otherwise be given a fresh console window — visible as
        # a black cmd window flashing on every capture event. The flag
        # is Windows-only; getattr keeps the import portable.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=_WIN_SUBPROCESS_TIMEOUT,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired:
            logger.warning("win-uia-helper timed out after %ds", _WIN_SUBPROCESS_TIMEOUT)
            return None
        except OSError as exc:
            logger.error("Failed to run win-uia-helper: %s", exc)
            return None

        if proc.returncode != 0:
            logger.warning(
                "win-uia-helper exited %d: %s", proc.returncode, proc.stderr.strip()[:200]
            )
            return None

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse win-uia-helper JSON: %s", exc)
            return None

        data = _strip_frame_fields(data)
        mode = "all-visible" if all_visible else "frontmost"
        return AXCaptureResult(
            raw_json=data,
            timestamp=data.get("timestamp", ""),
            apps=data.get("apps", []),
            metadata={"mode": mode, "depth": self._depth, "platform": "windows", "raw": self._raw},
        )


def _resolve_win_helper_path() -> Path | None:
    """Find the win-uia-helper.ps1 script."""
    override = os.environ.get("OPENCHRONICLE_WIN_UIA_HELPER")
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file():
            return p
        logger.warning("OPENCHRONICLE_WIN_UIA_HELPER set but not found: %s", p)

    candidates: list[Path] = []

    try:
        from importlib.resources import files as _pkg_files

        bundled_dir = Path(str(_pkg_files("openchronicle").joinpath("_bundled")))
        candidates.append(bundled_dir / "win-uia-helper.ps1")
    except (ModuleNotFoundError, ValueError):
        pass

    dev_root = Path(__file__).resolve().parents[3]
    candidates.append(dev_root / "resources" / "win-uia-helper.ps1")

    for p in candidates:
        if p.is_file():
            return p

    return None


def create_provider(*, depth: int = 8, timeout: int = 3, raw: bool = False) -> AXProvider:
    system = platform.system()
    if system == "Darwin":
        helper = _resolve_helper_path()
        if helper is None:
            return UnavailableAXProvider(
                "mac-ax-helper not found. Build it: bash resources/build-mac-ax-helper.sh"
            )
        logger.info("AX capture initialized (macOS): %s", helper)
        return MacAXHelperProvider(helper_path=helper, depth=depth, timeout=timeout, raw=raw)
    if system == "Windows":
        script = _resolve_win_helper_path()
        if script is None:
            return UnavailableAXProvider(
                "win-uia-helper.ps1 not found. Reinstall OpenChronicle."
            )
        logger.info("UI Automation capture initialized (Windows): %s", script)
        return WinUIAutomationProvider(script_path=script, depth=depth, timeout=timeout, raw=raw)
    return UnavailableAXProvider(f"unsupported platform: {system}")
