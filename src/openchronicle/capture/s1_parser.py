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

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
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
}

_EDITOR_BUNDLES = {
    "com.microsoft.VSCode",
    "com.microsoft.VSCodeInsiders",
    "com.todesktop.230313mzl4w4u92",  # Cursor (Electron)
    "com.codeium.windsurf",            # Windsurf
    "com.cursor.Cursor",               # Cursor (alt)
}

_TERMINAL_BUNDLES = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "dev.warp.Warp-Stable",
    "com.alacritty.Alacritty",
    "org.alacritty",
    "co.zeit.hyper",
    "net.kovidgoyal.kitty",
}

# Map bundle_id → trailing display-name suffix in window titles.
_EDITOR_DISPLAY_SUFFIXES = {
    "com.microsoft.VSCode":         " - Visual Studio Code",
    "com.microsoft.VSCodeInsiders": " - Visual Studio Code - Insiders",
    "com.todesktop.230313mzl4w4u92": " - Cursor",
    "com.codeium.windsurf":          " - Windsurf",
    "com.cursor.Cursor":             " - Cursor",
}

_URL_RE = re.compile(r"https?://\S+")
# Match [git:branch] or [WSL:distro] or bare [branch] in editor titles.
_BRACKET_BRANCH_RE = re.compile(r"\[(git:|WSL:)?([^\]]+)\]")

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
    """Mutate ``capture`` in place: add ``focused_element`` / ``visible_text`` / ``url``
    plus app-specific fields (``editor_file`` / ``editor_project`` / ``editor_git_branch`` /
    ``terminal_cwd``) when the frontmost app is a known editor or terminal.

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
        capture["editor_file"] = None
        capture["editor_project"] = None
        capture["editor_git_branch"] = None
        capture["terminal_cwd"] = None
        return

    capture["focused_element"] = _extract_focused_element(app_data).to_dict()
    capture["visible_text"] = _render_visible_text(app_data)
    capture["url"] = _extract_url(app_data)

    # ── App-specific S1 fields ──────────────────────────────────────────
    bundle = (app_data.get("bundle_id") or "").strip()

    title = _get_window_title(app_data, capture)

    if bundle in _EDITOR_BUNDLES and title:
        editor_info = _extract_editor_info(title, bundle)
        capture["editor_file"] = editor_info[0]
        capture["editor_project"] = editor_info[1]
        capture["editor_git_branch"] = editor_info[2]
    else:
        capture["editor_file"] = None
        capture["editor_project"] = None
        capture["editor_git_branch"] = None

    if bundle in _TERMINAL_BUNDLES and title:
        capture["terminal_cwd"] = _extract_terminal_cwd(title)
    else:
        capture["terminal_cwd"] = None


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
    if bundle not in _BROWSER_BUNDLES:
        return None
    for window in app_data.get("windows", []):
        for el in window.get("elements", []):
            if el.get("role") != "AXTextField":
                continue
            value = (el.get("value") or "").strip()
            if not value:
                continue
            if _URL_RE.search(value):
                return value
            if "." in value and " " not in value:
                return f"https://{value}"
    return None


# ── App-specific S1 helpers ───────────────────────────────────────────────────


def _get_window_title(app_data: dict[str, Any], capture: dict[str, Any]) -> str:
    """Best-effort window title for the frontmost app.

    Prefers ``window_meta.title`` (osascript — faster and avoids AX noise),
    falls back to the first focused window title in the AX tree.
    """
    wm = capture.get("window_meta") or {}
    title = (wm.get("title") or "").strip()
    if title:
        return title
    for win in app_data.get("windows", []):
        if win.get("focused"):
            return (win.get("title") or "").strip()
    return ""


def _extract_editor_info(
    title: str, bundle_id: str
) -> tuple[str | None, str | None, str | None]:
    """Parse an editor window title into ``(file, project, git_branch)``.

    Handles the common VS Code / Cursor / Windsurf title patterns::

        main.py — project-name - Visual Studio Code
        app.ts — website [git:feat/auth] - Cursor
        file.rs — project [WSL:Ubuntu] - Visual Studio Code
        main.py - Visual Studio Code                         (no project)
    """
    # 1. Strip the trailing " - <AppDisplayName>" suffix.
    suffix = _EDITOR_DISPLAY_SUFFIXES.get(bundle_id)
    if suffix and title.endswith(suffix):
        core = title[: -len(suffix)]
    else:
        core = title
        # Fallback: try each known suffix in case bundle_id didn't match
        # but we still have a recognisable title (e.g. a new fork).
        for known_suffix in _EDITOR_DISPLAY_SUFFIXES.values():
            if core.endswith(known_suffix):
                core = core[: -len(known_suffix)]
                break

    core = core.strip()
    if not core:
        return None, None, None

    # 2. Extract bracket annotation ([git:...], [WSL:...], [main]).
    branch: str | None = None
    m = _BRACKET_BRANCH_RE.search(core)
    if m:
        prefix = m.group(1) or ""
        branch = prefix + m.group(2)
        # Remove the bracket block from core so it doesn't pollute project/filename.
        core = (core[: m.start()] + core[m.end() :]).strip()

    # 3. Split on em dash (U+2014) to separate file from project.
    if " — " in core:
        file_part, _, project_part = core.partition(" — ")
        file_part = _clean_file_token(file_part)
        project_part = project_part.strip()
        return file_part or None, project_part or None, branch

    # 4. No em dash — try ASCII " - " as a weaker separator.
    #    Only split when both sides look meaningful (avoid splitting
    #    filenames like "my-app.ts").
    if " - " in core:
        left, _, right = core.partition(" - ")
        if _looks_like_filename(left) and _looks_like_filename(right):
            return _clean_file_token(right) or None, _clean_file_token(left) or None, branch

    # 5. No recognisable separator — the entire title is the filename.
    file_part = _clean_file_token(core)
    return file_part or None, None, branch


def _clean_file_token(token: str) -> str:
    """Remove noise suffixes like ``(diff)``, ``(read-only)`` from a file token."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", token.strip()).strip()


def _looks_like_filename(token: str) -> bool:
    """Heuristic: does ``token`` plausibly look like a file or project name?"""
    token = token.strip()
    return bool(token) and not token.startswith("[") and len(token) >= 2


def _extract_terminal_cwd(title: str) -> str | None:
    """Extract the current working directory from a terminal window title.

    Terminal titles vary by emulator and shell config.  Common patterns::

        vim — ~/projects/foo — zsh               (iTerm2 default)
        ~/projects/foo — zsh — 80x24
        user@host: /var/www                        (SSH)
        Terminal                                    (no path — returns None)
    """
    # Split on common title separators and look for the first path-like token.
    tokens = re.split(r"\s*[—–\-]\s*", title)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        # SSH-style: user@host:/path (optional whitespace after colon).
        ssh_m = re.match(r"^[^@]+@[^:]+:\s*(/.+)$", token)
        if ssh_m:
            return ssh_m.group(1)
        # Local path: ~/…, /…, ./…
        if token.startswith(("~/", "./", "/")):
            expanded = os.path.expanduser(token)
            return str(Path(expanded).resolve())
    return None
