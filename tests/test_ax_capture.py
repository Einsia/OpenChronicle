from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from openchronicle.capture import ax_capture


def test_provider_passes_manual_accessibility_bundle_and_reports_result(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "timestamp": "2026-07-24T14:00:00+08:00",
                    "apps": [
                        {
                            "name": "Code",
                            "bundle_id": "com.microsoft.VSCode",
                            "is_frontmost": True,
                            "manual_accessibility": {
                                "requested": True,
                                "succeeded": True,
                                "error_code": 0,
                            },
                            "windows": [
                                {
                                    "title": "Untitled-1",
                                    "focused": True,
                                    "elements": [],
                                }
                            ],
                        }
                    ],
                }
            ),
        )

    monkeypatch.setattr(ax_capture.subprocess, "run", fake_run)
    provider = ax_capture.MacAXHelperProvider(
        helper_path=Path("/tmp/mac-ax-helper"),
        depth=100,
        timeout=3,
        manual_accessibility_bundles=[
            "com.microsoft.VSCode",
            "com.example.CustomElectron",
        ],
    )

    result = provider.capture_frontmost()

    assert result is not None
    assert calls == [
        [
            "/tmp/mac-ax-helper",
            "--focused-window-only",
            "--manual-accessibility-bundle",
            "com.microsoft.VSCode",
            "--manual-accessibility-bundle",
            "com.example.CustomElectron",
            "--depth",
            "100",
            "--timeout",
            "3",
        ]
    ]
    assert result.metadata["manual_accessibility"] == [
        {
            "bundle_id": "com.microsoft.VSCode",
            "requested": True,
            "succeeded": True,
            "error_code": 0,
        }
    ]
