"""Long-running event watcher — cross-platform.

macOS: vendored ``mac-ax-watcher`` Swift binary (subprocess, JSONL on stdout)
Windows: in-process thread using SetWinEventHook + low-level input hooks

Both implementations share the same public interface:
  .available, .running, .on_event(callback), .start(), .stop()

Use ``create_watcher()`` to get the right implementation for the current OS.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ..logger import get
from .ax_capture import _maybe_compile

logger = get("openchronicle.capture")


class EventWatcher(Protocol):
    """Common interface implemented by both macOS and Windows watchers."""

    @property
    def available(self) -> bool: ...

    @property
    def running(self) -> bool: ...

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None: ...

    def start(self) -> None: ...

    def stop(self, *, join_timeout: float = 5.0) -> None: ...


def _resolve_watcher_path() -> Path | None:
    """Find or build the mac-ax-watcher binary.

    Search order mirrors ax_capture._resolve_helper_path:
      1. OPENCHRONICLE_AX_WATCHER env var
      2. Packaged resource shipped with the wheel (_bundled/)
      3. Dev source tree (OpenChronicle/resources/)
    """
    if platform.system() != "Darwin":
        return None

    override = os.environ.get("OPENCHRONICLE_AX_WATCHER")
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file() and os.access(p, os.X_OK):
            return p
        logger.warning("OPENCHRONICLE_AX_WATCHER set but not executable: %s", p)

    candidates: list[Path] = []
    try:
        from importlib.resources import files as _pkg_files

        bundled_dir = Path(str(_pkg_files("openchronicle").joinpath("_bundled")))
        candidates.append(bundled_dir / "mac-ax-watcher")
    except (ModuleNotFoundError, ValueError):
        pass

    dev_root = Path(__file__).resolve().parents[3]
    candidates.append(dev_root / "resources" / "mac-ax-watcher")

    for binary_path in candidates:
        swift_path = binary_path.with_suffix(".swift")
        if swift_path.is_file():
            _maybe_compile(swift_path, binary_path)
        if binary_path.is_file() and os.access(binary_path, os.X_OK):
            return binary_path

    return None


class AXWatcherProcess:
    """Owns the mac-ax-watcher subprocess and a reader thread.

    Thread safety: ``start`` / ``stop`` may be called from any thread.
    The callback runs on the reader thread — keep it fast and thread-safe.
    """

    def __init__(self, *, max_reconnect_delay: float = 60.0) -> None:
        self._watcher_path = _resolve_watcher_path()
        self._callback: Callable[[dict[str, Any]], None] | None = None
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._max_reconnect_delay = max_reconnect_delay

    @property
    def available(self) -> bool:
        return self._watcher_path is not None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def on_event(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        if not self._watcher_path:
            logger.warning("AX watcher not available (not macOS or binary not found)")
            return
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ax-watcher-reader"
        )
        self._reader_thread.start()
        logger.info("AX watcher started: %s", self._watcher_path)

    def stop(self, *, join_timeout: float = 5.0) -> None:
        """Stop the subprocess and join the reader thread.

        Closing ``stdout`` is necessary because the reader loop is blocked
        on a line read; otherwise ``join`` would hang for the full
        ``join_timeout`` even after the process is dead.
        """
        self._stop_event.set()
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=join_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=1.0)
        if proc and proc.stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                proc.stdout.close()
        self._process = None

        reader = self._reader_thread
        if reader is not None and reader.is_alive():
            reader.join(timeout=join_timeout)
            if reader.is_alive():
                logger.warning(
                    "AX watcher reader thread did not exit within %.1fs", join_timeout
                )
        self._reader_thread = None
        logger.info("AX watcher stopped")

    def _run_loop(self) -> None:
        delay = 1.0
        while not self._stop_event.is_set():
            try:
                self._start_process()
                if self._process is None:
                    break
                self._read_events()
            except Exception as exc:  # noqa: BLE001
                logger.warning("AX watcher error: %s", exc)

            if self._stop_event.is_set():
                break

            logger.info("AX watcher exited, reconnecting in %.0fs", delay)
            self._stop_event.wait(delay)
            delay = min(delay * 2, self._max_reconnect_delay)

    def _start_process(self) -> None:
        if not self._watcher_path:
            return
        try:
            self._process = subprocess.Popen(
                [str(self._watcher_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            logger.info("AX watcher subprocess started (pid=%d)", self._process.pid)
        except OSError as exc:
            logger.error("Failed to start AX watcher: %s", exc)
            self._process = None

    def _read_events(self) -> None:
        if not self._process or not self._process.stdout:
            return

        for line in self._process.stdout:
            if self._stop_event.is_set():
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Invalid JSON from watcher: %s", line[:100])
                continue
            if event.get("event_type", "").startswith("_"):
                logger.debug("Watcher internal event: %s", event.get("event_type"))
                continue
            if self._callback:
                try:
                    self._callback(event)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Event callback error: %s", exc)

        if self._process:
            rc = self._process.wait()
            if rc == 2:
                logger.error("Accessibility permission not granted — watcher won't restart")
                self._stop_event.set()
            elif rc != 0:
                logger.warning("AX watcher exited with code %d", rc)


def create_watcher() -> EventWatcher:
    """Factory: return the appropriate watcher for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return AXWatcherProcess()
    if system == "Windows":
        from .win_watcher import WinWatcherThread

        return WinWatcherThread()
    logger.warning("No event watcher available for platform: %s", system)
    return AXWatcherProcess()  # will be unavailable on non-Darwin
