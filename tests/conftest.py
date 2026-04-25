"""Shared pytest fixtures. All tests operate on a tmp OPENCHRONICLE_ROOT."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the source tree is importable (editable install may be slow over network)
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


@pytest.fixture
def ac_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "openchronicle"
    root.mkdir()
    monkeypatch.setenv("OPENCHRONICLE_ROOT", str(root))
    # Import paths after env var is set; also reset any cached modules
    from openchronicle import paths

    paths.ensure_dirs()
    return root
