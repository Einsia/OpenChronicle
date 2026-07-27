"""Durable, privacy-minimized storage for physical interaction signals."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..logger import get

logger = get("openchronicle.capture")

SIGNAL_SCHEMA_VERSION = 2
CAPTURE_SCHEMA_VERSION = 2
PRIVACY_POLICY_VERSION = 1
EVENT_SCHEMA_VERSION = 1

_SAFE_TARGET_FIELDS = ("role", "subrole", "identifier")
_SAFE_MODIFIERS = {"shift", "command", "control", "option"}
_SAFE_KEY_VARIANTS = {"return", "keypad_enter"}
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SUCCESS_STATES = {"new", "reused", "unchanged"}
_TERMINAL_STATES = _SUCCESS_STATES | {
    "unresolved",
    "app_changed",
    "privacy_blocked",
}
_DEFERRED_STATES = {"pending", "running", "deferred_queue_full", "deferred_shutdown"}


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class SignalCreateResult:
    created: bool
    signal_id: str
    path: Path | None = None


@dataclass(frozen=True)
class EventCreateResult:
    created: bool
    event_id: str
    path: Path | None = None


@dataclass(frozen=True)
class LinkageUpdateResult:
    updated: bool
    signal_id: str
    revision: int | None = None
    status: str | None = None


def _sanitize_identifier(value: Any) -> str:
    identifier = str(value or "")
    if not identifier or len(identifier) > 128 or _CONTROL_CHARACTERS.search(identifier):
        return ""
    # Identifiers should be structural labels, not dynamic user content.
    if len(identifier.split()) > 8 or "\n" in identifier or "\r" in identifier:
        return ""
    return identifier


def sanitize_user_enter(
    raw: dict[str, Any],
    *,
    excluded_bundle_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return the allowlisted V2 UserEnter representation, or ``None``."""
    if raw.get("event_type") != "UserEnter":
        return None

    signal_id = str(raw.get("signal_id") or "").strip()
    if not _SAFE_ID.fullmatch(signal_id):
        return None

    bundle_id = str(raw.get("bundle_id") or "")[:300]
    if bundle_id and bundle_id in (excluded_bundle_ids or set()):
        return None

    target = raw.get("input_target")
    safe_target: dict[str, str] | None = None
    if isinstance(target, dict):
        candidate: dict[str, str] = {}
        for key in _SAFE_TARGET_FIELDS:
            if not target.get(key):
                continue
            value = (
                _sanitize_identifier(target[key])
                if key == "identifier"
                else str(target[key])[:80]
            )
            if value:
                candidate[key] = value
        if candidate:
            safe_target = candidate

    status = str(raw.get("input_target_status") or "")
    if status not in {"available", "ax_unavailable", "secure_input", "app_unavailable"}:
        status = "available" if safe_target else "ax_unavailable"
    if status == "secure_input":
        safe_target = None

    key_variant = str(raw.get("key_variant") or "")
    if key_variant not in _SAFE_KEY_VARIANTS:
        key_variant = "return"
    modifiers = raw.get("modifiers")
    safe_modifiers = (
        [str(item) for item in modifiers if str(item) in _SAFE_MODIFIERS]
        if isinstance(modifiers, list)
        else []
    )
    pid = raw.get("pid")
    safe_pid = pid if isinstance(pid, int) and pid >= 0 else 0
    correlation_id = str(raw.get("correlation_id") or signal_id)
    if not _SAFE_ID.fullmatch(correlation_id):
        correlation_id = signal_id
    window_identity = str(raw.get("window_identity") or "")[:200]
    window_confidence = str(raw.get("window_identity_confidence") or "low")
    if window_confidence not in {"high", "medium", "low"}:
        window_confidence = "low"

    return {
        "signal_schema_version": SIGNAL_SCHEMA_VERSION,
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "signal_id": signal_id,
        "correlation_id": correlation_id,
        "event_type": "UserEnter",
        "timestamp": str(raw.get("timestamp") or "")[:80],
        "pid": safe_pid,
        "app_name": str(raw.get("app_name") or "")[:200],
        "bundle_id": bundle_id,
        "key_variant": key_variant,
        "modifiers": safe_modifiers,
        "input_target": safe_target,
        "input_target_status": status,
        "window_identity": window_identity,
        "window_identity_confidence": window_confidence,
        "semantic_intent": "unknown",
        "context_snapshot_ref": raw.get("context_snapshot_ref"),
        "result_snapshot_ref": None,
        "post_capture_status": "pending",
        "quality_status": None,
        "capture_request_id": None,
        "capture_attempts": [],
        "correlation_deadline": raw.get("correlation_deadline"),
        "revision": 1,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def sanitize_user_text_input(
    raw: dict[str, Any],
    *,
    excluded_bundle_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return a relationship-only UserTextInput event without typed content."""
    if raw.get("event_type") != "UserTextInput":
        return None
    event_id = str(raw.get("event_id") or "").strip()
    correlation_id = str(raw.get("correlation_id") or "").strip()
    related_signal_id = str(raw.get("related_signal_id") or "").strip()
    if not all(
        _SAFE_ID.fullmatch(value)
        for value in (event_id, correlation_id, related_signal_id)
    ):
        return None
    bundle_id = str(raw.get("bundle_id") or "")[:300]
    if bundle_id and bundle_id in (excluded_bundle_ids or set()):
        return None
    details = raw.get("details")
    safe_details: dict[str, Any] = {}
    if isinstance(details, dict):
        reason = str(details.get("reason") or "")[:80]
        if reason:
            safe_details["reason"] = reason
        element = details.get("element")
        if isinstance(element, dict):
            safe_element: dict[str, str] = {}
            for key in _SAFE_TARGET_FIELDS:
                if not element.get(key):
                    continue
                value = (
                    _sanitize_identifier(element[key])
                    if key == "identifier"
                    else str(element[key])[:80]
                )
                if value:
                    safe_element[key] = value
            if safe_element:
                safe_details["element"] = safe_element
    return {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "event_id": event_id,
        "event_type": "UserTextInput",
        "correlation_id": correlation_id,
        "related_signal_id": related_signal_id,
        "timestamp": str(raw.get("timestamp") or "")[:80],
        "pid": raw.get("pid") if isinstance(raw.get("pid"), int) else 0,
        "app_name": str(raw.get("app_name") or "")[:200],
        "bundle_id": bundle_id,
        "details": safe_details,
        "created_at": _now_iso(),
    }


class SignalStore:
    """Atomic, idempotent V2 JSON store keyed by watcher ``signal_id``."""

    def __init__(self, *, excluded_bundle_ids: set[str] | None = None) -> None:
        self._excluded_bundle_ids = excluded_bundle_ids or set()
        self._locks_guard = threading.Lock()
        self._signal_locks: dict[str, threading.RLock] = {}

    @property
    def excluded_bundle_ids(self) -> frozenset[str]:
        return frozenset(self._excluded_bundle_ids)

    def is_excluded_bundle(self, bundle_id: str) -> bool:
        return bool(bundle_id and bundle_id in self._excluded_bundle_ids)

    def _signal_lock(self, signal_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._signal_locks.setdefault(signal_id, threading.RLock())

    def create_user_enter(self, raw: dict[str, Any]) -> SignalCreateResult:
        signal = sanitize_user_enter(raw, excluded_bundle_ids=self._excluded_bundle_ids)
        if signal is None:
            return SignalCreateResult(False, str(raw.get("signal_id") or ""))

        paths.ensure_dirs()
        signal_id = signal["signal_id"]
        target = paths.signal_buffer_dir() / f"{signal_id}.json"
        with self._signal_lock(signal_id):
            if target.exists():
                return SignalCreateResult(False, signal_id, target)
            self._atomic_write(target, signal)
        logger.info(
            "signal stored: id=%s type=UserEnter bundle=%r",
            signal_id,
            signal["bundle_id"],
        )
        return SignalCreateResult(True, signal_id, target)

    def create_user_text_input(self, raw: dict[str, Any]) -> EventCreateResult:
        event = sanitize_user_text_input(
            raw,
            excluded_bundle_ids=self._excluded_bundle_ids,
        )
        if event is None:
            return EventCreateResult(False, str(raw.get("event_id") or ""))
        paths.ensure_dirs()
        event_id = event["event_id"]
        target = paths.event_buffer_dir() / f"{event_id}.json"
        with self._signal_lock(f"event-{event_id}"):
            if target.exists():
                return EventCreateResult(False, event_id, target)
            self._atomic_write(target, event)
        logger.info(
            "event stored: id=%s type=UserTextInput bundle=%r",
            event_id,
            event["bundle_id"],
        )
        return EventCreateResult(True, event_id, target)

    def read(self, signal_id: str) -> dict[str, Any] | None:
        if not _SAFE_ID.fullmatch(signal_id):
            return None
        target = paths.signal_buffer_dir() / f"{signal_id}.json"
        with self._signal_lock(signal_id):
            return self._read_current(target)

    def update_linkage(
        self,
        signal_id: str,
        *,
        attempt: dict[str, Any] | None = None,
        post_capture_status: str | None = None,
        quality_status: str | None = None,
        result_snapshot_ref: str | None = None,
        context_snapshot_ref: str | None = None,
        capture_request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> LinkageUpdateResult:
        """Merge one linkage update under the per-signal lock.

        The latest file is always re-read after locking. Attempts are idempotent
        by ``attempt_id`` and successful terminal results cannot be downgraded.
        """
        if not _SAFE_ID.fullmatch(signal_id):
            return LinkageUpdateResult(False, signal_id)
        target = paths.signal_buffer_dir() / f"{signal_id}.json"
        with self._signal_lock(signal_id):
            signal = self._read_current(target)
            if signal is None:
                return LinkageUpdateResult(False, signal_id)
            if signal.get("signal_schema_version") != SIGNAL_SCHEMA_VERSION:
                logger.warning("signal update skipped: id=%s status=unsupported_schema", signal_id)
                return LinkageUpdateResult(False, signal_id)

            current_revision = int(signal.get("revision") or 0)
            if expected_revision is not None and expected_revision != current_revision:
                logger.debug(
                    "signal revision changed: id=%s expected=%d actual=%d; merging latest",
                    signal_id,
                    expected_revision,
                    current_revision,
                )

            changed = False
            if capture_request_id and signal.get("capture_request_id") != capture_request_id:
                signal["capture_request_id"] = capture_request_id
                changed = True
            if (
                context_snapshot_ref is not None
                and signal.get("context_snapshot_ref") is None
            ):
                signal["context_snapshot_ref"] = context_snapshot_ref
                changed = True

            if attempt is not None:
                clean_attempt = self._sanitize_attempt(attempt)
                if clean_attempt is not None:
                    attempts = signal.setdefault("capture_attempts", [])
                    existing = next(
                        (
                            item
                            for item in attempts
                            if item.get("attempt_id") == clean_attempt["attempt_id"]
                        ),
                        None,
                    )
                    if existing is None:
                        attempts.append(clean_attempt)
                        changed = True
                    else:
                        for key, value in clean_attempt.items():
                            if value is None:
                                continue
                            if existing.get(key) != value:
                                existing[key] = value
                                changed = True

            current_status = str(signal.get("post_capture_status") or "pending")
            requested_status = post_capture_status
            if requested_status and self._transition_allowed(current_status, requested_status):
                if requested_status != current_status:
                    signal["post_capture_status"] = requested_status
                    changed = True
                if result_snapshot_ref is not None and signal.get(
                    "result_snapshot_ref"
                ) != result_snapshot_ref:
                    signal["result_snapshot_ref"] = result_snapshot_ref
                    changed = True
                if quality_status in {"good", "degraded", "failed"} and signal.get(
                    "quality_status"
                ) != quality_status:
                    signal["quality_status"] = quality_status
                    changed = True
            elif requested_status and requested_status != current_status:
                logger.warning(
                    "signal transition rejected: id=%s from=%s to=%s",
                    signal_id,
                    current_status,
                    requested_status,
                )

            if not changed:
                return LinkageUpdateResult(False, signal_id, current_revision, current_status)
            signal["revision"] = current_revision + 1
            signal["updated_at"] = _now_iso()
            self._atomic_write(target, signal)
            final_status = str(signal.get("post_capture_status") or "")

        logger.info("signal updated: id=%s post_capture_status=%s", signal_id, final_status)
        return LinkageUpdateResult(True, signal_id, current_revision + 1, final_status)

    def defer_pending_for_shutdown(self) -> int:
        """Mark unfinished V2 attempts as shutdown-deferred without downgrading success."""
        count = 0
        for target in paths.signal_buffer_dir().glob("*.json"):
            signal_id = target.stem
            signal = self.read(signal_id)
            if not signal or signal.get("post_capture_status") in _TERMINAL_STATES:
                continue
            attempt = {
                "attempt_id": f"shutdown-{uuid.uuid4().hex}",
                "capture_request_id": signal.get("capture_request_id"),
                "phase": "primary",
                "association_mode": "direct",
                "status": "cancelled_shutdown",
                "completed_at": _now_iso(),
                "quality_status": "failed",
                "error_reason": "shutdown",
            }
            result = self.update_linkage(
                signal_id,
                attempt=attempt,
                post_capture_status="deferred_shutdown",
                quality_status="failed",
            )
            count += int(result.updated)
        return count

    def recover_incomplete(self) -> list[str]:
        """Normalize abandoned V2 work before the watcher starts.

        Live recapture is intentionally left to the dispatcher, which can
        verify the current app/window. Unknown and legacy schemas are never
        modified here.
        """
        recoverable: list[str] = []
        paths.ensure_dirs()
        for target in paths.signal_buffer_dir().glob("*.json"):
            try:
                signal = json.loads(target.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (
                signal.get("signal_schema_version") is None
                and signal.get("schema_version") == 1
            ):
                signal = self._migrate_v1(target, signal)
            if signal.get("signal_schema_version") != SIGNAL_SCHEMA_VERSION:
                logger.warning("signal recovery skipped: file=%s status=unsupported_schema", target.name)
                continue
            status = str(signal.get("post_capture_status") or "")
            if status not in _DEFERRED_STATES:
                continue
            if status == "running":
                self.update_linkage(
                    str(signal["signal_id"]),
                    attempt={
                        "attempt_id": f"abandoned-{uuid.uuid4().hex}",
                        "phase": "recovery",
                        "association_mode": "recovery",
                        "status": "abandoned_process_exit",
                        "completed_at": _now_iso(),
                        "quality_status": "failed",
                        "error_reason": "process_exit",
                    },
                    post_capture_status="deferred_shutdown",
                    quality_status="failed",
                )
            if not signal.get("result_snapshot_ref"):
                recoverable.append(str(signal["signal_id"]))
        return recoverable

    def _migrate_v1(self, target: Path, legacy: dict[str, Any]) -> dict[str, Any]:
        """Atomically and idempotently migrate the known first-round schema."""
        signal_id = str(legacy.get("signal_id") or "")
        if not _SAFE_ID.fullmatch(signal_id):
            return legacy
        with self._signal_lock(signal_id):
            current = self._read_current(target)
            if current is None:
                return legacy
            if current.get("signal_schema_version") == SIGNAL_SCHEMA_VERSION:
                return current
            if current.get("schema_version") != 1:
                return current
            raw = {
                **current,
                "correlation_id": signal_id,
                "context_snapshot_ref": None,
            }
            migrated = sanitize_user_enter(
                raw,
                excluded_bundle_ids=self._excluded_bundle_ids,
            )
            if migrated is None:
                return current
            old_status = str(current.get("snapshot_status") or "pending")
            status_map = {
                "captured": "new",
                "reused": "reused",
                "duplicate_without_ref": "unchanged",
                "queue_full": "deferred_queue_full",
                "pending": "pending",
                "app_changed": "app_changed",
            }
            migrated["post_capture_status"] = status_map.get(old_status, "unresolved")
            old_ref = current.get("snapshot_ref")
            if migrated["post_capture_status"] in _SUCCESS_STATES:
                migrated["result_snapshot_ref"] = old_ref
                migrated["quality_status"] = "good"
            elif migrated["post_capture_status"] == "deferred_queue_full":
                migrated["quality_status"] = "failed"
            migrated["migrated_from_schema_version"] = 1
            self._atomic_write(target, migrated)
            logger.info("signal migrated: id=%s from=1 to=%d", signal_id, SIGNAL_SCHEMA_VERSION)
            return migrated

    def update_snapshot(
        self,
        signal_id: str,
        *,
        status: str,
        snapshot_ref: str | None = None,
    ) -> None:
        """Compatibility wrapper for V1 callers while the pipeline uses V2."""
        mapping = {
            "captured": ("new", "good"),
            "reused": ("reused", "good"),
            "duplicate_without_ref": ("unchanged", "degraded"),
            "queue_full": ("deferred_queue_full", "failed"),
            "capture_request_failed": ("unresolved", "failed"),
            "capture_unavailable": ("unresolved", "failed"),
            "capture_failed": ("unresolved", "failed"),
            "app_changed": ("app_changed", "failed"),
        }
        post_status, quality = mapping.get(status, ("unresolved", "failed"))
        self.update_linkage(
            signal_id,
            post_capture_status=post_status,
            quality_status=quality,
            result_snapshot_ref=snapshot_ref,
        )

    @staticmethod
    def _transition_allowed(current: str, requested: str) -> bool:
        known = _TERMINAL_STATES | _DEFERRED_STATES
        if requested not in known:
            return False
        if current in _SUCCESS_STATES:
            return requested in _SUCCESS_STATES
        if current in {"app_changed", "privacy_blocked", "unresolved"}:
            return requested == current
        return True

    @staticmethod
    def _sanitize_attempt(raw: dict[str, Any]) -> dict[str, Any] | None:
        attempt_id = str(raw.get("attempt_id") or "")
        if not _SAFE_ID.fullmatch(attempt_id):
            return None
        capture_request_id = str(raw.get("capture_request_id") or "")
        if capture_request_id and not _SAFE_ID.fullmatch(capture_request_id):
            return None
        phase = str(raw.get("phase") or "")
        if phase not in {"primary", "natural_event", "follow_up", "recovery"}:
            return None
        association_mode = str(raw.get("association_mode") or "direct")
        if association_mode not in {"direct", "coalesced", "reused", "recovery"}:
            association_mode = "direct"
        return {
            "attempt_id": attempt_id,
            "capture_request_id": capture_request_id or None,
            "phase": phase,
            "association_mode": association_mode,
            "requested_at": str(raw.get("requested_at") or "")[:80] or None,
            "due_at": str(raw.get("due_at") or "")[:80] or None,
            "started_at": str(raw.get("started_at") or "")[:80] or None,
            "completed_at": str(raw.get("completed_at") or "")[:80] or None,
            "bundle_id": str(raw.get("bundle_id") or "")[:300],
            "window_identity": str(raw.get("window_identity") or "")[:200],
            "window_identity_confidence": str(
                raw.get("window_identity_confidence") or "low"
            ),
            "status": str(raw.get("status") or "")[:80],
            "snapshot_ref": str(raw.get("snapshot_ref") or "")[:300] or None,
            "quality_status": str(raw.get("quality_status") or "")[:40] or None,
            "error_reason": str(raw.get("error_reason") or "")[:120] or None,
        }

    @staticmethod
    def _read_current(target: Path) -> dict[str, Any] | None:
        if not target.exists():
            return None
        try:
            value = json.loads(target.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _atomic_write(target: Path, payload: dict[str, Any]) -> None:
        temp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False))
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
