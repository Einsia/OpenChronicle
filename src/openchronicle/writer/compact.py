"""Compact a memory file while preserving unique facts.

Workflow: LLM rewrites the file, then a noun-phrase-preservation check blocks
compressions that drop too many distinct tokens.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import frontmatter

from ..config import Config
from ..logger import get
from ..prompts import load as load_prompt
from ..store import entries as entries_mod
from ..store import files as files_mod
from ..store import fts
from . import llm as llm_mod

logger = get("openchronicle.compact")

_UNIQUE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
_PRESERVATION_THRESHOLD = 0.95  # must keep ≥95% of unique tokens


@dataclass
class CompactResult:
    path: str
    accepted: bool
    before_tokens: int
    after_tokens: int
    before_unique: int
    after_unique: int
    preservation_ratio: float
    note: str = ""


def _unique_tokens(text: str) -> set[str]:
    return {t.lower() for t in _UNIQUE_TOKEN_RE.findall(text)}


def compact_file(cfg: Config, conn: sqlite3.Connection, *, name: str) -> CompactResult:
    path = files_mod.memory_path(name)
    if not path.exists():
        return CompactResult(name, False, 0, 0, 0, 0, 0.0, "file missing")

    original = path.read_text()
    before_unique = _unique_tokens(original)
    before_tokens = len(original) // 4

    system = load_prompt("compact.md")
    user = (
        "Compress this file. Output the full new Markdown including frontmatter.\n\n"
        "```markdown\n" + original + "\n```"
    )

    try:
        resp = llm_mod.call_llm(
            cfg,
            "compact",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compact llm call failed: %s", exc)
        return CompactResult(name, False, before_tokens, before_tokens,
                             len(before_unique), len(before_unique), 1.0,
                             f"llm error: {exc}")

    new_text = llm_mod.extract_text(resp).strip()
    # Strip markdown code fences if the model wrapped the output
    new_text = _unwrap_code_fence(new_text)

    if not new_text.startswith("---"):
        return CompactResult(
            name, False, before_tokens, len(new_text) // 4,
            len(before_unique), 0, 0.0, "response missing frontmatter — rejected",
        )

    try:
        compacted = frontmatter.loads(new_text)
    except Exception as exc:  # noqa: BLE001
        return CompactResult(
            name, False, before_tokens, len(new_text) // 4,
            len(before_unique), 0, 0.0, f"frontmatter parse error: {exc}",
        )
    compacted.metadata["needs_compact"] = False
    new_text = frontmatter.dumps(compacted) + "\n"
    compacted_entries = files_mod._parse_entries(compacted.content)
    prefix = files_mod.validate_prefix(path.name)

    after_unique = _unique_tokens(new_text)
    preserved = len(before_unique & after_unique)
    ratio = preserved / len(before_unique) if before_unique else 1.0

    if ratio < _PRESERVATION_THRESHOLD:
        logger.warning(
            "compact rejected: %.1f%% preservation (need %.0f%%) — %s",
            ratio * 100, _PRESERVATION_THRESHOLD * 100, name,
        )
        return CompactResult(
            name, False, before_tokens, len(new_text) // 4,
            len(before_unique), len(after_unique), ratio,
            f"rejected: preservation {ratio:.1%} < {_PRESERVATION_THRESHOLD:.0%}",
        )

    # Accept only if the file is still the same one the LLM saw. The LLM call
    # can take tens of seconds; reducers/classifiers may append while it runs.
    # Overwriting after a stale read would silently drop those new entries.
    with files_mod.file_lock(path):
        try:
            current = path.read_text()
        except FileNotFoundError:
            return CompactResult(
                name, False, before_tokens, before_tokens,
                len(before_unique), len(before_unique), 1.0,
                "file missing before writeback",
            )
        if current != original:
            logger.info("compact skipped: %s changed during LLM rewrite", name)
            return CompactResult(
                name, False, before_tokens, before_tokens,
                len(before_unique), len(before_unique), 1.0,
                "file changed during compact — retry later",
            )

        files_mod.atomic_write_text(path, new_text)

        # Re-ingest this file's entries into FTS while still holding the same
        # file lock so on-disk Markdown and index rows move forward together.
        conn.execute("SAVEPOINT compact_file_fts")
        try:
            fts.delete_entries_for(conn, path.name)
            fts.upsert_file(
                conn,
                fts.FileRow(
                    path=path.name,
                    prefix=prefix,
                    description=str(compacted.metadata.get("description", "")),
                    tags=" ".join(compacted.metadata.get("tags", []) or []),
                    status=str(compacted.metadata.get("status", "active")),
                    entry_count=len(compacted_entries),
                    created=str(compacted.metadata.get("created", "")),
                    updated=str(compacted.metadata.get("updated", "")),
                    needs_compact=0,
                ),
            )
            for e in compacted_entries:
                fts.insert_entry(
                    conn,
                    id=e.id,
                    path=path.name,
                    prefix=prefix,
                    timestamp=e.timestamp,
                    tags=" ".join(e.tags),
                    content=entries_mod._strip_strike(e.body),
                    superseded=1 if e.superseded_by else 0,
                )
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT compact_file_fts")
            conn.execute("RELEASE SAVEPOINT compact_file_fts")
            raise
        conn.execute("RELEASE SAVEPOINT compact_file_fts")

    logger.info(
        "compact accepted: %s  %d→%d tokens (%.1f%% preservation)",
        name, before_tokens, len(new_text) // 4, ratio * 100,
    )
    return CompactResult(
        name, True, before_tokens, len(new_text) // 4,
        len(before_unique), len(after_unique), ratio,
    )


def _unwrap_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def run_pending(cfg: Config, conn: sqlite3.Connection) -> list[CompactResult]:
    pending = fts.files_needing_compact(conn)
    results: list[CompactResult] = []
    for name in pending:
        results.append(compact_file(cfg, conn, name=name))
    return results
