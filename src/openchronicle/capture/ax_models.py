"""AX Tree result dataclass and LLM-friendly Markdown rendering.

Ported from Einsia-Partner's backend/core/capture/ax_models.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AXCaptureResult:
    """Result from one accessibility tree capture cycle."""

    raw_json: dict[str, Any]
    timestamp: str
    apps: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


def ax_tree_to_markdown(ax_tree: dict[str, Any]) -> str:
    """Convert AX tree JSON into compact, LLM-friendly Markdown.

    Apps → h2, Windows → h3, elements → indented bullet points.
    Container nodes (no text) are skipped; their children promoted.
    """
    lines: list[str] = []
    for app in ax_tree.get("apps", []):
        name = app.get("name", "Unknown")
        badge = " [active]" if app.get("is_frontmost") else ""
        bundle = app.get("bundle_id", "")
        lines.append(f"## {name}{badge}")
        if bundle:
            lines.append(f"_{bundle}_")
        for win in app.get("windows", []):
            title = win.get("title", "(untitled)")
            lines.append(f"### {title}")
            _ax_elements_to_bullets(win.get("elements", []), lines, depth=0)
    return "\n".join(lines)


def ax_app_to_markdown(app_data: dict[str, Any]) -> str:
    return ax_tree_to_markdown({"apps": [app_data]})


def _ax_elements_to_bullets(
    elements: list[dict[str, Any]], lines: list[str], depth: int
) -> None:
    indent = "  " * depth
    for el in elements:
        title = (el.get("title") or "").strip()
        value = (el.get("value") or "").strip()
        role = (el.get("role") or "").replace("AX", "")
        children = el.get("children", [])

        texts = []
        if title:
            texts.append(title)
        if value and value != title:
            texts.append(value)

        if texts:
            text = " — ".join(texts)
            if role and role not in ("StaticText", "Group"):
                text = f"[{role}] {text}"
            lines.append(f"{indent}- {text}")
            if children:
                _ax_elements_to_bullets(children, lines, depth + 1)
        elif children:
            _ax_elements_to_bullets(children, lines, depth + 1)
