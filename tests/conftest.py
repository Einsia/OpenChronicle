"""Shared pytest fixtures. All tests operate on a tmp OPENCHRONICLE_ROOT."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def ac_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "openchronicle"
    root.mkdir()
    monkeypatch.setenv("OPENCHRONICLE_ROOT", str(root))
    # Import paths after env var is set; also reset any cached modules
    from openchronicle import paths

    paths.ensure_dirs()
    return root
