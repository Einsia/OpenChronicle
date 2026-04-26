"""S1 app parser registry.

Parsers are registered at import time and run in priority order during
:func:`apply_parsers`.  Later parsers can match on fields produced by
earlier parsers (e.g. a Linear parser matching ``fields.url`` that
contains ``linear.app``, which was extracted by the browser parser).
"""

from __future__ import annotations

from ...logger import get
from .base import AppParser, ParseContext, S1Fields
from .browser import BrowserParser

logger = get("openchronicle.capture.s1_registry")

_parsers: list[AppParser] = []


def _register_builtins() -> None:
    register(BrowserParser())


def register(parser: AppParser) -> None:
    _parsers.append(parser)
    _parsers.sort(key=lambda p: p.priority)


def _reset_registry() -> None:
    """Clear all registered parsers and re-register builtins.

    Intended for test isolation so registry mutations in one test
    do not leak into another.
    """
    _parsers.clear()
    _register_builtins()


def apply_parsers(ctx: ParseContext, fields: S1Fields) -> None:
    for parser in _parsers:
        try:
            if parser.matches(ctx, fields):
                patch = parser.parse(ctx, fields)
                if patch.focused_element is not None:
                    fields.focused_element = patch.focused_element
                if patch.visible_text is not None:
                    fields.visible_text = patch.visible_text
                if patch.url is not None:
                    fields.url = patch.url
                if patch.app_context:
                    fields.app_context = {**fields.app_context, **patch.app_context}
        except Exception:
            logger.exception("S1 parser %r failed", parser.name)


_register_builtins()
