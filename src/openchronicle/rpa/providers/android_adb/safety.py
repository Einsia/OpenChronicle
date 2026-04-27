"""Android-specific RPA safety helpers."""

from __future__ import annotations

from typing import Any

from ...safety import assess_action


def assess_android_action(action: dict[str, Any]) -> dict[str, Any]:
    return assess_action(action)
