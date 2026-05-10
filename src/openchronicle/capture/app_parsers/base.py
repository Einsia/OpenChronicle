"""Base types for the S1 app parser registry.

Every app-specific parser implements the :class:`AppParser` protocol.
The :class:`ParseContext` gives parsers read-only access to the raw
capture data; :class:`S1Fields` holds the current state; and
:class:`S1Patch` lets a parser selectively override fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol


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


@dataclass
class ParseContext:
    """Read-only view of the raw capture data for a parser."""

    capture: dict[str, Any]
    app: dict[str, Any]
    window_meta: dict[str, Any]

    @property
    def bundle_id(self) -> str:
        return (self.app.get("bundle_id") or "").strip()

    @property
    def app_name(self) -> str:
        return (self.app.get("name") or "").strip()

    def iter_windows(self) -> Iterable[dict[str, Any]]:
        return iter(self.app.get("windows", []))

    def focused_window(self) -> dict[str, Any] | None:
        for w in self.app.get("windows", []):
            if w.get("focused"):
                return w
        return None

    def iter_elements(self) -> Iterable[dict[str, Any]]:
        """Iterate top-level elements across all windows."""
        for window in self.app.get("windows", []):
            yield from window.get("elements", [])


@dataclass
class S1Fields:
    focused_element: FocusedElement
    visible_text: str
    url: str | None = None
    app_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class S1Patch:
    focused_element: FocusedElement | None = None
    visible_text: str | None = None
    url: str | None = None
    app_context: dict[str, Any] = field(default_factory=dict)


class AppParser(Protocol):
    """Protocol for app-specific S1 field parsers.

    .. warning::

        ``matches()`` and ``parse()`` **must not** call ``register()``.
        Doing so mutates the parser list while ``apply_parsers()`` is
        iterating and will raise a ``RuntimeError``.
    """

    name: str
    priority: int

    def matches(self, ctx: ParseContext, fields: S1Fields) -> bool: ...

    def parse(self, ctx: ParseContext, fields: S1Fields) -> S1Patch: ...
