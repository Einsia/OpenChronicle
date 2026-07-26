from __future__ import annotations

import json

from openchronicle.capture.signal_store import SignalStore, sanitize_user_enter


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
    assert signal["window_title"] == ""
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
    assert signal["snapshot_status"] == "reused"
    assert signal["snapshot_ref"] == "snapshot.json"
