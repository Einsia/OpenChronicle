"""Entry-level operations: create file, append, supersede. Syncs FTS5 on every write."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter

from ..logger import get
from . import files as files_mod
from . import fts

logger = get("openchronicle.store")


def _now_iso_minute() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")


def make_id(timestamp: str) -> str:
    """YYYYMMDD-HHMM-<6-hex>.

    6 hex chars (24 bits) keeps collision probability <0.1% within a single
    minute even under heavy batched writes.
    """
    compact = timestamp.replace("-", "").replace(":", "").replace("T", "-")[:13]
    salt = hashlib.blake2s(os.urandom(8), digest_size=3).hexdigest()
    return f"{compact}-{salt}"


def _ensure_prefix(path_name: str) -> str:
    return files_mod.validate_prefix(path_name)


def create_file(
    conn: sqlite3.Connection, *, name: str, description: str, tags: list[str]
) -> Path:
    if not description.strip():
        raise ValueError("description is required")
    prefix = _ensure_prefix(name)
    path = files_mod.memory_path(name)
    if path.exists():
        raise FileExistsError(f"{path.name} already exists")

    fm = files_mod.default_frontmatter(description=description, tags=tags)
    files_mod.write_file(path, fm, body="")
    fts.upsert_file(
        conn,
        fts.FileRow(
            path=path.name,
            prefix=prefix,
            description=description,
            tags=" ".join(tags),
            status="active",
            entry_count=0,
            created=fm["created"],
            updated=fm["updated"],
            needs_compact=0,
        ),
    )
    logger.info("created file: %s", path.name)
    return path


def append_entry(
    conn: sqlite3.Connection,
    *,
    name: str,
    content: str,
    tags: list[str],
    soft_limit_tokens: int | None = None,
) -> str:
    """Append a new entry, returning its id."""
    path = files_mod.memory_path(name)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} does not exist; call create_file first")
    prefix = _ensure_prefix(name)

    ts = _now_iso_minute()
    entry_id = make_id(ts)
    heading = files_mod.render_heading(timestamp=ts, entry_id=entry_id, tags=tags)
    body = content.strip()

    # Append to file
    post = frontmatter.load(path)
    current = post.content.rstrip()
    new_block = f"\n\n{heading}\n{body}\n" if current else f"{heading}\n{body}\n"
    post.content = current + new_block
    post.metadata["entry_count"] = int(post.metadata.get("entry_count", 0)) + 1
    post.metadata["updated"] = files_mod.today()

    # Soft limit check
    if soft_limit_tokens is not None:
        est_tokens = len(post.content) // 4
        if est_tokens > soft_limit_tokens and not post.metadata.get("needs_compact"):
            post.metadata["needs_compact"] = True
            logger.info("flagged %s for compact (est %d tokens > %d)",
                        path.name, est_tokens, soft_limit_tokens)

    path.write_text(frontmatter.dumps(post) + "\n")

    # Update FTS
    fts.insert_entry(
        conn,
        id=entry_id,
        path=path.name,
        prefix=prefix,
        timestamp=ts,
        tags=" ".join(tags),
        content=body,
        superseded=0,
    )
    fts.upsert_file(
        conn,
        fts.FileRow(
            path=path.name,
            prefix=prefix,
            description=str(post.metadata.get("description", "")),
            tags=" ".join(post.metadata.get("tags", []) or []),
            status=str(post.metadata.get("status", "active")),
            entry_count=int(post.metadata.get("entry_count", 0)),
            created=str(post.metadata.get("created", "")),
            updated=str(post.metadata.get("updated", "")),
            needs_compact=1 if post.metadata.get("needs_compact") else 0,
        ),
    )
    return entry_id


def supersede_entry(
    conn: sqlite3.Connection,
    *,
    name: str,
    old_entry_id: str,
    new_content: str,
    reason: str,
    tags: list[str] | None = None,
) -> str:
    """Mark old entry superseded and append the new one. Returns new entry id."""
    path = files_mod.memory_path(name)
    if not path.exists():
        raise FileNotFoundError(path.name)

    parsed = files_mod.read_file(path)
    target = next((e for e in parsed.entries if e.id == old_entry_id), None)
    if target is None:
        raise ValueError(f"entry {old_entry_id} not found in {path.name}")

    # Build replacement heading and body in the file
    ts = _now_iso_minute()
    new_id = make_id(ts)

    new_heading = files_mod.render_heading(
        timestamp=ts, entry_id=new_id, tags=tags or target.tags
    )

    # Modify file text directly to preserve formatting
    text = path.read_text()
    # 1) append #superseded-by to old heading (only if not already present)
    old_heading = target.heading_line
    if f"superseded-by:{new_id}" not in old_heading:
        updated_heading = old_heading.rstrip() + f" #superseded-by:{new_id}"
        text = text.replace(old_heading, updated_heading, 1)
    # 2) wrap old body in ~~...~~ (only if not already)
    if target.body and not target.body.startswith("~~"):
        striked = "~~" + target.body.strip() + "~~"
        text = text.replace(target.body, striked, 1)

    # 3) Append the new entry at the end
    body = new_content.strip()
    new_block = f"\n\n{new_heading}\n{body}\n<!-- supersedes: {old_entry_id}; reason: {reason} -->\n"
    if not text.endswith("\n"):
        text += "\n"
    text += new_block
    path.write_text(text)

    # Rebuild frontmatter counts (re-parse to be safe)
    post = frontmatter.load(path)
    post.metadata["entry_count"] = int(post.metadata.get("entry_count", 0)) + 1
    post.metadata["updated"] = files_mod.today()
    path.write_text(frontmatter.dumps(post) + "\n")

    # FTS
    fts.mark_superseded(conn, old_entry_id)
    prefix = _ensure_prefix(name)
    fts.insert_entry(
        conn,
        id=new_id,
        path=path.name,
        prefix=prefix,
        timestamp=ts,
        tags=" ".join(tags or target.tags),
        content=body,
        superseded=0,
    )
    fts.upsert_file(
        conn,
        fts.FileRow(
            path=path.name,
            prefix=prefix,
            description=str(post.metadata.get("description", "")),
            tags=" ".join(post.metadata.get("tags", []) or []),
            status=str(post.metadata.get("status", "active")),
            entry_count=int(post.metadata.get("entry_count", 0)),
            created=str(post.metadata.get("created", "")),
            updated=str(post.metadata.get("updated", "")),
            needs_compact=1 if post.metadata.get("needs_compact") else 0,
        ),
    )
    return new_id


def rebuild_index(conn: sqlite3.Connection) -> tuple[int, int]:
    """Full rebuild: drop all FTS rows and files rows, re-ingest from Markdown."""
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM files")
    file_count = 0
    entry_count = 0
    for path in files_mod.list_memory_files():
        try:
            prefix = _ensure_prefix(path.name)
        except ValueError as exc:
            logger.warning("skipping %s: %s", path.name, exc)
            continue
        parsed = files_mod.read_file(path)
        fts.upsert_file(
            conn,
            fts.FileRow(
                path=path.name,
                prefix=prefix,
                description=parsed.description,
                tags=" ".join(parsed.tags),
                status=parsed.status,
                entry_count=len(parsed.entries),
                created=parsed.created,
                updated=parsed.updated,
                needs_compact=1 if parsed.needs_compact else 0,
            ),
        )
        file_count += 1
        for e in parsed.entries:
            superseded = 1 if (e.superseded_by or _body_is_striked(e.body)) else 0
            fts.insert_entry(
                conn,
                id=e.id,
                path=path.name,
                prefix=prefix,
                timestamp=e.timestamp,
                tags=" ".join(e.tags),
                content=_strip_strike(e.body),
                superseded=superseded,
            )
            entry_count += 1
    return file_count, entry_count


_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)


def _body_is_striked(body: str) -> bool:
    stripped = body.strip()
    return stripped.startswith("~~") and stripped.endswith("~~")


def _strip_strike(body: str) -> str:
    return _STRIKE_RE.sub(r"\1", body)


def write_preset_files(conn: sqlite3.Connection) -> None:
    """Create user-profile.md and user-preferences.md if absent."""
    presets: dict[str, dict[str, Any]] = {
        "user-profile.md": {
            "description": (
                "User's identity, background, and long-term stable basic information "
                "(name, profession, languages, location, skill stack, etc.)"
            ),
            "tags": ["identity", "background"],
        },
        "user-preferences.md": {
            "description": (
                "User's preferences, habits, working style, and subjective tool choices"
            ),
            "tags": ["preferences"],
        },
    }
    for name, info in presets.items():
        if files_mod.memory_path(name).exists():
            continue
        with contextlib.suppress(FileExistsError):
            create_file(conn, name=name, description=info["description"], tags=info["tags"])
