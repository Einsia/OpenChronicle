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
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .ax_models import ax_app_to_markdown

_BROWSER_BUNDLES = {
    "com.google.Chrome",
    "com.apple.Safari",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.brave.Browser",
    "com.operasoftware.Opera",
}

_URL_RE = re.compile(r"^[^\s]+$")

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
        capture["url_source"] = "unavailable"
        return

    capture["focused_element"] = _extract_focused_element(app_data).to_dict()
    capture["visible_text"] = _render_visible_text(app_data)
    url, source = _extract_url(app_data)
    capture["url"] = url
    capture["url_source"] = source


def _frontmost_app(ax_tree: dict[str, Any]) -> dict[str, Any] | None:
    apps = ax_tree.get("apps") or []
    for app in apps:
        if app.get("is_frontmost"):
            return app
    return apps[0] if apps else None


def _extract_focused_element(app_data: dict[str, Any]) -> FocusedElement:
    direct = app_data.get("focused_element")
    if isinstance(direct, dict):
        return _focused_element_from_node(direct)

    for window in app_data.get("windows", []):
        if not window.get("focused"):
            continue
        # Compatibility fallback for fixtures/older helpers: recurse, but only
        # trust a node explicitly marked focused. An arbitrary first text node
        # is worse than an empty result.
        for el, _ancestors in _walk_elements(window.get("elements", [])):
            if el.get("focused") is True:
                return _focused_element_from_node(el)
    return FocusedElement()


def _focused_element_from_node(node: dict[str, Any]) -> FocusedElement:
    role = node.get("role", "") or ""
    value = node.get("value") or ""
    if role in _STATIC_ROLES and not value:
        value = node.get("title") or ""
    return FocusedElement(
        role=role,
        title=(node.get("title") or "")[:_FOCUS_TITLE_MAX],
        value=value[:_FOCUS_VALUE_MAX],
        is_editable=role in _EDITABLE_ROLES,
    )


def _walk_elements(elements: list[dict[str, Any]], ancestors: tuple[str, ...] = ()):
    for el in elements:
        if not isinstance(el, dict):
            continue
        role = el.get("role", "") or ""
        yield el, ancestors
        children = el.get("children") or []
        if isinstance(children, list):
            yield from _walk_elements(children, (*ancestors, role))


def _render_visible_text(app_data: dict[str, Any]) -> str:
    md = ax_app_to_markdown(app_data)
    if len(md) > _VISIBLE_TEXT_MAX:
        md = md[:_VISIBLE_TEXT_MAX] + "\n...(truncated)"
    return md


def _extract_url(app_data: dict[str, Any]) -> tuple[str | None, str]:
    bundle = app_data.get("bundle_id", "")
    if bundle not in _BROWSER_BUNDLES:
        return None, "unavailable"

    strong: list[str] = []
    toolbar: list[str] = []
    for window in app_data.get("windows", []):
        if not window.get("focused"):
            continue
        for el, ancestors in _walk_elements(window.get("elements", [])):
            if el.get("role") not in {"AXTextField", "AXComboBox"}:
                continue
            value = _normalize_url(el.get("value") or "")
            if value is None:
                continue
            semantic = " ".join(
                str(el.get(key) or "")
                for key in ("title", "description", "identifier", "domIdentifier")
            ).lower()
            is_address_semantic = any(
                marker in semantic
                for marker in ("address", "location", "omnibox", "url bar", "search bar")
            )
            in_toolbar = "AXToolbar" in ancestors
            in_web_area = "AXWebArea" in ancestors
            if is_address_semantic and not in_web_area:
                strong.append(value)
            elif in_toolbar:
                toolbar.append(value)

    candidates = list(dict.fromkeys(strong))
    if len(candidates) == 1:
        return candidates[0], "ax_address_bar"
    if len(candidates) > 1:
        return None, "unavailable"

    candidates = list(dict.fromkeys(toolbar))
    if len(candidates) == 1:
        return candidates[0], "ax_address_bar"
    return None, "unavailable"


def _normalize_url(raw: str) -> str | None:
    value = raw.strip()
    if not value or not _URL_RE.fullmatch(value):
        return None

    candidate = value
    if "://" not in candidate:
        if (
            "." not in candidate
            and candidate != "localhost"
            and not candidate.startswith("localhost:")
        ):
            return None
        candidate = f"https://{candidate}"

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https", "chrome", "file"}:
        return None
    if parsed.scheme in {"http", "https"} and not parsed.hostname:
        return None

    hostname = parsed.hostname or ""
    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None:
        host = f"{host}:{port}"
    # Deliberately discard username/password from the normalized URL.
    netloc = host
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment))
