"""Rebuild memory/index.md from the `files` table after every writer commit."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from .. import paths
from . import files as files_mod
from . import fts


def rebuild(conn: sqlite3.Connection) -> None:
    active = fts.list_files(conn, include_dormant=False, include_archived=False)
    dormant = fts.list_files(conn, include_dormant=True, include_archived=False)
    archived = fts.list_files(conn, include_dormant=True, include_archived=True)
    dormant_only = [f for f in dormant if f.status == "dormant"]
    archived_only = [f for f in archived if f.status == "archived"]

    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    lines: list[str] = []
    lines.append("# Memory Index")
    lines.append(f"Last rebuilt: {now}")
    lines.append("")

    lines.append("## Active files")
    lines.append("")
    if active:
        lines.append("| File | Description | Tags | Entries | Updated |")
        lines.append("|---|---|---|---|---|")
        for f in active:
            desc = f.description.replace("\n", " ").strip()
            lines.append(
                f"| {f.path} | {desc} | {f.tags} | {f.entry_count} | {f.updated} |"
            )
    else:
        lines.append("_(none yet)_")
    lines.append("")

    lines.append("## Dormant files (30+ days no update)")
    lines.append("")
    if dormant_only:
        lines.append("| File | Description | Last Updated |")
        lines.append("|---|---|---|")
        for f in dormant_only:
            lines.append(f"| {f.path} | {f.description} | {f.updated} |")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Archived")
    if archived_only:
        lines.append("")
        for f in archived_only:
            lines.append(f"- {f.path} — {f.description}")
    else:
        lines.append("")
        lines.append("_(none)_")
    lines.append("")

    lines.append("## Recent activity (last 7 days)")
    lines.append("")
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT timestamp, path FROM entries WHERE timestamp >= ? "
        "ORDER BY timestamp DESC LIMIT 40",
        (cutoff,),
    ).fetchall()
    if rows:
        by_day_path: dict[tuple[str, str], int] = {}
        for r in rows:
            day = r["timestamp"][:10]
            by_day_path[(day, r["path"])] = by_day_path.get((day, r["path"]), 0) + 1
        for (day, path_), count in sorted(by_day_path.items(), reverse=True):
            lines.append(f"- {day}: {path_} (+{count} entr{'ies' if count != 1 else 'y'})")
    else:
        lines.append("_(none)_")
    lines.append("")

    files_mod.atomic_write_text(paths.memory_dir() / "index.md", "\n".join(lines))


def auto_dormant(conn: sqlite3.Connection, *, days: int = 30) -> int:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "UPDATE files SET status='dormant' WHERE status='active' AND updated < ?", (cutoff,)
    )
    return cur.rowcount or 0
