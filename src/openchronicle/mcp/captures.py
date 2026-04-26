"""Read-side helper for ``read_recent_capture``.

Reads JSON files straight out of ``~/.openchronicle/capture-buffer/`` and
returns the closest match to an optional timestamp with optional app / title
filters. Filenames are ISO timestamps (``:`` → ``-``, ``+`` → ``p``,
``-`` → ``m`` in the offset), which is enough to pre-filter by name before
opening the JSON — critical because each JSON is ~160 KB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..store import fts as fts_store


def _parse_stem(stem: str) -> datetime | None:
    """Invert ``scheduler._safe_filename``. Returns None on malformed input."""
    try:
        date_part, _, rest = stem.partition("T")
        if not rest:
            return None
        for sign, marker in (("+", "p"), ("-", "m")):
            if marker in rest:
                time_part, _, offset = rest.partition(marker)
                h, m, s = time_part.split("-")
                oh, om = offset.split("-")
                return datetime.fromisoformat(
                    f"{date_part}T{h}:{m}:{s}{sign}{oh}:{om}"
                )
        return None
    except (ValueError, IndexError):
        return None


def _parse_at(text: str) -> datetime:
    """Accept ISO timestamps or bare ``HH:MM[:SS]``. Bare times use today (local)."""
    s = text.strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        now = datetime.now().astimezone()
        today = now.date()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(s, fmt).time()
                return datetime.combine(today, t, tzinfo=now.tzinfo)
            except ValueError:
                continue
        raise ValueError(f"cannot parse time: {text!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _matches(
    data: dict[str, Any],
    app_name: str | None,
    window_title_substring: str | None,
) -> bool:
    if app_name is None and window_title_substring is None:
        return True
    meta = data.get("window_meta") or {}
    name = (meta.get("app_name") or "").lower()
    title = (meta.get("title") or "").lower()
    if app_name is not None and app_name.lower() not in name:
        return False
    return not (
        window_title_substring is not None
        and window_title_substring.lower() not in title
    )


def _load_capture(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _format_response(
    path: Path, data: dict[str, Any], include_screenshot: bool
) -> dict[str, Any]:
    meta = data.get("window_meta") or {}
    focused = data.get("focused_element") or {}
    shot = data.get("screenshot") or {}
    out: dict[str, Any] = {
        "timestamp": data.get("timestamp"),
        "file": path.name,
        "app_name": meta.get("app_name"),
        "bundle_id": meta.get("bundle_id"),
        "window_title": meta.get("title"),
        "url": data.get("url"),
        "focused_element": {
            "role": focused.get("role") or "",
            "title": focused.get("title") or "",
            "value": focused.get("value") or "",
            "is_editable": bool(focused.get("is_editable")),
            "value_length": int(focused.get("value_length") or 0),
        },
        "visible_text": data.get("visible_text") or "",
        "screenshot_stripped": bool(data.get("screenshot_stripped")),
    }
    if include_screenshot and shot.get("image_base64"):
        out["screenshot_b64"] = shot["image_base64"]
        out["screenshot_mime"] = shot.get("mime_type") or "image/jpeg"
    return out


def read_recent_capture(
    *,
    at: str | None = None,
    app_name: str | None = None,
    window_title_substring: str | None = None,
    include_screenshot: bool = False,
    max_age_minutes: int = 15,
) -> dict[str, Any] | None:
    """Return the capture that best matches the given time + filters.

    ``at`` None → newest matching capture overall.
    ``at`` set → nearest-in-time match, bounded by ``max_age_minutes`` on either side.
    """
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        return None

    target: datetime | None = _parse_at(at) if at else None

    # Filenames sort lexicographically by wall-clock time; pre-filter by name
    # range so we don't open hundreds of JSONs we don't need.
    stems = sorted(
        (p for p in buf.iterdir() if p.is_file() and p.suffix == ".json"),
        reverse=target is None,  # newest-first when no anchor time
    )

    best: tuple[float, Path, dict[str, Any]] | None = None

    for path in stems:
        ts = _parse_stem(path.stem)
        if ts is None:
            continue
        if target is not None:
            delta = abs((ts - target).total_seconds())
            if delta > max_age_minutes * 60:
                # With no ordering guarantee across timezones we can't short-
                # circuit, but the buffer is small enough post-cleanup that
                # a full pass is cheap.
                continue
        data = _load_capture(path)
        if data is None:
            continue
        if not _matches(data, app_name, window_title_substring):
            continue
        if target is None:
            return _format_response(path, data, include_screenshot)
        delta = abs((ts - target).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, path, data)

    if best is None:
        return None
    _, path, data = best
    return _format_response(path, data, include_screenshot)


# ─── search_captures + current_context (FTS-backed) ───────────────────────


def search_captures(
    *,
    query: str,
    since: str | None = None,
    until: str | None = None,
    app_name: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """BM25 + snippet search over the S1 FTS index.

    Returns a list of light-weight hits — `file_stem` is the handle to follow
    up with `read_recent_capture(at=<timestamp>, app_name=<app>)` for the
    full visible_text + screenshot.
    """
    with fts_store.cursor() as conn:
        hits = fts_store.search_captures(
            conn, query=query, since=since, until=until,
            app_name=app_name, limit=limit,
        )
    return [
        {
            "timestamp": h.timestamp,
            "app_name": h.app_name,
            "bundle_id": h.bundle_id,
            "window_title": h.window_title,
            "url": h.url,
            "snippet": h.snippet,
            "rank": h.rank,
            "file_stem": h.id,
            "focused_role": h.focused_role,
            "focused_value_preview": (h.focused_value or "")[:200],
        }
        for h in hits
    ]


def _dedupe_recent_captures(
    rows: list[fts_store.CaptureHit], *, limit: int,
) -> list[fts_store.CaptureHit]:
    """Pick up to ``limit`` rows distinct by (app_name, window_title)."""
    seen: set[tuple[str, str]] = set()
    out: list[fts_store.CaptureHit] = []
    for r in rows:
        key = (r.app_name or "", r.window_title or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _recent_timeline_blocks(
    conn: sqlite3.Connection, limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT start_time, end_time, entries, apps_used, capture_count
          FROM timeline_blocks
         ORDER BY end_time DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            entries = json.loads(r["entries"] or "[]")
        except json.JSONDecodeError:
            entries = []
        try:
            apps = json.loads(r["apps_used"] or "[]")
        except json.JSONDecodeError:
            apps = []
        out.append(
            {
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "entries": entries,
                "apps_used": apps,
                "capture_count": r["capture_count"] or 0,
            }
        )
    # Newest first looks weird in a context block; reverse to time-ordered.
    return list(reversed(out))


def current_context(
    *,
    app_filter: str | None = None,
    headline_limit: int = 5,
    fulltext_limit: int = 3,
    timeline_limit: int = 8,
) -> dict[str, Any]:
    """One-shot snapshot of "what's happening on screen right now".

    Mirrors the payload Einsia-Partner auto-injects every chat turn:

      * ``recent_captures_headline`` — last N captures as ``[HH:MM] App — Title [Role]``
      * ``recent_captures_fulltext`` — top M captures deduped by (app, window),
        carrying the FULL visible_text + focused_element.value so the model can
        actually read what's on screen
      * ``recent_timeline_blocks`` — the last K LLM-summarized 1-min blocks
    """
    with fts_store.cursor() as conn:
        rows = fts_store.recent_captures(
            conn, app_name=app_filter, limit=max(headline_limit, 30),
        )
        full_rows = _dedupe_recent_captures(rows, limit=fulltext_limit)
        full: list[dict[str, Any]] = []
        for r in full_rows:
            visible = fts_store.get_capture_visible_text(conn, r.id)
            full.append(
                {
                    "timestamp": r.timestamp,
                    "app_name": r.app_name,
                    "window_title": r.window_title,
                    "url": r.url,
                    "focused_role": r.focused_role,
                    "focused_value": r.focused_value,
                    "visible_text": visible,
                    "file_stem": r.id,
                }
            )
        timeline = _recent_timeline_blocks(conn, timeline_limit)

    headlines: list[dict[str, Any]] = []
    for r in rows[:headline_limit]:
        ts_short = (r.timestamp or "")[11:16]  # HH:MM from ISO
        headlines.append(
            {
                "time": ts_short,
                "app_name": r.app_name,
                "window_title": r.window_title,
                "focused_role": r.focused_role,
                "file_stem": r.id,
            }
        )

    return {
        "recent_captures_headline": headlines,
        "recent_captures_fulltext": full,
        "recent_timeline_blocks": timeline,
    }
