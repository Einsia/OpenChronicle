"""Classifier stage: event-daily → user-/project-/topic-/tool-/person-/org-.

Runs after the S2 reducer successfully appends a session summary to
``event-YYYY-MM-DD.md``. Reads that entry plus a small window of the
preceding entries of the same day, calls the ``classifier`` LLM stage,
and lets it drive the same tool-call loop the old routing stage used
(read_memory / search_memory / append / create / supersede / commit).

The prompt forbids writing back to ``event-*.md`` — event-daily is owned
by the reducer. The classifier's *only* job is to distill durable
facts into the non-event files.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..config import Config
from ..logger import get
from ..prompts import load as load_prompt
from ..store import entries as entries_mod
from ..store import files as files_mod
from ..store import fts
from . import llm as llm_mod
from . import tools as tools_mod

logger = get("openchronicle.writer")

# How many trailing entries from yesterday's event-daily file to carry in as
# context. One day is deliberate: the classifier has retrieval tools
# (`search_memory` / `read_memory`) and should pull more on its own if a
# specific fact seems to need older grounding.
_PRIOR_DAY_ENTRIES = 8


@dataclass
class ClassifyResult:
    session_id: str
    committed: bool = False
    summary: str = ""
    written_ids: list[str] = field(default_factory=list)
    created_paths: list[str] = field(default_factory=list)
    iterations: int = 0
    skipped_reason: str = ""


def classify_window(
    cfg: Config,
    *,
    session_id: str,
    event_daily_path: str,
    start: datetime,
    end: datetime,
    include_prior_day: bool = False,
) -> ClassifyResult:
    """Classify event-daily entries for ``session_id`` within ``[start, end)``.

    Used by two callers:
      * the 30-min classifier tick during an active session — classifies the
        window ``[classified_end or session_start, now)`` and advances
        ``classified_end`` on success.
      * the terminal classifier after session-end reduce — classifies the
        trailing window ``[classified_end or session_start, session_end)``.

    Only entries in event-daily tagged ``sid:<session_id>`` with a
    timestamp in the window count as focus entries; if none match the
    window, the tick is a silent no-op.
    """
    if not cfg.reducer.enabled:
        return ClassifyResult(session_id=session_id, skipped_reason="reducer disabled")

    with fts.cursor() as conn:
        entries_mod.write_preset_files(conn)

        focus_entries = _focus_entries_in_range(
            event_daily_path=event_daily_path,
            session_id=session_id,
            start=start,
            end=end,
        )
        if not focus_entries:
            return ClassifyResult(
                session_id=session_id,
                skipped_reason="no session entries in window",
            )

        timeline_text = _render_timeline_blocks(conn, start, end)
        prior_day_text = _render_prior_day(start) if include_prior_day else ""

        context = _assemble_context(
            event_daily_path=event_daily_path,
            focus_entries=focus_entries,
            timeline_text=timeline_text,
            prior_day_text=prior_day_text,
        )

        return _run_tool_loop(
            cfg, conn,
            session_id=session_id,
            event_daily_path=event_daily_path,
            context=context,
        )


def classify_after_reduce(
    cfg: Config,
    *,
    session_id: str,
    event_daily_path: str,
    just_written_entry_id: str = "",
    session_start: datetime | None = None,
    session_end: datetime | None = None,
    window_start: datetime | None = None,
) -> ClassifyResult:
    """Terminal-reduce classifier entry point.

    If ``window_start`` is provided (e.g. ``classified_end`` from the
    sessions table), classify only the trailing window
    ``[window_start, session_end)`` — the 30-min tick has already handled
    everything earlier in the session. Otherwise fall back to the whole
    session (behaves like the legacy callsite).
    """
    if not cfg.reducer.enabled:
        return ClassifyResult(session_id=session_id, skipped_reason="reducer disabled")

    if session_start is None or session_end is None:
        # Legacy path: no time bounds available — best we can do is classify
        # every entry tagged with this session and hope for the best.
        return _classify_untimed(
            cfg,
            session_id=session_id,
            event_daily_path=event_daily_path,
            just_written_entry_id=just_written_entry_id,
        )

    effective_start = window_start or session_start
    # Event-daily entries are appended with wall-clock "now" timestamps
    # (not the session's nominal start/end), so the focus-entry filter
    # must end at the current moment — especially on the catch-up path
    # where the reducer runs long after session_end.
    now = datetime.now().astimezone()
    window_end = max(session_end, now)
    if effective_start >= window_end:
        return ClassifyResult(
            session_id=session_id,
            skipped_reason="terminal window empty (already classified)",
        )
    return classify_window(
        cfg,
        session_id=session_id,
        event_daily_path=event_daily_path,
        start=effective_start,
        end=window_end,
        include_prior_day=True,
    )


def _classify_untimed(
    cfg: Config,
    *,
    session_id: str,
    event_daily_path: str,
    just_written_entry_id: str,
) -> ClassifyResult:
    with fts.cursor() as conn:
        entries_mod.write_preset_files(conn)
        focus_entries = _focus_entries(
            event_daily_path=event_daily_path,
            session_id=session_id,
            fallback_entry_id=just_written_entry_id,
        )
        if not focus_entries:
            return ClassifyResult(
                session_id=session_id,
                skipped_reason=f"no entries found in {event_daily_path}",
            )
        context = _assemble_context(
            event_daily_path=event_daily_path,
            focus_entries=focus_entries,
            timeline_text="",
            prior_day_text="",
        )
        return _run_tool_loop(
            cfg, conn,
            session_id=session_id,
            event_daily_path=event_daily_path,
            context=context,
        )


def _focus_entries_in_range(
    *, event_daily_path: str, session_id: str,
    start: datetime, end: datetime,
) -> list[files_mod.ParsedEntry]:
    path = files_mod.memory_path(event_daily_path)
    if not path.exists():
        return []
    try:
        parsed = files_mod.read_file(path)
    except Exception:  # noqa: BLE001
        return []
    sid_tag = f"sid:{session_id}"
    matches: list[files_mod.ParsedEntry] = []
    for e in parsed.entries:
        if sid_tag not in e.tags:
            continue
        ts = _parse_entry_ts(e.timestamp)
        if ts is None:
            # Timestamp unparseable — keep it so the classifier sees it
            # rather than silently dropping a tagged entry.
            matches.append(e)
            continue
        ts_cmp = _align_tz(ts, start)
        start_cmp = start
        end_cmp = end
        if start_cmp <= ts_cmp < end_cmp:
            matches.append(e)
    return matches


def _align_tz(ts: datetime, ref: datetime) -> datetime:
    """Make ``ts`` comparable with ``ref`` — if one is naive, make the other naive too."""
    if (ts.tzinfo is None) == (ref.tzinfo is None):
        return ts
    if ts.tzinfo is None and ref.tzinfo is not None:
        return ts.replace(tzinfo=ref.tzinfo)
    return ts.replace(tzinfo=None)


def _parse_entry_ts(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _focus_entries(
    *, event_daily_path: str, session_id: str, fallback_entry_id: str,
) -> list[files_mod.ParsedEntry]:
    """Return every entry in today's event-daily tagged with this session.

    Falls back to ``[fallback_entry_id]`` (the single last-written entry) if
    the session tag is missing — keeps behaviour sane even if the tag
    convention shifts.
    """
    path = files_mod.memory_path(event_daily_path)
    if not path.exists():
        return []
    try:
        parsed = files_mod.read_file(path)
    except Exception:  # noqa: BLE001
        return []
    sid_tag = f"sid:{session_id}"
    matches = [e for e in parsed.entries if sid_tag in e.tags]
    if matches:
        return matches
    for e in parsed.entries:
        if e.id == fallback_entry_id:
            return [e]
    return [parsed.entries[-1]] if parsed.entries else []


def _render_timeline_blocks(
    conn: sqlite3.Connection, start: datetime, end: datetime,
) -> str:
    rows = conn.execute(
        """
        SELECT start_time, end_time, entries, apps_used
          FROM timeline_blocks
         WHERE end_time > ? AND start_time < ?
         ORDER BY start_time ASC
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    if not rows:
        return "(no timeline blocks recorded for this session)"
    out: list[str] = []
    for r in rows:
        try:
            s = datetime.fromisoformat(r["start_time"]).strftime("%H:%M")
            e = datetime.fromisoformat(r["end_time"]).strftime("%H:%M")
        except (TypeError, ValueError):
            s, e = r["start_time"], r["end_time"]
        entries = json.loads(r["entries"] or "[]")
        header = f"[{s}-{e}]"
        if not entries:
            out.append(f"{header} (no notable activity)")
            continue
        out.append(header)
        out.extend(f"  - {entry}" for entry in entries)
    return "\n".join(out)


def _render_prior_day(session_start: datetime) -> str:
    prior_date = (session_start - timedelta(days=1)).strftime("%Y-%m-%d")
    name = f"event-{prior_date}.md"
    path = files_mod.memory_path(name)
    if not path.exists():
        return ""
    try:
        parsed = files_mod.read_file(path)
    except Exception:  # noqa: BLE001
        return ""
    tail = parsed.entries[-_PRIOR_DAY_ENTRIES:]
    if not tail:
        return ""
    out: list[str] = [f"From {name} (last {len(tail)} entries):", ""]
    for e in tail:
        out.append(f"### [{e.timestamp}] {{id: {e.id}}}")
        body = e.body.strip()
        if body:
            out.append(body)
        out.append("")
    return "\n".join(out).strip()


def _assemble_context(
    *,
    event_daily_path: str,
    focus_entries: list[files_mod.ParsedEntry],
    timeline_text: str,
    prior_day_text: str,
) -> str:
    parts: list[str] = [f"Source file: {event_daily_path}", ""]
    parts.append("## Session entries (focus — classify these)")
    for e in focus_entries:
        parts.append(f"### [{e.timestamp}] {{id: {e.id}}}")
        body = e.body.strip()
        if body:
            parts.append(body)
        parts.append("")
    if timeline_text:
        parts.append("## Timeline blocks covering this session")
        parts.append(
            "These are the verbatim-preserving activity slices the reducer compressed. "
            "Use them to ground any durable fact you're considering writing — "
            "or to skip a fact that the compressed entry overstates."
        )
        parts.append("")
        parts.append(timeline_text)
        parts.append("")
    if prior_day_text:
        parts.append("## Preceding day (context, dedup anchor)")
        parts.append(prior_day_text)
        parts.append("")
    parts.append(
        "If you need earlier history or adjacent entity files, call "
        "`search_memory` or `read_memory` — don't guess."
    )
    return "\n".join(parts).strip()


def _render_index(conn: sqlite3.Connection) -> str:
    active = fts.list_files(conn, include_dormant=False, include_archived=False)
    if not active:
        return "(no non-event memory files yet — create them as needed)"
    # Classifier never touches event-*; show only the files it can
    # actually write to so it doesn't get tempted.
    filtered = [f for f in active if not f.path.startswith("event-")]
    if not filtered:
        return "(no non-event memory files yet — create them as needed)"
    lines = ["Active non-event memory files:"]
    for f in filtered[:30]:
        lines.append(
            f"- {f.path}  # {f.description}  "
            f"(tags: {f.tags}; entries: {f.entry_count}; updated: {f.updated})"
        )
    return "\n".join(lines)


def _run_tool_loop(
    cfg: Config,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    event_daily_path: str,
    context: str,
) -> ClassifyResult:
    system = load_prompt("classifier.md")
    schema = load_prompt("schema.md")
    index = _render_index(conn)

    user_msg = (
        f"# Schema\n\n{schema}\n\n"
        f"# Memory index\n\n{index}\n\n"
        f"# Event-daily context\n\n{context}\n\n"
        f"Source file (do NOT write to it): {event_daily_path}\n"
        f"Session being classified: {session_id}"
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    state = tools_mod.CommitState()
    max_iter = cfg.writer.max_tool_iterations

    for iteration in range(max_iter):
        try:
            resp = llm_mod.call_llm(
                cfg, "classifier",
                messages=messages,
                tools=tools_mod.TOOL_SCHEMAS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "classifier %s: LLM call failed at iter %d: %s",
                session_id, iteration, exc,
            )
            break

        tool_calls = llm_mod.extract_tool_calls(resp)
        text = llm_mod.extract_text(resp)

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": c["id"] or f"call_{iteration}_{i}",
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                    },
                }
                for i, c in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            logger.info("classifier %s: ended without commit at iter %d", session_id, iteration)
            break

        for i, call in enumerate(tool_calls):
            name = call["name"]
            args = call["arguments"] or {}
            # Hard guard: never let the classifier write back to event-*.
            if name in {"append", "create", "supersede", "flag_compact"}:
                target_path = str(args.get("path") or "")
                if target_path.startswith("event-"):
                    result = {
                        "error": (
                            f"forbidden: classifier cannot write to {target_path}. "
                            "event-daily is owned by the reducer."
                        ),
                    }
                    messages.append(_tool_response(assistant_msg, i, name, result))
                    continue

            if name not in tools_mod.TOOL_NAMES:
                result = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = tools_mod.dispatch(
                        name, args, conn=conn,
                        soft_limit_tokens=cfg.writer.soft_limit_tokens,
                        state=state,
                    )
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"tool crashed: {exc}"}
                    logger.exception("classifier tool %s failed", name)
            messages.append(_tool_response(assistant_msg, i, name, result))

        if state.committed:
            return ClassifyResult(
                session_id=session_id,
                committed=True,
                summary=state.summary,
                written_ids=list(state.written_ids),
                created_paths=list(state.created_paths),
                iterations=iteration + 1,
            )

    return ClassifyResult(
        session_id=session_id,
        committed=state.committed,
        summary=state.summary,
        written_ids=list(state.written_ids),
        created_paths=list(state.created_paths),
        iterations=max_iter,
    )


def _tool_response(
    assistant_msg: dict[str, Any], i: int, name: str, result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": assistant_msg["tool_calls"][i]["id"],
        "name": name,
        "content": json.dumps(result, ensure_ascii=False),
    }
