"""Logging setup — three separate sinks (writer / compact / capture) + console."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import paths

_INITIALIZED = False
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _sink(name: str, filename: str, *, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fh = RotatingFileHandler(
        paths.logs_dir() / filename, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(fh)
    logger.propagate = False
    return logger


def setup(*, console: bool = True, verbose: bool = False) -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    paths.ensure_dirs()

    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(sh)

    _sink("openchronicle.writer", "writer.log", level=level)
    _sink("openchronicle.compact", "compact.log", level=level)
    _sink("openchronicle.capture", "capture.log", level=level)
    _sink("openchronicle.timeline", "timeline.log", level=level)
    _sink("openchronicle.session", "session.log", level=level)
    _sink("openchronicle.daemon", "daemon.log", level=level)
    _sink("openchronicle.mcp", "daemon.log", level=level)

    _INITIALIZED = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
