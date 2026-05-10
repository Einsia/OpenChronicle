"""Enrich capture JSON with structured S1 fields.

Downstream stages (timeline aggregator, session reducer, classifier) read
``focused_element`` / ``visible_text`` / ``url`` instead of re-parsing the
raw AX tree every time. Cutting the prompt size and giving the LLM a
consistent schema is the point.

Ported from Einsia-Partner's S1 extraction (``s1_collector`` —
``_extract_focused_element`` / ``_render_visible_text`` / ``_extract_url``).
Runs inline inside ``capture_once`` so every capture-buffer JSON carries
these fields.

Architecture
------------

``enrich()`` computes a **generic baseline** (focused element + visible text
+ url=None) and then runs registered app parsers in priority order.  Each
parser may selectively override fields via an ``S1Patch``.  This lets future
parsers compose — for example a Linear parser can match ``linear.app`` in
the URL that the browser parser already extracted.
"""

from __future__ import annotations

from typing import Any

# Import triggers builtin parser registration.
from .app_parsers import apply_parsers
from .app_parsers.base import FocusedElement, ParseContext, S1Fields
from .ax_models import ax_app_to_markdown

# Re-export for tests and downstream code that imports from here.
__all__ = ["FocusedElement", "enrich"]

_EDITABLE_ROLES = {"AXTextField", "AXTextArea", "AXComboBox"}
_STATIC_ROLES = {"AXStaticText", "AXWebArea"}

_VISIBLE_TEXT_MAX = 10_000
_FOCUS_TITLE_MAX = 200
_FOCUS_VALUE_MAX = 2_000


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

    # ── Generic baseline ──────────────────────────────────────────────
    fields = S1Fields(
        focused_element=_extract_focused_element(app_data),
        visible_text=_render_visible_text(app_data),
        url=None,
    )

    # ── App-parser patches ────────────────────────────────────────────
    ctx = ParseContext(
        capture=capture,
        app=app_data,
        window_meta=capture.get("window_meta") or {},
    )
    apply_parsers(ctx, fields)

    # ── Write back ────────────────────────────────────────────────────
    capture["focused_element"] = fields.focused_element.to_dict()
    capture["visible_text"] = fields.visible_text
    capture["url"] = fields.url
    if fields.app_context:
        capture["app_context"] = fields.app_context


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
        for el in window.get("elements", []):
            role = el.get("role", "") or ""
            if role in _EDITABLE_ROLES:
                return FocusedElement(
                    role=role,
                    title=(el.get("title") or "")[:_FOCUS_TITLE_MAX],
                    value=(el.get("value") or "")[:_FOCUS_VALUE_MAX],
                    is_editable=True,
                )
            if role in _STATIC_ROLES:
                return FocusedElement(
                    role=role,
                    title=(el.get("title") or "")[:_FOCUS_TITLE_MAX],
                    value=(el.get("value") or el.get("title") or "")[:_FOCUS_VALUE_MAX],
                    is_editable=False,
                )
    return FocusedElement()


def _render_visible_text(app_data: dict[str, Any]) -> str:
    md = ax_app_to_markdown(app_data)
    if len(md) > _VISIBLE_TEXT_MAX:
        md = md[:_VISIBLE_TEXT_MAX] + "\n...(truncated)"
    return md
