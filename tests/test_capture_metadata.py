from __future__ import annotations

import json
from dataclasses import dataclass

from openchronicle.capture import scheduler
from openchronicle.capture.signal_store import SignalStore
from openchronicle.config import CaptureConfig


@dataclass
class _Result:
    raw_json: dict
    metadata: dict


class _Provider:
    available = True

    def __init__(self, raw_json: dict | list[dict]) -> None:
        self.snapshots = raw_json if isinstance(raw_json, list) else [raw_json]
        self.calls = 0

    def capture_frontmost(self, *, focused_window_only: bool) -> _Result:
        assert focused_window_only is True
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return _Result(self.snapshots[index], {})


def test_build_capture_prefers_snapshot_title(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    monkeypatch.setattr(
        scheduler.window_meta,
        "active_window",
        lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                    "is_frontmost": True,
                    "focused_element": {"role": "AXTextArea", "value": "body"},
                    "windows": [
                        {
                            "title": "  Snapshot\nTitle  ",
                            "focused": True,
                            "elements": [],
                        }
                    ],
                }
            ]
        }
    )

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.apple.TextEdit",
            "window_title": "Stale title",
        },
    )

    assert out is not None
    assert out["window_meta"]["title"] == "Snapshot Title"
    assert out["window_meta"]["title_source"] == "ax_snapshot"


def test_build_capture_uses_matching_trigger_title(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", ())
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    monkeypatch.setattr(
        scheduler.window_meta,
        "active_window",
        lambda: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                    "is_frontmost": True,
                    "windows": [{"title": "", "focused": True, "elements": []}],
                }
            ]
        }
    )

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.apple.TextEdit",
            "window_title": "Event title",
        },
    )

    assert out is not None
    assert out["window_meta"]["title"] == "Event title"
    assert out["window_meta"]["title_source"] == "trigger"


def test_build_capture_rejects_cross_app_trigger_title(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", ())
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    monkeypatch.setattr(
        scheduler.window_meta,
        "active_window",
        lambda: scheduler.window_meta.WindowMeta(
            app_name="TextEdit",
            title="Current title",
            bundle_id="com.apple.TextEdit",
        ),
    )
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                    "is_frontmost": True,
                    "windows": [{"title": "", "focused": True, "elements": []}],
                }
            ]
        }
    )

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "AXFocusedWindowChanged",
            "bundle_id": "com.google.Chrome",
            "window_title": "Stale Chrome title",
        },
    )

    assert out is not None
    assert out["window_meta"]["title"] == "Current title"
    assert out["window_meta"]["title_source"] == "system_events"


def test_build_capture_retries_incomplete_textedit_snapshot(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(scheduler.time, "sleep", lambda _: None)
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    incomplete = {
        "apps": [
            {
                "name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Untitled",
                        "focused": True,
                        "elements": [{"role": "AXScrollArea"}],
                    }
                ],
            }
        ]
    }
    ready = {
        "apps": [
            {
                "name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "is_frontmost": True,
                "focused_element": {
                    "role": "AXTextArea",
                    "identifier": "First Text View",
                    "value": "OC_TEXTEDIT_BODY_001",
                },
                "windows": [
                    {
                        "title": "Untitled",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXScrollArea",
                                "children": [
                                    {
                                        "role": "AXTextArea",
                                        "value": "OC_TEXTEDIT_BODY_001",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    provider = _Provider([incomplete, ready])

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "AXApplicationActivated",
            "bundle_id": "com.apple.TextEdit",
            "window_title": "Untitled",
        },
    )

    assert out is not None
    assert provider.calls == 2
    assert out["focused_element"]["role"] == "AXTextArea"
    assert "OC_TEXTEDIT_BODY_001" in out["visible_text"]
    assert out["ax_metadata"]["retry_count"] == 1
    assert out["ax_metadata"]["app_consistent"] is True


def test_build_capture_discards_retry_after_app_switch(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(scheduler.time, "sleep", lambda _: None)
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    monkeypatch.setattr(
        scheduler.window_meta,
        "active_window",
        lambda: scheduler.window_meta.WindowMeta(
            app_name="TextEdit",
            title="Untitled",
            bundle_id="com.apple.TextEdit",
        ),
    )
    textedit = {
        "apps": [
            {
                "name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "is_frontmost": True,
                "windows": [{"title": "Untitled", "focused": True, "elements": []}],
            }
        ]
    }
    chrome = {
        "apps": [
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "focused_element": {"role": "AXTextField", "value": "https://example.com"},
                "windows": [{"title": "Example", "focused": True, "elements": []}],
            }
        ]
    }
    provider = _Provider([textedit, chrome])

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "AXApplicationActivated",
            "bundle_id": "com.apple.TextEdit",
            "window_title": "Untitled",
        },
    )

    assert out is not None
    assert provider.calls == 2
    assert out["window_meta"]["bundle_id"] == "com.apple.TextEdit"
    assert out["focused_element"]["role"] == ""
    assert out["ax_metadata"]["app_consistent"] is False


def test_build_capture_does_not_retry_complete_browser_page(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(
        scheduler.time,
        "sleep",
        lambda _: (_ for _ in ()).throw(AssertionError("browser snapshot must not retry")),
    )
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "Chrome",
                    "bundle_id": "com.google.Chrome",
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": "Example Domain",
                            "focused": True,
                            "elements": [
                                {
                                    "role": "AXToolbar",
                                    "children": [
                                        {
                                            "role": "AXTextField",
                                            "title": "Address and search bar",
                                            "value": "https://example.com/?oc_case=A01",
                                        }
                                    ],
                                },
                                {
                                    "role": "AXWebArea",
                                    "children": [
                                        {"role": "AXStaticText", "value": "Example Domain"}
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )

    out = scheduler._build_capture(
        CaptureConfig(include_screenshot=False),
        provider,
        {
            "event_type": "UserMouseClick",
            "bundle_id": "com.google.Chrome",
            "window_title": "Example Domain",
        },
    )

    assert out is not None
    assert provider.calls == 1
    assert out["focused_element"]["role"] == ""
    assert out["url"] == "https://example.com/?oc_case=A01"
    assert out["ax_metadata"]["retry_count"] == 0
    assert out["ax_metadata"]["app_consistent"] is True


def test_enter_reuses_identical_snapshot_without_losing_signal(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", ())
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                    "is_frontmost": True,
                    "focused_element": {"role": "AXTextArea", "value": "same"},
                    "windows": [
                        {
                            "title": "Untitled",
                            "focused": True,
                            "elements": [{"role": "AXTextArea", "value": "same"}],
                        }
                    ],
                }
            ]
        }
    )
    store = SignalStore()
    runner = scheduler._CaptureRunner(
        CaptureConfig(include_screenshot=False),
        provider,
        signal_store=store,
    )
    for signal_id in ("enter-1", "enter-2"):
        store.create_user_enter(
            {
                "event_type": "UserEnter",
                "signal_id": signal_id,
                "timestamp": "2026-07-25T12:00:00+08:00",
                "bundle_id": "com.apple.TextEdit",
                "key_variant": "return",
            }
        )
        runner.run(
            {
                "event_type": "UserEnter",
                "signal_id": signal_id,
                "bundle_id": "com.apple.TextEdit",
            }
        )

    first = json.loads((ac_root / "signal-buffer" / "enter-1.json").read_text())
    second = json.loads((ac_root / "signal-buffer" / "enter-2.json").read_text())
    assert first["snapshot_status"] == "captured"
    assert second["snapshot_status"] == "reused"
    assert second["snapshot_ref"] == first["snapshot_ref"]
    assert len(list((ac_root / "capture-buffer").glob("*.json"))) == 1


def test_enter_does_not_associate_snapshot_after_app_switch(monkeypatch, ac_root) -> None:
    monkeypatch.setattr(scheduler, "_AX_RETRY_DELAYS", ())
    monkeypatch.setattr(scheduler.screenshot, "grab", lambda **_: None)
    provider = _Provider(
        {
            "apps": [
                {
                    "name": "Chrome",
                    "bundle_id": "com.google.Chrome",
                    "is_frontmost": True,
                    "windows": [{"title": "New app", "focused": True, "elements": []}],
                }
            ]
        }
    )
    store = SignalStore()
    store.create_user_enter(
        {
            "event_type": "UserEnter",
            "signal_id": "switched",
            "timestamp": "2026-07-25T12:00:00+08:00",
            "bundle_id": "com.apple.TextEdit",
            "key_variant": "return",
        }
    )
    runner = scheduler._CaptureRunner(
        CaptureConfig(include_screenshot=False),
        provider,
        signal_store=store,
    )

    runner.run(
        {
            "event_type": "UserEnter",
            "signal_id": "switched",
            "bundle_id": "com.apple.TextEdit",
        }
    )

    signal = json.loads((ac_root / "signal-buffer" / "switched.json").read_text())
    assert signal["snapshot_status"] == "app_changed"
    assert signal["snapshot_ref"] is None
    assert list((ac_root / "capture-buffer").glob("*.json")) == []
