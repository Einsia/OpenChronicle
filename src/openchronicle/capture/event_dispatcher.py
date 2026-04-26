"""Classifies AX watcher events and triggers captures.

Inspired by Einsia-Partner's S0/S1 collector pipeline, collapsed into a single
dispatcher that writes one JSON per semantic event into the capture buffer.

Classification rules:
  AXFocusedWindowChanged   → immediate capture
  AXApplicationActivated   → immediate capture
  UserMouseClick           → immediate capture
  UserTextInput            → immediate capture (Swift already debounced typing)
  AXValueChanged           → debounced capture (3s)
  AXTitleChanged           → skip (too noisy, covered by window/app events)

Additional guards:
  * Same-app-same-window dedup: skip a non-focus-change capture if the last
    capture in the same bundle+window happened less than
    ``same_window_dedup_seconds`` ago. Focus changes always pass.
  * Rate limit: sequentialize captures and enforce a minimum gap so bursts
    of events (e.g. a rapid click → value change → focus change) don't
    write 5 frames in 200ms.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..logger import get

logger = get("openchronicle.capture")

_IMMEDIATE_EVENTS = {
    "AXFocusedWindowChanged",
    "AXApplicationActivated",
    "UserMouseClick",
    "UserTextInput",
}
_DEBOUNCED_EVENTS = {"AXValueChanged"}
_SKIP_EVENTS = {"AXTitleChanged"}


class EventDispatcher:
    """Consumes watcher events and invokes a capture callback.

    ``capture_fn`` should be idempotent and safe to call from this thread.
    It will be called with a kwarg ``trigger`` carrying the event metadata
    (event_type / bundle_id / window_title) so captures can be logged.
    """

    def __init__(
        self,
        capture_fn: Callable[[dict[str, Any]], None],
        *,
        debounce_seconds: float = 3.0,
        min_capture_gap_seconds: float = 2.0,
        dedup_interval_seconds: float = 1.0,
        same_window_dedup_seconds: float = 5.0,
    ) -> None:
        self._capture_fn = capture_fn
        self._debounce_seconds = debounce_seconds
        self._min_capture_gap = min_capture_gap_seconds
        self._dedup_interval = dedup_interval_seconds
        self._same_window_dedup = same_window_dedup_seconds

        self._lock = threading.Lock()
        self._debounce_timer: threading.Timer | None = None
        self._pending_trigger: dict[str, Any] | None = None

        # Tuple keys avoid the silent collision a delimited-string key has
        # whenever bundle_id or window_title contains the delimiter (e.g.
        # a window titled "App: Untitled" colliding with "App" + ": Untitled").
        self._last_event_time: dict[tuple[str, str, str], float] = {}
        self._last_capture_key: tuple[str, str] = ("", "")
        self._last_capture_monotonic: float = 0.0

    # Periodically prune entries that can no longer suppress dedup so the
    # map can't grow forever as the user visits many distinct windows.
    _PRUNE_EVERY: int = 256

    def on_event(self, raw: dict[str, Any]) -> None:
        """Watcher callback. Classifies the event and (maybe) triggers capture."""
        event_type = raw.get("event_type", "")
        if not event_type or event_type in _SKIP_EVENTS:
            return

        bundle_id = raw.get("bundle_id", "") or ""
        window_title = raw.get("window_title", "") or ""
        dedup_key = (event_type, bundle_id, window_title)

        now = time.monotonic()
        last = self._last_event_time.get(dedup_key, 0.0)
        if now - last < self._dedup_interval:
            return
        self._last_event_time[dedup_key] = now
        if len(self._last_event_time) >= self._PRUNE_EVERY:
            self._prune_event_times(now)

        trigger = {
            "event_type": event_type,
            "bundle_id": bundle_id,
            "window_title": window_title,
        }

        if event_type in _IMMEDIATE_EVENTS:
            self._cancel_debounce()
            self._maybe_capture(trigger)
        elif event_type in _DEBOUNCED_EVENTS:
            self._schedule_debounce(trigger)

    def _prune_event_times(self, now: float) -> None:
        cutoff = now - self._dedup_interval
        self._last_event_time = {
            k: t for k, t in self._last_event_time.items() if t >= cutoff
        }

    def _schedule_debounce(self, trigger: dict[str, Any]) -> None:
        with self._lock:
            self._pending_trigger = trigger
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            t = threading.Timer(self._debounce_seconds, self._flush_debounce)
            t.daemon = True
            self._debounce_timer = t
            t.start()

    def _cancel_debounce(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
            self._pending_trigger = None

    def _flush_debounce(self) -> None:
        with self._lock:
            trigger = self._pending_trigger
            self._pending_trigger = None
            self._debounce_timer = None
        if trigger is not None:
            self._maybe_capture(trigger)

    def _maybe_capture(self, trigger: dict[str, Any]) -> None:
        """Apply last-frame dedup + rate limit, then invoke the capture fn."""
        event_type = trigger["event_type"]
        key = (trigger["bundle_id"], trigger["window_title"])
        now = time.monotonic()
        is_focus_change = event_type in (
            "AXFocusedWindowChanged",
            "AXApplicationActivated",
        )

        # Decide-and-commit under the lock: this method is called from both the
        # watcher reader thread (immediate events) and the debounce Timer
        # thread, so reading then writing _last_capture_* without serialization
        # races and lets two near-simultaneous events bypass dedup/rate-limit.
        # Keep _capture_fn outside the lock so a slow callback can't stall the
        # other thread.
        with self._lock:
            if (
                not is_focus_change
                and key == self._last_capture_key
                and (now - self._last_capture_monotonic) < self._same_window_dedup
            ):
                logger.debug(
                    "capture skipped (same-window dedup <%.1fs): %s",
                    self._same_window_dedup, trigger["window_title"][:40],
                )
                return

            gap = now - self._last_capture_monotonic
            if gap < self._min_capture_gap and not is_focus_change:
                logger.debug(
                    "capture skipped (rate limit %.1fs): %s", gap, event_type
                )
                return

            self._last_capture_key = key
            self._last_capture_monotonic = now

        try:
            self._capture_fn(trigger)
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture callback failed: %s", exc)

    def shutdown(self) -> None:
        self._cancel_debounce()
