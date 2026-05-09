"""Deterministic assertion helpers for RPA workflow replay."""

from __future__ import annotations

from typing import Any


def verify_assertion(assertion: dict[str, Any] | None, observation: dict[str, Any]) -> tuple[bool, str]:
    if not assertion:
        return True, ""

    assertion_type = str(assertion.get("type") or "")
    value = assertion.get("value")

    if assertion_type == "text_exists":
        texts = _texts(observation)
        if value is not None and str(value) in "\n".join(texts):
            return True, ""
        return False, f"text not found: {value}"

    if assertion_type == "resource_id_exists":
        resource_ids = _resource_ids(observation)
        if value is not None and str(value) in resource_ids:
            return True, ""
        return False, f"resource_id not found: {value}"

    if assertion_type == "ocr_contains":
        texts = _texts(observation)
        if value is not None and str(value) in "\n".join(texts):
            return True, ""
        return False, f"OCR text not found: {value}"

    if assertion_type == "screen_changed":
        before = str(observation.get("before_screen_state") or "")
        after = str(observation.get("screen_state") or observation.get("after_screen_state") or "")
        if before and after and before != after:
            return True, ""
        return False, "screen did not change"

    return False, f"unsupported assertion type: {assertion_type}"


def _texts(observation: dict[str, Any]) -> list[str]:
    values = observation.get("ocr_text") or observation.get("ocr_texts") or []
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values]


def _resource_ids(observation: dict[str, Any]) -> set[str]:
    raw = observation.get("resource_ids") or []
    if isinstance(raw, str):
        return {raw}
    return {str(value) for value in raw}
