"""Shared pytest fixtures. All tests operate on a tmp OPENCHRONICLE_ROOT."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_app_parser_registry() -> None:
    """Restore builtin parsers before each test so registry mutations
    in one test do not leak into another."""
    from openchronicle.capture.app_parsers import _reset_registry

    _reset_registry()


@pytest.fixture
def ac_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "openchronicle"
    root.mkdir()
    monkeypatch.setenv("OPENCHRONICLE_ROOT", str(root))
    # Import paths after env var is set; also reset any cached modules
    from openchronicle import paths

    paths.ensure_dirs()
    return root
