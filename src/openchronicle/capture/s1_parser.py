"""Enrich capture JSON with structured S1 fields.

Downstream stages (timeline aggregator, session reducer, classifier) read
``focused_element`` / ``visible_text`` / ``url`` instead of re-parsing the
raw AX tree every time. Cutting the prompt size and giving the LLM a
consistent schema is the point.

Ported from Einsia-Partner's S1 extraction (``s1_collector`` —
``_extract_focused_element`` / ``_render_visible_text`` / ``_extract_url``).
Runs inline inside ``capture_once`` so every capture-buffer JSON carries
these fields.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .ax_models import ax_app_to_markdown

_BROWSER_BUNDLES = {
    "com.google.Chrome",
    "com.apple.Safari",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.brave.Browser",
    "com.operasoftware.Opera",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
}

_URL_RE = re.compile(r"https?://\S+")

_EDITABLE_ROLES = {"AXTextField", "AXTextArea", "AXComboBox"}
_STATIC_ROLES = {"AXStaticText", "AXWebArea"}

_VISIBLE_TEXT_MAX = 10_000
_FOCUS_TITLE_MAX = 200
_FOCUS_VALUE_MAX = 2_000


@dataclass
class FocusedElement:
    role: str = ""
    title: str = ""
    value: str = ""
    is_editable: bool = False
    has_value: bool = False
    value_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        stripped = (self.value or "").strip()
        d["has_value"] = bool(stripped)
        d["value_length"] = len(stripped)
        return d


def enrich(capture: dict[str, Any]) -> None:
    """Mutate ``capture`` in place: add ``focused_element`` / ``visible_text`` / ``url``.

    No-op when there is no ``ax_tree`` (e.g. AX unavailable, permission denied).
    """
    ax_tree = capture.get("ax_tree")
    if not isinstance(ax_tree, dict):
        return

    app_data = _frontmost_app(ax_tree)
    if app_data is None:
        capture["focused_element"] = FocusedElement().to_dict()
        capture["visible_text"] = ""
        capture["url"] = None
        return

    capture["focused_element"] = _extract_focused_element(app_data).to_dict()
    capture["visible_text"] = _render_visible_text(app_data)
    capture["url"] = _extract_url(app_data)


def _frontmost_app(ax_tree: dict[str, Any]) -> dict[str, Any] | None:
    apps = ax_tree.get("apps") or []
    for app in apps:
        if app.get("is_frontmost"):
            return app
    return apps[0] if apps else None


def _extract_focused_element(app_data: dict[str, Any]) -> FocusedElement:
    for window in app_data.get("windows", []):
        if not window.get("focused"):
            continue

        elements = list(_walk_elements(window.get("elements", [])))
        for el in elements:
            if el.get("focused") and (el.get("role") or "") in (_EDITABLE_ROLES | _STATIC_ROLES):
                return _focused_from_element(el)
        for el in elements:
            if (el.get("role") or "") in _EDITABLE_ROLES:
                return _focused_from_element(el)
        for el in elements:
            if (el.get("role") or "") in _STATIC_ROLES:
                return _focused_from_element(el)
    return FocusedElement()


def _focused_from_element(el: dict[str, Any]) -> FocusedElement:
    role = el.get("role", "") or ""
    is_editable = role in _EDITABLE_ROLES
    value = el.get("value") or ("" if is_editable else el.get("title") or "")
    return FocusedElement(
        role=role,
        title=(el.get("title") or "")[:_FOCUS_TITLE_MAX],
        value=(value or "")[:_FOCUS_VALUE_MAX],
        is_editable=is_editable,
    )


def _render_visible_text(app_data: dict[str, Any]) -> str:
    md = ax_app_to_markdown(app_data)
    if len(md) > _VISIBLE_TEXT_MAX:
        md = md[:_VISIBLE_TEXT_MAX] + "\n...(truncated)"
    return md


def _extract_url(app_data: dict[str, Any]) -> str | None:
    bundle = (app_data.get("bundle_id", "") or "").lower()
    if bundle not in {b.lower() for b in _BROWSER_BUNDLES}:
        return None
    for window in app_data.get("windows", []):
        for el in _walk_elements(window.get("elements", [])):
            if el.get("role") not in ("AXTextField", "AXComboBox", "AXWebArea"):
                continue
            value = (el.get("value") or "").strip()
            if not value:
                continue
            match = _URL_RE.search(value)
            if match:
                return match.group(0).rstrip(".,);]")
            if _looks_like_bare_url(value):
                return f"https://{value}"
    return None


def _walk_elements(elements: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for el in elements:
        yield el
        children = el.get("children") or []
        if isinstance(children, list):
            yield from _walk_elements(children)


def _looks_like_bare_url(value: str) -> bool:
    if any(ch.isspace() for ch in value):
        return False
    if "." not in value or len(value) > 300:
        return False
    lowered = value.lower()
    return not lowered.startswith(("about:", "file:", "edge:", "chrome:"))
