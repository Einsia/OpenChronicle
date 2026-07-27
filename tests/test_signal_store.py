from __future__ import annotations

import json

from openchronicle.capture.signal_store import (
    SignalStore,
    sanitize_user_enter,
    sanitize_user_text_input,
)


def _enter(signal_id: str = "sig-1", **overrides: object) -> dict:
    event = {
        "event_type": "UserEnter",
        "signal_id": signal_id,
        "timestamp": "2026-07-25T12:00:00+08:00",
        "pid": 42,
        "app_name": "Terminal",
        "bundle_id": "com.apple.Terminal",
        "window_title": "secret-token-in-title",
        "key_variant": "return",
        "modifiers": ["shift", "command", "invalid"],
        "input_target": {
            "role": "AXTextField",
            "subrole": "AXStandardTextField",
            "identifier": "input",
            "title": "private title",
            "value": "sk-secret-value",
        },
        "input_target_status": "available",
        "semantic_intent": "submit",
    }
    event.update(overrides)
    return event


def test_sanitize_user_enter_is_strict_allowlist() -> None:
    signal = sanitize_user_enter(_enter())

    assert signal is not None
    assert "window_title" not in signal
    assert signal["signal_schema_version"] == 2
    assert signal["revision"] == 1
    assert signal["semantic_intent"] == "unknown"
    assert signal["modifiers"] == ["shift", "command"]
    assert signal["input_target"] == {
        "role": "AXTextField",
        "subrole": "AXStandardTextField",
        "identifier": "input",
    }
    serialized = json.dumps(signal)
    assert "secret-token" not in serialized
    assert "sk-secret" not in serialized
    assert "private title" not in serialized
    assert "submit" not in serialized


def test_secure_target_is_removed() -> None:
    signal = sanitize_user_enter(_enter(input_target_status="secure_input"))

    assert signal is not None
    assert signal["input_target"] is None
    assert signal["input_target_status"] == "secure_input"


def test_signal_store_is_idempotent(ac_root) -> None:
    store = SignalStore()

    first = store.create_user_enter(_enter())
    second = store.create_user_enter(_enter())

    assert first.created is True
    assert second.created is False
    files = list((ac_root / "signal-buffer").glob("*.json"))
    assert len(files) == 1


def test_excluded_bundle_is_not_persisted(ac_root) -> None:
    store = SignalStore(excluded_bundle_ids={"com.apple.Terminal"})

    result = store.create_user_enter(_enter())

    assert result.created is False
    assert list((ac_root / "signal-buffer").glob("*.json")) == []


def test_unsafe_signal_id_is_rejected(ac_root) -> None:
    store = SignalStore()

    result = store.create_user_enter(_enter("../outside"))

    assert result.created is False
    assert list((ac_root / "signal-buffer").glob("*.json")) == []


def test_snapshot_update_preserves_signal(ac_root) -> None:
    store = SignalStore()
    store.create_user_enter(_enter())

    store.update_snapshot("sig-1", status="reused", snapshot_ref="snapshot.json")

    signal = json.loads((ac_root / "signal-buffer" / "sig-1.json").read_text())
    assert signal["post_capture_status"] == "reused"
    assert signal["result_snapshot_ref"] == "snapshot.json"


def test_identifier_with_control_characters_is_removed() -> None:
    signal = sanitize_user_enter(
        _enter(input_target={"role": "AXTextField", "identifier": "secret\nvalue"})
    )

    assert signal is not None
    assert signal["input_target"] == {"role": "AXTextField"}


def test_success_result_cannot_be_downgraded_and_revision_increments(ac_root) -> None:
    store = SignalStore()
    store.create_user_enter(_enter())

    first = store.update_linkage(
        "sig-1",
        post_capture_status="new",
        quality_status="good",
        result_snapshot_ref="new.json",
    )
    second = store.update_linkage(
        "sig-1",
        post_capture_status="deferred_queue_full",
        quality_status="failed",
    )
    signal = json.loads((ac_root / "signal-buffer" / "sig-1.json").read_text())

    assert first.updated is True
    assert second.updated is False
    assert signal["revision"] == 2
    assert signal["post_capture_status"] == "new"
    assert signal["result_snapshot_ref"] == "new.json"


def test_attempt_updates_are_idempotent(ac_root) -> None:
    store = SignalStore()
    store.create_user_enter(_enter())
    attempt = {
        "attempt_id": "att-1",
        "capture_request_id": "cap-1",
        "phase": "primary",
        "association_mode": "direct",
        "status": "running",
    }

    store.update_linkage("sig-1", attempt=attempt, post_capture_status="running")
    store.update_linkage("sig-1", attempt=attempt, post_capture_status="running")
    signal = json.loads((ac_root / "signal-buffer" / "sig-1.json").read_text())

    assert len(signal["capture_attempts"]) == 1


def test_attempt_completion_preserves_requested_timestamps(ac_root) -> None:
    store = SignalStore()
    store.create_user_enter(_enter())
    store.update_linkage(
        "sig-1",
        attempt={
            "attempt_id": "att-timing",
            "capture_request_id": "cap-1",
            "phase": "primary",
            "association_mode": "direct",
            "requested_at": "2026-07-25T12:00:00+08:00",
            "due_at": "2026-07-25T12:00:00.200+08:00",
            "started_at": "2026-07-25T12:00:00.201+08:00",
            "status": "running",
        },
        post_capture_status="running",
    )
    store.update_linkage(
        "sig-1",
        attempt={
            "attempt_id": "att-timing",
            "capture_request_id": "cap-1",
            "phase": "primary",
            "association_mode": "direct",
            "completed_at": "2026-07-25T12:00:00.500+08:00",
            "status": "new",
        },
        post_capture_status="new",
        quality_status="good",
        result_snapshot_ref="new.json",
    )

    signal = json.loads((ac_root / "signal-buffer" / "sig-1.json").read_text())
    attempt = signal["capture_attempts"][0]
    assert attempt["requested_at"] == "2026-07-25T12:00:00+08:00"
    assert attempt["due_at"] == "2026-07-25T12:00:00.200+08:00"
    assert attempt["started_at"] == "2026-07-25T12:00:00.201+08:00"
    assert attempt["completed_at"] == "2026-07-25T12:00:00.500+08:00"


def test_known_v1_schema_migrates_once(ac_root) -> None:
    signal_dir = ac_root / "signal-buffer"
    signal_dir.mkdir(parents=True, exist_ok=True)
    path = signal_dir / "legacy-1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "signal_id": "legacy-1",
                "event_type": "UserEnter",
                "timestamp": "2026-07-25T12:00:00+08:00",
                "pid": 42,
                "app_name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "key_variant": "return",
                "modifiers": [],
                "input_target": {"role": "AXTextArea"},
                "input_target_status": "available",
                "snapshot_status": "reused",
                "snapshot_ref": "old.json",
            }
        )
    )
    store = SignalStore()

    store.recover_incomplete()
    first = path.read_text()
    store.recover_incomplete()

    signal = json.loads(path.read_text())
    assert path.read_text() == first
    assert signal["signal_schema_version"] == 2
    assert signal["migrated_from_schema_version"] == 1
    assert signal["post_capture_status"] == "reused"
    assert signal["result_snapshot_ref"] == "old.json"


def test_user_text_input_event_is_relationship_only_and_idempotent(ac_root) -> None:
    raw = {
        "event_type": "UserTextInput",
        "event_id": "evt-1",
        "correlation_id": "corr-1",
        "related_signal_id": "sig-1",
        "timestamp": "2026-07-27T12:00:00+08:00",
        "pid": 42,
        "app_name": "TextEdit",
        "bundle_id": "com.apple.TextEdit",
        "window_title": "private",
        "details": {
            "reason": "enter",
            "element": {
                "role": "AXTextArea",
                "identifier": "First Text View",
                "title": "private",
                "value": "V2_PRIVATE_TEXT",
            },
        },
    }
    event = sanitize_user_text_input(raw)
    assert event is not None
    serialized = json.dumps(event)
    assert "V2_PRIVATE_TEXT" not in serialized
    assert "private" not in serialized
    assert event["related_signal_id"] == "sig-1"

    store = SignalStore()
    assert store.create_user_text_input(raw).created is True
    assert store.create_user_text_input(raw).created is False
    assert len(list((ac_root / "event-buffer").glob("*.json"))) == 1
