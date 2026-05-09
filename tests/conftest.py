"""Shared pytest fixtures. All tests operate on a tmp OPENCHRONICLE_ROOT."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest


def pytest_configure() -> None:
    # Some modules read OPENCHRONICLE_ROOT at import time; provide a safe default
    # so test collection does not depend on external environment state.
    root = Path.home() / ".codex" / "memories" / "openchronicle-test"
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPENCHRONICLE_ROOT", str(root / "openchronicle"))


@pytest.fixture
def tmp_path() -> Path:
    # The Windows sandbox environment may deny access to the default temp dir
    # (e.g. %LOCALAPPDATA%\\Temp). Override tmp_path to a known-writable root.
    root = Path.home() / ".codex" / "memories" / "openchronicle-test" / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def ac_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "openchronicle"
    root.mkdir()
    monkeypatch.setenv("OPENCHRONICLE_ROOT", str(root))
    # Import paths after env var is set; also reset any cached modules
    from openchronicle import paths

    paths.ensure_dirs()
    return root
