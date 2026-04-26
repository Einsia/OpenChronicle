import os
from pathlib import Path
from unittest.mock import patch

import pytest

from openchronicle.store import (
    entries as entries_mod,
)
from openchronicle.store import (
    files as files_mod,
)
from openchronicle.store import (
    fts,
    index_md,
)


def test_make_id_uniqueness() -> None:
    ids = {entries_mod.make_id("2026-04-21T10:30") for _ in range(200)}
    assert len(ids) == 200


def test_create_append_search(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn,
            name="project-openchronicle.md",
            description="OpenChronicle OSS project design",
            tags=["project", "ai"],
        )
        eid1 = entries_mod.append_entry(
            conn,
            name="project-openchronicle.md",
            content="User chose Python CLI + daemon form factor for v1.",
            tags=["project", "decision"],
        )
        eid2 = entries_mod.append_entry(
            conn,
            name="project-openchronicle.md",
            content="User picked uv and pyproject.toml over pip + requirements.txt.",
            tags=["project", "tooling"],
        )

        hits = fts.search(conn, query="daemon", top_k=5)
        hit_ids = {h.id for h in hits}
        assert eid1 in hit_ids

        hits2 = fts.search(conn, query="uv", top_k=5)
        assert any(h.id == eid2 for h in hits2)

        # GLOB path filter
        hits3 = fts.search(conn, query="Python", path_patterns=["project-*.md"], top_k=5)
        assert len(hits3) >= 1


def test_supersede_filters_old_by_default(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="tool-cursor.md", description="Cursor editor", tags=["tool"]
        )
        old = entries_mod.append_entry(
            conn, name="tool-cursor.md",
            content="User prefers VSCode as primary editor.", tags=["editor"],
        )
        entries_mod.supersede_entry(
            conn, name="tool-cursor.md", old_entry_id=old,
            new_content="User switched from VSCode to Cursor for AI integration.",
            reason="editor switch", tags=["editor"],
        )
        # Default: no superseded
        hits_default = fts.search(conn, query="VSCode", top_k=5)
        assert not any(h.id == old for h in hits_default)
        # With include_superseded: old re-surfaces
        hits_all = fts.search(conn, query="VSCode", top_k=5, include_superseded=True)
        assert any(h.id == old for h in hits_all)


def test_invalid_prefix_rejected(ac_root: Path) -> None:
    with fts.cursor() as conn, pytest.raises(ValueError):
        entries_mod.create_file(
            conn, name="random-notes.md", description="desc", tags=[]
        )


def test_rebuild_index_round_trip(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="user-profile.md", description="identity", tags=["identity"]
        )
        entries_mod.append_entry(
            conn, name="user-profile.md",
            content="User is a data scientist.", tags=["identity"],
        )
        entries_mod.append_entry(
            conn, name="user-profile.md",
            content="User writes a lot of Python.", tags=["identity", "skills"],
        )
    with fts.cursor() as conn2:
        file_count, entry_count = entries_mod.rebuild_index(conn2)
        assert file_count == 1
        assert entry_count == 2
        hits = fts.search(conn2, query="Python", top_k=5)
        assert len(hits) >= 1


def test_index_md_rebuild_runs(ac_root: Path) -> None:
    from openchronicle import paths

    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="user-profile.md", description="identity", tags=["identity"]
        )
        index_md.rebuild(conn)
    out = (paths.memory_dir() / "index.md").read_text()
    assert "# Memory Index" in out
    assert "user-profile.md" in out


def test_atomic_write_preserves_original_on_replace_failure(tmp_path: Path) -> None:
    """Simulating a crash at the rename step must leave the file intact.

    A SIGKILL between ``write_text``'s first byte and last byte truncates
    the file under the previous code; under ``atomic_write_text`` the
    rename is the only externally-visible step so a failure there leaves
    the original content untouched and any temp file cleaned up.
    """
    target = tmp_path / "memory.md"
    original = "ORIGINAL CONTENT\nline 2\n"
    target.write_text(original)

    real_replace = os.replace
    boom = OSError("simulated rename failure")
    with (
        patch("openchronicle.store.files.os.replace", side_effect=boom),
        pytest.raises(OSError),
    ):
        files_mod.atomic_write_text(target, "NEW CONTENT THAT NEVER LANDS")

    assert target.read_text() == original
    # No leftover .tmp files
    leftovers = [p for p in tmp_path.iterdir() if p.name != "memory.md"]
    assert leftovers == [], f"unexpected leftover files: {leftovers}"

    # Sanity: a normal call still works once we restore replace
    assert os.replace is real_replace
    files_mod.atomic_write_text(target, "NEW CONTENT")
    assert target.read_text() == "NEW CONTENT"


def test_atomic_write_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir" / "file.md"
    files_mod.atomic_write_text(nested, "hello")
    assert nested.read_text() == "hello"


def test_atomic_write_preserves_existing_permissions(tmp_path: Path) -> None:
    """Overwriting must not silently downgrade an existing file's mode.

    ``tempfile.mkstemp`` creates files at 0o600 — without explicit
    chmod the rename would replace a user's 0o644 file with a 0o600
    one, a hidden behavior change from ``Path.write_text``.
    """
    target = tmp_path / "memory.md"
    target.write_text("original")
    target.chmod(0o644)

    files_mod.atomic_write_text(target, "updated")

    assert target.read_text() == "updated"
    assert (target.stat().st_mode & 0o777) == 0o644


def test_atomic_write_round_trip_through_append_entry(ac_root: Path) -> None:
    """End-to-end: append → read returns the new entry, file isn't corrupted."""
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="topic-rust-async.md",
            description="Rust async patterns", tags=["topic"],
        )
        entries_mod.append_entry(
            conn, name="topic-rust-async.md",
            content="Tokio's `select!` polls all branches each iteration.",
            tags=["topic", "rust"],
        )
    parsed = files_mod.read_file(files_mod.memory_path("topic-rust-async.md"))
    assert len(parsed.entries) == 1
    assert "Tokio" in parsed.entries[0].body
