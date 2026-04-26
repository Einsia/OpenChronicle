"""Build one TimelineBlock from a short (default 1-minute) window of captures.

Reads capture-buffer JSON files whose ``timestamp`` falls inside the
window, renders them into a prompt, and asks the LLM to produce a
small list of self-contained ``[App] …`` lines. Idempotent: skips
windows that already have a block.

The prompt reads the structured S1 fields (``focused_element``,
``visible_text``, ``url``) written by ``capture/s1_parser.py`` rather
than re-rendering the raw AX tree. Pre-v2 captures without those
fields are back-rendered via ``ax_tree_to_markdown`` as a fallback.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import paths
from ..capture.ax_models import ax_tree_to_markdown
from ..config import Config
from ..logger import get
from ..prompts import load as load_prompt
from ..writer import llm as llm_mod
from . import store

logger = get("openchronicle.timeline")

# Per-capture slice that goes into the timeline prompt. S1 parser
# already caps visible_text at 10k; the timeline prompt is now a
# verbatim-preserving normalizer, so we want to keep as much as the
# context budget allows. 1-min windows rarely carry more than ~6
# captures in practice.
_PER_CAPTURE_TEXT_LIMIT = 4000
# Defensive ceiling: if something goes haywire and a 1-min window has
# 30+ captures, keep the newest ones. Later events are more recent and
# tend to be more informative.
_MAX_EVENTS_PER_WINDOW = 30


def _capture_stem_in_window(stem: str, start: datetime, end: datetime) -> bool:
    """Parse the filename stem back to a datetime and check window membership."""
    ts = _stem_to_dt(stem)
    if ts is None:
        return False
    return start <= ts < end


def _stem_to_dt(stem: str) -> datetime | None:
    # Capture filenames look like ``2026-04-21T17-07-32p08-00`` or
    # ``…m05-00`` for negative offsets. Reverse the sanitisation that
    # scheduler.py applied so fromisoformat can parse it.
    if len(stem) < 20:
        return None
    try:
        date_part = stem[:10]
        time_part = stem[11:19].replace("-", ":")
        offset = stem[19:]
        if offset.startswith("p"):
            tz = "+" + offset[1:].replace("-", ":")
        elif offset.startswith("m"):
            tz = "-" + offset[1:].replace("-", ":")
        else:
            tz = ""
        iso = f"{date_part}T{time_part}{tz}"
        return datetime.fromisoformat(iso)
    except (ValueError, IndexError):
        return None


def captures_in_window(start: datetime, end: datetime) -> list[Path]:
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        return []
    files: list[Path] = []
    for p in sorted(buf.iterdir()):
        if p.suffix != ".json" or not p.is_file():
            continue
        if _capture_stem_in_window(p.stem, start, end):
            files.append(p)
    return files


def _load_captures(capture_files: list[Path]) -> list[tuple[Path, dict]]:
    """Parse every capture JSON once. Files that fail to read/parse are dropped.

    The window is small (≤30 files) so the entire parsed list stays cheap to
    pass around; the win is avoiding a second ``json.loads`` per file when
    ``_heuristic_entries`` runs after the LLM returns no usable output.
    """
    parsed: list[tuple[Path, dict]] = []
    for p in capture_files:
        # read_bytes() + json.loads handles BOM/encoding sniffing; read_text()
        # would raise UnicodeDecodeError (a ValueError, not OSError) on a
        # mis-encoded file and crash the aggregator instead of dropping it.
        try:
            data = json.loads(p.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("timeline: failed to load capture %s: %s", p.name, exc)
            continue
        if not isinstance(data, dict):
            logger.warning("timeline: capture %s is not a JSON object", p.name)
            continue
        parsed.append((p, data))
    return parsed


def _format_events(parsed: list[tuple[Path, dict]]) -> tuple[str, list[str]]:
    """Render captures for the timeline prompt. Returns (events_text, apps_used).

    Reads the structured S1 fields written by ``capture/s1_parser.py`` —
    ``focused_element``, ``visible_text``, ``url`` — and lays them out in
    the one-line-per-capture format matching Einsia's S1 prompt rendering.
    Pre-v2 captures without those fields fall back to a bounded
    ``ax_tree_to_markdown`` render so historical buffer contents still work.
    """
    lines: list[str] = []
    apps: set[str] = set()

    files = parsed[-_MAX_EVENTS_PER_WINDOW:]
    for i, (p, data) in enumerate(files, 1):
        ts_raw = str(data.get("timestamp", p.stem))
        ts = _short_time(ts_raw)

        wm = data.get("window_meta") or {}
        app = str(wm.get("app_name") or "Unknown")
        title = str(wm.get("title") or "")
        bundle = str(wm.get("bundle_id") or "")
        if app:
            apps.add(app)

        trigger = data.get("trigger") or {}
        event_type = str(trigger.get("event_type") or "")

        parts = [f"{i}. [{ts}] {app}"]
        if title:
            parts.append(f"— {title}")
        if bundle:
            parts.append(f"({bundle})")

        url = data.get("url")
        if url:
            parts.append(f"(URL: {url})")

        fe = data.get("focused_element") or {}
        role = str(fe.get("role") or "")
        if role:
            role_desc = f"[{role}]"
            if fe.get("is_editable"):
                role_desc += " (editing)"
            fe_title = str(fe.get("title") or "")
            if fe_title:
                role_desc += f" title={fe_title[:80]}"
            value_length = int(fe.get("value_length") or 0)
            if value_length:
                role_desc += f" len={value_length}"
            value = str(fe.get("value") or "")
            if value:
                role_desc += f": {value}"
            parts.append(role_desc)

        if event_type:
            parts.append(f"<{event_type}>")

        lines.append(" ".join(parts))

        visible_text = data.get("visible_text")
        if visible_text is None:
            # Pre-v2 capture — fall back to rendering the raw AX tree.
            ax = data.get("ax_tree")
            visible_text = ax_tree_to_markdown(ax) if ax else ""
        visible_text = str(visible_text).strip()
        if visible_text:
            if len(visible_text) > _PER_CAPTURE_TEXT_LIMIT:
                visible_text = visible_text[:_PER_CAPTURE_TEXT_LIMIT] + "\n…(truncated)"
            preview = visible_text.replace("\n", " ")
            lines.append(f"| {preview}")

        lines.append("")
    return "\n".join(lines).strip(), sorted(apps)


def _short_time(ts: str) -> str:
    """`2026-04-21T17:07:32+08:00` → `17:07:32`. Best-effort only."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except ValueError:
        return ts[:19]


def _format_window(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def produce_block_for_window(
    cfg: Config,
    conn,
    *,
    start: datetime,
    end: datetime,
) -> store.TimelineBlock | None:
    """Build one block. Returns ``None`` if the window is empty or already done."""
    if store.has_window(conn, start, end):
        logger.debug(
            "timeline: window %s → %s already has a block", start.isoformat(), end.isoformat()
        )
        return None

    capture_files = captures_in_window(start, end)
    if not capture_files:
        logger.info(
            "timeline: window %s → %s has 0 captures, skipping",
            start.isoformat(), end.isoformat(),
        )
        return None

    # Parse capture JSON once; reused for prompt rendering AND the heuristic
    # fallback so an LLM miss doesn't trigger a second pass over the same files.
    parsed = _load_captures(capture_files)
    events_text, apps_used = _format_events(parsed)
    # Use len(parsed) — capture_count must match what the LLM actually sees
    # and what _heuristic_entries can group; len(capture_files) overcounts
    # whenever _load_captures drops a corrupt or non-dict file.
    capture_count = len(parsed)
    prompt = load_prompt("timeline_block.md").format(
        start_time=_format_window(start),
        end_time=_format_window(end),
        capture_count=capture_count,
        events_text=events_text,
    )

    entries: list[str] = []
    try:
        resp = llm_mod.call_llm(
            cfg,
            "timeline",
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        text = llm_mod.extract_text(resp).strip()
        data = json.loads(text) if text else {}
        raw = data.get("entries") if isinstance(data, dict) else None
        if isinstance(raw, list):
            entries = [str(e).strip() for e in raw if str(e).strip()]
    except json.JSONDecodeError as exc:
        logger.warning("timeline: malformed JSON from LLM: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("timeline: LLM call failed: %s", exc)

    if not entries:
        entries = _heuristic_entries(parsed)

    block = store.TimelineBlock(
        start_time=start,
        end_time=end,
        timezone=start.tzname() or "",
        entries=entries,
        apps_used=apps_used,
        capture_count=capture_count,
    )
    store.insert(conn, block)
    logger.info(
        "timeline: stored block %s — %s → %s (%d entries, %d captures, apps=%s)",
        block.id, start.isoformat(), end.isoformat(),
        len(entries), capture_count, ", ".join(apps_used),
    )
    return block


def _heuristic_entries(parsed: list[tuple[Path, dict]]) -> list[str]:
    """Cheap fallback when the LLM returns no parseable entries."""
    groups: list[tuple[str, str, int]] = []
    for _p, data in parsed:
        wm = data.get("window_meta") or {}
        app = str(wm.get("app_name") or "Unknown")
        title = str(wm.get("title") or "")
        if groups and groups[-1][0] == app and groups[-1][1] == title:
            groups[-1] = (app, title, groups[-1][2] + 1)
        else:
            groups.append((app, title, 1))

    entries: list[str] = []
    for app, title, _count in groups:
        if title:
            entries.append(f"[{app}] worked in window '{title}', involving —")
        else:
            entries.append(f"[{app}] active, involving —")
    return entries
