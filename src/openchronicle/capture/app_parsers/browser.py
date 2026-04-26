"""Browser URL extraction parser.

Migrated from ``s1_parser._extract_url``.  Matches known browser
bundle IDs and extracts the URL from the first ``AXTextField`` whose
value looks like a URL or bare domain.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ParseContext, S1Fields, S1Patch

_BROWSER_BUNDLES = {
    "com.google.Chrome",
    "com.apple.Safari",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.brave.Browser",
    "com.operasoftware.Opera",
}

_URL_RE = re.compile(r"https?://\S+")


class BrowserParser:
    name = "browser"
    priority = 10

    def matches(self, ctx: ParseContext, fields: S1Fields) -> bool:
        return ctx.bundle_id in _BROWSER_BUNDLES

    def parse(self, ctx: ParseContext, fields: S1Fields) -> S1Patch:
        url = _extract_url_from_app(ctx.app)
        return S1Patch(url=url)


def _extract_url_from_app(app_data: dict[str, Any]) -> str | None:
    for window in app_data.get("windows", []):
        for el in window.get("elements", []):
            if el.get("role") != "AXTextField":
                continue
            value = (el.get("value") or "").strip()
            if not value:
                continue
            if _URL_RE.search(value):
                return value
            if "." in value and " " not in value:
                return f"https://{value}"
    return None
