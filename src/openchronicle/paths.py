"""Single source of truth for on-disk OpenChronicle locations."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def root() -> Path:
    override = os.environ.get("OPENCHRONICLE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "OpenChronicle"
        return Path.home() / "AppData" / "Local" / "OpenChronicle"
    return Path.home() / ".openchronicle"


def memory_dir() -> Path:
    return root() / "memory"


def capture_buffer_dir() -> Path:
    return root() / "capture-buffer"


def logs_dir() -> Path:
    return root() / "logs"


def config_file() -> Path:
    return root() / "config.toml"


def index_db() -> Path:
    return root() / "index.db"


def pid_file() -> Path:
    return root() / ".pid"


def paused_flag() -> Path:
    return root() / ".paused"


def writer_state() -> Path:
    """Tracks last-commit timestamp and processed capture files."""
    return root() / ".writer-state.json"


def ensure_dirs() -> None:
    for d in (root(), memory_dir(), capture_buffer_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)
