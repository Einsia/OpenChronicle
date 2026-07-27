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
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logger import get
from .signal_store import SignalStore

logger = get("openchronicle.capture")

_IMMEDIATE_EVENTS = {
    "AXFocusedWindowChanged",
    "AXApplicationActivated",
    "UserMouseClick",
    "UserTextInput",
}
_DEBOUNCED_EVENTS = {"AXValueChanged"}
_SKIP_EVENTS = {"AXTitleChanged"}
_SAFE_ELEMENT_FIELDS = ("role", "subrole", "identifier")
_NO_FOLLOWUP_STATUSES = {
    "new",
    "privacy_blocked",
    "app_changed",
    "permission_denied",
    "screen_locked",
}
_RETRYABLE_STATUSES = {
    "reused",
    "unchanged",
    "deferred_queue_full",
    "ax_incomplete",
    "capture_unavailable",
}
_RETRYABLE_DEGRADED_REASONS = {
    "ax_incomplete",
    "capture_unavailable",
    "duplicate_without_ref",
    "queue_full",
    "temporary_capture_error",
}


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="milliseconds")


@dataclass
class _CaptureGroup:
    capture_request_id: str
    key: tuple[str, int, str]
    bundle_id: str
    pid: int
    window_identity: str
    window_identity_confidence: str
    created_at: str
    due_at: str
    member_signal_ids: list[str] = field(default_factory=list)
    timer: threading.Timer | None = None
    running: bool = False
    phase: str = "primary"
    attempt_id: str | None = None
    natural_attempted: bool = False


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
        signal_store: SignalStore | None = None,
        context_snapshot_ref_fn: Callable[[str], str | None] | None = None,
        enter_capture_delay_seconds: float = 0.2,
        # Sample after the documented 800ms update boundary rather than
        # exactly on it, avoiding a race with UI work scheduled for T+800ms.
        enter_followup_delay_seconds: float | None = 1.0,
        debounce_seconds: float = 3.0,
        min_capture_gap_seconds: float = 2.0,
        dedup_interval_seconds: float = 1.0,
        same_window_dedup_seconds: float = 5.0,
    ) -> None:
        self._capture_fn = capture_fn
        self._signal_store = signal_store
        self._context_snapshot_ref_fn = context_snapshot_ref_fn
        self._enter_capture_delay = enter_capture_delay_seconds
        self._enter_followup_delay = enter_followup_delay_seconds
        self._debounce_seconds = debounce_seconds
        self._min_capture_gap = min_capture_gap_seconds
        self._dedup_interval = dedup_interval_seconds
        self._same_window_dedup = same_window_dedup_seconds

        self._lock = threading.Lock()
        self._debounce_timer: threading.Timer | None = None
        self._enter_timers: set[threading.Timer] = set()
        self._active_groups: dict[tuple[str, int, str], _CaptureGroup] = {}
        self._waiting_groups: dict[tuple[str, int, str], _CaptureGroup] = {}
        self._draining = False
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
        bundle_id = str(raw.get("bundle_id") or "")
        if self._signal_store and self._signal_store.is_excluded_bundle(bundle_id):
            return
        if self._draining:
            return
        if event_type == "UserEnter":
            self._handle_user_enter(raw)
            return
        if (
            event_type == "UserTextInput"
            and self._signal_store is not None
            and not self._signal_store.create_user_text_input(raw).created
        ):
            return
        if event_type == "AXValueChanged" and self._try_natural_enter_capture(raw):
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
        event_id = raw.get("event_id")
        if isinstance(event_id, str) and 0 < len(event_id) <= 128:
            trigger["event_id"] = event_id
        correlation_id = raw.get("correlation_id")
        if isinstance(correlation_id, str) and 0 < len(correlation_id) <= 128:
            trigger["correlation_id"] = correlation_id
        related_signal_id = raw.get("related_signal_id")
        if isinstance(related_signal_id, str) and 0 < len(related_signal_id) <= 128:
            trigger["related_signal_id"] = related_signal_id
        details = raw.get("details")
        if isinstance(details, dict):
            safe_details: dict[str, Any] = {}
            if isinstance(details.get("reason"), str):
                safe_details["reason"] = details["reason"][:80]
            if isinstance(details.get("button"), int):
                safe_details["button"] = details["button"]
            element = details.get("element")
            if isinstance(element, dict):
                safe_element = {
                    key: str(element[key])[:200] for key in _SAFE_ELEMENT_FIELDS if element.get(key)
                }
                if safe_element:
                    safe_details["element"] = safe_element
            if safe_details:
                trigger["details"] = safe_details

        if event_type in _IMMEDIATE_EVENTS:
            self._cancel_debounce()
            self._maybe_capture(trigger)
        elif event_type in _DEBOUNCED_EVENTS:
            self._schedule_debounce(trigger)

    def _handle_user_enter(self, raw: dict[str, Any]) -> None:
        """Persist Enter, then coalesce its conditional Capture request."""
        if self._signal_store is None:
            logger.warning("UserEnter ignored: signal store unavailable")
            return
        raw = dict(raw)
        if self._context_snapshot_ref_fn is not None:
            raw.setdefault(
                "context_snapshot_ref",
                self._context_snapshot_ref_fn(str(raw.get("bundle_id") or "")),
            )
        raw.setdefault(
            "correlation_deadline",
            (
                datetime.now(UTC).astimezone()
                + timedelta(seconds=max(10.0, (self._enter_followup_delay or 0) + 1.0))
            ).isoformat(timespec="milliseconds"),
        )
        result = self._signal_store.create_user_enter(raw)
        if not result.created:
            return

        bundle_id = str(raw.get("bundle_id") or "")[:300]
        pid = raw.get("pid") if isinstance(raw.get("pid"), int) else 0
        window_identity = str(raw.get("window_identity") or f"{bundle_id}:{pid}")[:200]
        confidence = str(raw.get("window_identity_confidence") or "low")
        key = (bundle_id, pid, window_identity)
        with self._lock:
            active = self._active_groups.get(key)
            if active is None:
                group = self._new_group(
                    key, bundle_id, pid, window_identity, confidence, self._enter_capture_delay
                )
                group.member_signal_ids.append(result.signal_id)
                self._active_groups[key] = group
                self._schedule_group_locked(group, self._enter_capture_delay)
            elif not active.running and active.phase == "primary":
                active.member_signal_ids.append(result.signal_id)
                group = active
            else:
                group = self._waiting_groups.get(key)
                if group is None:
                    group = self._new_group(
                        key,
                        bundle_id,
                        pid,
                        window_identity,
                        confidence,
                        self._enter_capture_delay,
                    )
                    self._waiting_groups[key] = group
                group.member_signal_ids.append(result.signal_id)

        self._signal_store.update_linkage(
            result.signal_id,
            capture_request_id=group.capture_request_id,
        )

    def recover_signal(self, signal: dict[str, Any]) -> bool:
        """Schedule one conservative startup recovery for a V2 Signal."""
        if self._signal_store is None:
            return False
        signal_id = str(signal.get("signal_id") or "")
        deadline_text = str(signal.get("correlation_deadline") or "")
        try:
            deadline = datetime.fromisoformat(deadline_text)
        except ValueError:
            deadline = datetime.min.replace(tzinfo=UTC)
        confidence = str(signal.get("window_identity_confidence") or "low")
        if deadline <= datetime.now(UTC).astimezone() or confidence != "high":
            reason = "recovery_expired" if deadline_text and deadline <= datetime.now(
                UTC
            ).astimezone() else "context_changed"
            self._signal_store.update_linkage(
                signal_id,
                attempt={
                    "attempt_id": f"att-{uuid.uuid4().hex}",
                    "phase": "recovery",
                    "association_mode": "recovery",
                    "status": "unresolved",
                    "completed_at": _now_iso(),
                    "bundle_id": signal.get("bundle_id"),
                    "window_identity": signal.get("window_identity"),
                    "window_identity_confidence": confidence,
                    "quality_status": "failed",
                    "error_reason": reason,
                },
                post_capture_status="unresolved",
                quality_status="failed",
            )
            return False

        bundle_id = str(signal.get("bundle_id") or "")
        pid = signal.get("pid") if isinstance(signal.get("pid"), int) else 0
        window_identity = str(signal.get("window_identity") or "")
        key = (bundle_id, pid, window_identity)
        group = self._new_group(
            key,
            bundle_id,
            pid,
            window_identity,
            confidence,
            0,
        )
        group.phase = "recovery"
        group.member_signal_ids.append(signal_id)
        with self._lock:
            if key in self._active_groups:
                return False
            self._active_groups[key] = group
            self._schedule_group_locked(group, 0)
        return True

    def _new_group(
        self,
        key: tuple[str, int, str],
        bundle_id: str,
        pid: int,
        window_identity: str,
        confidence: str,
        delay: float,
    ) -> _CaptureGroup:
        now = datetime.now(UTC).astimezone()
        return _CaptureGroup(
            capture_request_id=f"cap-{uuid.uuid4().hex}",
            key=key,
            bundle_id=bundle_id,
            pid=pid,
            window_identity=window_identity,
            window_identity_confidence=confidence,
            created_at=now.isoformat(timespec="milliseconds"),
            due_at=(now + timedelta(seconds=delay)).isoformat(timespec="milliseconds"),
        )

    def _try_natural_enter_capture(self, raw: dict[str, Any]) -> bool:
        bundle_id = str(raw.get("bundle_id") or "")
        pid = raw.get("pid") if isinstance(raw.get("pid"), int) else 0
        with self._lock:
            candidates = [
                group
                for group in self._active_groups.values()
                if group.bundle_id == bundle_id
                and group.pid == pid
                and group.phase == "follow_up"
                and not group.running
                and not group.natural_attempted
            ]
            if len(candidates) != 1:
                return False
            group = candidates[0]
            if group.timer is not None:
                group.timer.cancel()
                self._enter_timers.discard(group.timer)
            group.natural_attempted = True
            group.phase = "natural_event"
            self._schedule_group_locked(group, 0)
            return True

    def _schedule_group_locked(self, group: _CaptureGroup, delay: float) -> None:
        timer = threading.Timer(delay, self._run_group, args=(group,))
        timer.daemon = True
        group.timer = timer
        self._enter_timers.add(timer)
        timer.start()

    def _run_group(self, group: _CaptureGroup) -> None:
        with self._lock:
            if self._draining:
                self._enter_timers.discard(group.timer)
                return
            group.running = True
            member_ids = tuple(group.member_signal_ids)
            group.attempt_id = f"att-{uuid.uuid4().hex}"
            self._enter_timers.discard(group.timer)

        requested_at = _now_iso()
        attempt = {
            "attempt_id": group.attempt_id,
            "capture_request_id": group.capture_request_id,
            "phase": group.phase,
            "association_mode": "coalesced" if len(member_ids) > 1 else "direct",
            "requested_at": requested_at,
            "due_at": group.due_at,
            "started_at": requested_at,
            "bundle_id": group.bundle_id,
            "window_identity": group.window_identity,
            "window_identity_confidence": group.window_identity_confidence,
            "status": "running",
        }
        for signal_id in member_ids:
            self._signal_store.update_linkage(
                signal_id,
                attempt=attempt,
                capture_request_id=group.capture_request_id,
                post_capture_status="running" if group.phase == "primary" else None,
            )

        trigger = {
            "event_type": "UserEnter",
            "signal_id": member_ids[0],
            "member_signal_ids": list(member_ids),
            "capture_request_id": group.capture_request_id,
            "attempt_id": group.attempt_id,
            "enter_attempt": "initial" if group.phase == "primary" else group.phase,
            "phase": group.phase,
            "pid": group.pid,
            "bundle_id": group.bundle_id,
            "window_identity": group.window_identity,
            "window_identity_confidence": group.window_identity_confidence,
            "window_title": "",
            "_capture_complete": lambda outcome: self._complete_group(group, member_ids, outcome),
        }
        try:
            self._capture_fn(trigger)
        except Exception as exc:  # noqa: BLE001
            self._complete_group(
                group,
                member_ids,
                {
                    "status": "unresolved",
                    "quality_status": "failed",
                    "error_reason": type(exc).__name__,
                },
            )

    def _complete_group(
        self,
        group: _CaptureGroup,
        member_ids: tuple[str, ...],
        outcome: dict[str, Any],
    ) -> None:
        attempt_status = str(outcome.get("status") or "unresolved")
        status = attempt_status
        if attempt_status in {"capture_unavailable", "ax_incomplete"}:
            status = "pending" if group.phase == "primary" else "unresolved"
        if status == "deferred_queue_full" and group.phase in {
            "follow_up",
            "recovery",
        }:
            status = "unresolved"
            outcome = {**outcome, "error_reason": "queue_full_exhausted"}
        quality = str(outcome.get("quality_status") or "failed")
        snapshot_ref = outcome.get("snapshot_ref")
        context_snapshot_ref = outcome.get("context_snapshot_ref")
        completed_at = _now_iso()
        attempt = {
            "attempt_id": group.attempt_id,
            "capture_request_id": group.capture_request_id,
            "phase": group.phase,
            "association_mode": (
                "coalesced"
                if len(member_ids) > 1
                else ("reused" if status in {"reused", "unchanged"} else "direct")
            ),
            "completed_at": completed_at,
            "bundle_id": group.bundle_id,
            "window_identity": group.window_identity,
            "window_identity_confidence": group.window_identity_confidence,
            "status": attempt_status,
            "snapshot_ref": snapshot_ref,
            "quality_status": quality,
            "error_reason": outcome.get("error_reason"),
        }
        for signal_id in member_ids:
            self._signal_store.update_linkage(
                signal_id,
                attempt=attempt,
                post_capture_status=status,
                quality_status=quality,
                result_snapshot_ref=snapshot_ref,
                context_snapshot_ref=context_snapshot_ref,
                capture_request_id=group.capture_request_id,
            )

        should_follow_up = (
            group.phase == "primary"
            and self._enter_followup_delay is not None
            and (
                attempt_status in _RETRYABLE_STATUSES
                or (
                    quality == "degraded"
                    and outcome.get("error_reason") in _RETRYABLE_DEGRADED_REASONS
                )
            )
            and status not in _NO_FOLLOWUP_STATUSES
        )
        natural_event_failed = (
            group.phase == "natural_event"
            and (
                attempt_status in _RETRYABLE_STATUSES
                or (
                    quality == "degraded"
                    and outcome.get("error_reason") in _RETRYABLE_DEGRADED_REASONS
                )
            )
            and status not in _NO_FOLLOWUP_STATUSES
        )
        with self._lock:
            group.running = False
            if (should_follow_up or natural_event_failed) and not self._draining:
                group.phase = "follow_up"
                group.due_at = (
                    datetime.now(UTC).astimezone()
                    + timedelta(seconds=self._enter_followup_delay or 0)
                ).isoformat(timespec="milliseconds")
                self._schedule_group_locked(group, self._enter_followup_delay or 0)
                return
            self._active_groups.pop(group.key, None)
            waiting = self._waiting_groups.pop(group.key, None)
            if waiting is not None and not self._draining:
                self._active_groups[group.key] = waiting
                self._schedule_group_locked(waiting, self._enter_capture_delay)

    def _prune_event_times(self, now: float) -> None:
        cutoff = now - self._dedup_interval
        self._last_event_time = {k: t for k, t in self._last_event_time.items() if t >= cutoff}

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
                    self._same_window_dedup,
                    trigger["window_title"][:40],
                )
                return

            gap = now - self._last_capture_monotonic
            if gap < self._min_capture_gap and not is_focus_change:
                logger.debug("capture skipped (rate limit %.1fs): %s", gap, event_type)
                return

            self._last_capture_key = key
            self._last_capture_monotonic = now

        try:
            self._capture_fn(trigger)
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture callback failed: %s", exc)

    def shutdown(self) -> None:
        self._draining = True
        self._cancel_debounce()
        with self._lock:
            timers = list(self._enter_timers)
            self._enter_timers.clear()
        for timer in timers:
            timer.cancel()
        if self._signal_store is not None:
            self._signal_store.defer_pending_for_shutdown()
