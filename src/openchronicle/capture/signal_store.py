"""Durable, privacy-minimized storage for physical user interaction signals."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..logger import get

logger = get("openchronicle.capture")

_SAFE_TARGET_FIELDS = ("role", "subrole", "identifier")
_SAFE_MODIFIERS = {"shift", "command", "control", "option"}
_SAFE_KEY_VARIANTS = {"return", "keypad_enter"}
_SAFE_SIGNAL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SNAPSHOT_STATUS_RANK = {
    "pending": 0,
    "capture_request_failed": 1,
    "capture_unavailable": 1,
    "capture_failed": 1,
    "queue_full": 1,
    "app_changed": 1,
    "duplicate_without_ref": 1,
    "reused": 2,
    "captured": 3,
}


@dataclass(frozen=True)
class SignalCreateResult:
    created: bool
    signal_id: str
    path: Path | None = None


def sanitize_user_enter(
    raw: dict[str, Any],
    *,
    excluded_bundle_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return the allowlisted UserEnter representation, or ``None`` if excluded."""
    if raw.get("event_type") != "UserEnter":
        return None

    signal_id = str(raw.get("signal_id") or "").strip()
    if not _SAFE_SIGNAL_ID.fullmatch(signal_id):
        return None

    bundle_id = str(raw.get("bundle_id") or "")[:300]
    if bundle_id and bundle_id in (excluded_bundle_ids or set()):
        return None

    target = raw.get("input_target")
    safe_target: dict[str, str] | None = None
    if isinstance(target, dict):
        candidate = {
            key: str(target[key])[:200]
            for key in _SAFE_TARGET_FIELDS
            if target.get(key)
        }
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
    return {
        "schema_version": 1,
        "signal_id": signal_id,
        "event_type": "UserEnter",
        "timestamp": str(raw.get("timestamp") or "")[:80],
        "pid": safe_pid,
        "app_name": str(raw.get("app_name") or "")[:200],
        "bundle_id": bundle_id,
        # Window titles can contain document names, contacts, URLs, or typed
        # secrets. They are deliberately not persisted in lightweight signals.
        "window_title": "",
        "key_variant": key_variant,
        "modifiers": safe_modifiers,
        "input_target": safe_target,
        "input_target_status": status,
        "semantic_intent": "unknown",
        "snapshot_status": "pending",
        "snapshot_ref": None,
    }


class SignalStore:
    """Atomic, idempotent JSON-file store keyed by watcher ``signal_id``."""

    def __init__(self, *, excluded_bundle_ids: set[str] | None = None) -> None:
        self._excluded_bundle_ids = excluded_bundle_ids or set()
        self._lock = threading.Lock()

    def create_user_enter(self, raw: dict[str, Any]) -> SignalCreateResult:
        signal = sanitize_user_enter(raw, excluded_bundle_ids=self._excluded_bundle_ids)
        if signal is None:
            return SignalCreateResult(False, str(raw.get("signal_id") or ""))

        paths.ensure_dirs()
        signal_id = signal["signal_id"]
        target = paths.signal_buffer_dir() / f"{signal_id}.json"
        with self._lock:
            if target.exists():
                return SignalCreateResult(False, signal_id, target)
            self._atomic_write(target, signal)
        logger.info(
            "signal stored: id=%s type=UserEnter bundle=%r",
            signal_id,
            signal["bundle_id"],
        )
        return SignalCreateResult(True, signal_id, target)

    def update_snapshot(
        self,
        signal_id: str,
        *,
        status: str,
        snapshot_ref: str | None = None,
    ) -> None:
        target = paths.signal_buffer_dir() / f"{signal_id}.json"
        with self._lock:
            if not target.exists():
                return
            try:
                signal = json.loads(target.read_text())
            except (OSError, json.JSONDecodeError):
                logger.warning("signal update failed: id=%s status=unreadable", signal_id)
                return
            current_status = str(signal.get("snapshot_status") or "pending")
            if _SNAPSHOT_STATUS_RANK.get(status, 1) < _SNAPSHOT_STATUS_RANK.get(
                current_status, 0
            ):
                return
            signal["snapshot_status"] = status
            signal["snapshot_ref"] = snapshot_ref
            self._atomic_write(target, signal)
        logger.info("signal updated: id=%s snapshot_status=%s", signal_id, status)

    @staticmethod
    def _atomic_write(target: Path, payload: dict[str, Any]) -> None:
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False))
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
