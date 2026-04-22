"""Prompt templates shipped with the package. Load via `load(name)`."""

from __future__ import annotations

from importlib.resources import files


def load(name: str) -> str:
    """Read a prompt file by basename (e.g. classifier.md, compact.md)."""
    return files("openchronicle.prompts").joinpath(name).read_text(encoding="utf-8")
