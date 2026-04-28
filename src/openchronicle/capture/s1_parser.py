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
from pathlib import PurePath
from typing import Any

from .ax_models import ax_app_to_markdown

# macOS bundle IDs (reverse-DNS).
_BROWSER_BUNDLES_MAC = {
    "com.google.Chrome",
    "com.apple.Safari",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.brave.Browser",
    "com.operasoftware.Opera",
}

# Windows executable basenames (lowercase, no extension). On Windows the
# capture pipeline stores the full ``*.exe`` path as ``bundle_id``, so we
# match on the file stem to keep parity with the macOS bundle-ID check.
_BROWSER_EXES_WIN = {
    "chrome",
    "msedge",
    "firefox",
    "brave",
    "opera",
    "vivaldi",
    "arc",
    "iexplore",
}

_URL_RE = re.compile(r"https?://\S+")

_EDITABLE_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXEdit"}
_STATIC_ROLES = {"AXStaticText", "AXWebArea", "AXText"}

# Roles that can hold a browser address bar. mac-ax-helper reports the
# Chromium/Safari address bar as ``AXTextField``; win-uia-helper.ps1 maps
# the UIA ``Edit`` control type to ``AXEdit`` (and some browsers expose
# the address bar as ``AXComboBox``). Keep all three here so ``_extract_url``
# works on both platforms without per-OS branching.
_URL_BAR_ROLES = {"AXTextField", "AXEdit", "AXComboBox"}

# Hints in the address-bar element's title/identifier — used to prefer the
# real address bar over an unrelated edit control on the page (e.g. a
# search input rendered as ``AXEdit``). Lowercased substring match.
_URL_BAR_NAME_HINTS = (
    "address",            # "Address and search bar" (Edge/Chrome English)
    "url",                # "URL bar"
    "location",           # Firefox "location bar"
    "地址",               # Edge/Chrome zh-CN "地址和搜索栏"
)

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


def _is_browser_bundle(bundle: str) -> bool:
    """Cross-platform browser detection.

    macOS: ``bundle_id`` is reverse-DNS (e.g. ``com.microsoft.edgemac``).
    Windows: ``bundle_id`` is the full executable path
    (e.g. ``C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe``)
    — match on the lowercase file stem.
    """
    if not bundle:
        return False
    if bundle in _BROWSER_BUNDLES_MAC:
        return True
    # PurePath handles both forward- and back-slashes regardless of the
    # host OS, so a Windows path passed through on macOS still parses.
    stem = PurePath(bundle).stem.lower()
    if not stem and "." in bundle:
        # Bare exe name like ``msedge.exe`` or ``msedge`` slipping through.
        stem = bundle.rsplit(".", 1)[0].lower()
    return stem in _BROWSER_EXES_WIN


def enrich(capture: dict[str, Any], *, trigger: dict[str, Any] | None = None) -> None:
    """Mutate ``capture`` in place: add ``focused_element`` / ``visible_text`` / ``url``.

    No-op when there is no ``ax_tree`` (e.g. AX unavailable, permission denied).

    ``trigger`` (optional) is the watcher event that drove this capture.
    When ax_tree fails to yield a URL we fall back to scanning
    ``trigger.window_title`` for an ``https?://...`` substring, so a
    GitHub-style window title that ends in ``" — Microsoft Edge"`` still
    has its URL surfaced. This mirrors the macOS behaviour of pulling URL
    candidates from any text the watcher already exposed.
    """
    ax_tree = capture.get("ax_tree")
    if not isinstance(ax_tree, dict):
        if trigger is not None:
            capture["url"] = _extract_url_from_trigger(trigger)
        return

    app_data = _frontmost_app(ax_tree)
    if app_data is None:
        capture["focused_element"] = FocusedElement().to_dict()
        capture["visible_text"] = ""
        capture["url"] = _extract_url_from_trigger(trigger) if trigger is not None else None
        return

    focused = _extract_focused_element(app_data)
    capture["focused_element"] = focused.to_dict()
    capture["visible_text"] = _render_visible_text(app_data)

    url = _extract_url(app_data)
    # All URL fallbacks are gated on bundle-is-browser, so a code editor
    # whose buffer contains an https URL never surfaces as a captured URL.
    is_browser = _is_browser_bundle(str(app_data.get("bundle_id") or ""))
    if not url and is_browser:
        # Edge/Chrome on Windows sometimes only expose the address bar
        # as the focused AXEdit, not as a child element of the window.
        url = _extract_url_from_text(focused.value)
    if not url and trigger is not None:
        url = _extract_url_from_trigger(trigger)
    capture["url"] = url


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


def _extract_url(app_data: dict[str, Any]) -> str | None:
    bundle = app_data.get("bundle_id", "")
    if not _is_browser_bundle(bundle):
        return None

    # Two-pass walk: prefer an element whose title/identifier looks like
    # an address bar ("Address and search bar"), then fall back to any
    # url-bar-shaped element. This avoids picking up an in-page search
    # field that happens to be the first AXEdit on the page.
    candidates: list[tuple[bool, str]] = []
    for window in app_data.get("windows", []):
        _collect_url_bar_candidates(window.get("elements", []), candidates)

    candidates.sort(key=lambda c: 0 if c[0] else 1)
    for _is_named, value in candidates:
        url = _normalise_url(value)
        if url:
            return url
    return None


def _collect_url_bar_candidates(
    elements: list[dict[str, Any]],
    out: list[tuple[bool, str]],
) -> None:
    """Recursive walk: collect (is_named_addr_bar, value) tuples."""
    for el in elements:
        role = el.get("role", "") or ""
        if role in _URL_BAR_ROLES:
            value = (el.get("value") or "").strip()
            if value:
                hint_blob = " ".join(
                    str(el.get(k) or "") for k in ("title", "identifier", "name")
                ).lower()
                is_named = any(h in hint_blob for h in _URL_BAR_NAME_HINTS)
                out.append((is_named, value))
        children = el.get("children")
        if children:
            _collect_url_bar_candidates(children, out)


def _normalise_url(value: str) -> str | None:
    """Turn an address-bar string into a normalised URL or ``None``."""
    if not value:
        return None
    match = _URL_RE.search(value)
    if match:
        return match.group(0)
    if "." in value and " " not in value:
        return f"https://{value}"
    return None


def _extract_url_from_text(text: str) -> str | None:
    """Pull the first ``https?://...`` substring out of free-form text."""
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def _extract_url_from_trigger(trigger: dict[str, Any]) -> str | None:
    """Last-ditch URL recovery: scan the watcher trigger for a URL.

    Browsers rarely put the full URL in the window title, but some sites
    (and some browser configurations) do. We only fall back here when
    the AX-tree path produced nothing, so the noise floor stays low.
    Restricted to triggers whose ``bundle_id`` looks like a browser, so
    we don't misclassify a Word document path that happens to contain
    ``https://`` as a URL.
    """
    if not _is_browser_bundle(str(trigger.get("bundle_id") or "")):
        return None
    return _extract_url_from_text(str(trigger.get("window_title") or ""))
