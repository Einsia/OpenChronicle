"""Writer tool implementations + JSON Schema declarations for the LLM."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..logger import get
from ..store import entries as entries_mod
from ..store import files as files_mod
from ..store import fts

logger = get("openchronicle.writer")


@dataclass
class CommitState:
    committed: bool = False
    summary: str = ""
    written_ids: list[str] = field(default_factory=list)
    created_paths: list[str] = field(default_factory=list)
    flagged_compact: list[str] = field(default_factory=list)


# ─── tool implementations ────────────────────────────────────────────────

def tool_read_memory(conn: sqlite3.Connection, *, path: str, tail_n: int = 10) -> dict[str, Any]:
    p = files_mod.memory_path(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}
    parsed = files_mod.read_file(p)
    tail = parsed.entries[-tail_n:] if tail_n > 0 else parsed.entries
    return {
        "path": path,
        "description": parsed.description,
        "tags": parsed.tags,
        "status": parsed.status,
        "entry_count": parsed.entry_count,
        "updated": parsed.updated,
        "entries": [
            {"id": e.id, "timestamp": e.timestamp, "tags": e.tags, "body": e.body,
             "superseded_by": e.superseded_by}
            for e in tail
        ],
    }


def tool_search_memory(
    conn: sqlite3.Connection,
    *,
    query: str,
    top_k: int = 5,
    include_superseded: bool = False,
) -> dict[str, Any]:
    hits = fts.search(
        conn, query=query, top_k=top_k, include_superseded=include_superseded
    )
    return {
        "query": query,
        "results": [
            {"id": h.id, "path": h.path, "timestamp": h.timestamp,
             "content": h.content, "rank": h.rank}
            for h in hits
        ],
    }


def tool_append(
    conn: sqlite3.Connection,
    *,
    path: str,
    content: str,
    tags: list[str],
    soft_limit_tokens: int,
    state: CommitState,
) -> dict[str, Any]:
    try:
        entry_id = entries_mod.append_entry(
            conn, name=path, content=content, tags=tags,
            soft_limit_tokens=soft_limit_tokens,
        )
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}
    state.written_ids.append(entry_id)
    return {"ok": True, "id": entry_id, "path": path}


def tool_create(
    conn: sqlite3.Connection,
    *,
    path: str,
    description: str,
    tags: list[str],
    state: CommitState,
) -> dict[str, Any]:
    try:
        entries_mod.create_file(conn, name=path, description=description, tags=tags)
    except (FileExistsError, ValueError) as exc:
        return {"error": str(exc)}
    state.created_paths.append(path)
    return {"ok": True, "path": path}


def tool_supersede(
    conn: sqlite3.Connection,
    *,
    path: str,
    old_entry_id: str,
    new_content: str,
    reason: str,
    tags: list[str] | None,
    state: CommitState,
) -> dict[str, Any]:
    try:
        new_id = entries_mod.supersede_entry(
            conn,
            name=path,
            old_entry_id=old_entry_id,
            new_content=new_content,
            reason=reason,
            tags=tags,
        )
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}
    state.written_ids.append(new_id)
    return {"ok": True, "new_id": new_id}


def tool_flag_compact(
    conn: sqlite3.Connection, *, path: str, reason: str, state: CommitState
) -> dict[str, Any]:
    p = files_mod.memory_path(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}
    fts.set_needs_compact(conn, p.name, True)
    files_mod.update_frontmatter(p, {"needs_compact": True})
    state.flagged_compact.append(path)
    logger.info("flag_compact: %s (%s)", path, reason)
    return {"ok": True}


def tool_commit(state: CommitState, *, summary: str) -> dict[str, Any]:
    state.committed = True
    state.summary = summary
    return {"ok": True}


# ─── JSON Schema declarations (OpenAI tool format) ───────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": "Read a memory file (frontmatter + last N entries).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "e.g. 'project-openchronicle.md'"},
                    "tail_n": {"type": "integer", "default": 10},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "BM25 full-text search across all memory. Use to dedup before appending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                    "include_superseded": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append",
            "description": "Append a new entry to a memory file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "1–3 sentence self-contained fact"},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                },
                "required": ["path", "content", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create",
            "description": (
                "Create a new memory file. Filename prefix must be one of: "
                "user-, project-, tool-, topic-, person-, org-, event-."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "description": {"type": "string", "description": "One-line description; required"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path", "description", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "supersede",
            "description": "Mark an old entry as superseded and append the replacement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_entry_id": {"type": "string"},
                    "new_content": {"type": "string"},
                    "reason": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path", "old_entry_id", "new_content", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_compact",
            "description": "Flag a file for the next compaction pass.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["path", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit",
            "description": "Finish this round. Call exactly once at the end.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One-line summary of what you wrote."},
                },
                "required": ["summary"],
            },
        },
    },
]


TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}


def dispatch(
    name: str,
    args: dict[str, Any],
    *,
    conn: sqlite3.Connection,
    soft_limit_tokens: int,
    state: CommitState,
) -> dict[str, Any]:
    if name == "read_memory":
        return tool_read_memory(conn, path=args["path"], tail_n=args.get("tail_n", 10))
    if name == "search_memory":
        return tool_search_memory(
            conn,
            query=args["query"],
            top_k=args.get("top_k", 5),
            include_superseded=args.get("include_superseded", False),
        )
    if name == "append":
        return tool_append(
            conn,
            path=args["path"],
            content=args["content"],
            tags=list(args.get("tags", []) or []),
            soft_limit_tokens=soft_limit_tokens,
            state=state,
        )
    if name == "create":
        return tool_create(
            conn,
            path=args["path"],
            description=args["description"],
            tags=list(args.get("tags", []) or []),
            state=state,
        )
    if name == "supersede":
        return tool_supersede(
            conn,
            path=args["path"],
            old_entry_id=args["old_entry_id"],
            new_content=args["new_content"],
            reason=args["reason"],
            tags=list(args.get("tags") or []) or None,
            state=state,
        )
    if name == "flag_compact":
        return tool_flag_compact(
            conn, path=args["path"], reason=args.get("reason", ""), state=state
        )
    if name == "commit":
        return tool_commit(state, summary=args.get("summary", ""))
    return {"error": f"unknown tool: {name}"}
