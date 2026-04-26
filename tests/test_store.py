import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from openchronicle.store import entries as entries_mod
from openchronicle.store import files as files_mod
from openchronicle.store import fts, index_md


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


def test_concurrent_appends_lose_no_entries(ac_root: Path) -> None:
    """N threads appending to the same file must all land.

    Without the per-path lock, ``append_entry`` is read-modify-write:
    each thread reads the same base, appends, and only the last writer's
    version reaches disk — silent data loss with FTS rows pointing at
    entries that don't exist on disk. ``threading.Barrier`` forces every
    thread to enter the critical section as simultaneously as the OS
    will allow, which is what makes the race deterministic enough to
    catch in a unit test.
    """
    n = 30
    name = "topic-load-test.md"

    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name=name, description="concurrent appends", tags=["topic"]
        )

    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()
            with fts.cursor() as conn:
                entries_mod.append_entry(
                    conn, name=name,
                    content=f"entry number {i:02d}",
                    tags=["topic"],
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert errors == [], f"workers errored: {errors}"

    parsed = files_mod.read_file(files_mod.memory_path(name))
    assert len(parsed.entries) == n, (
        f"expected {n} entries, got {len(parsed.entries)} "
        f"— silent loss indicates the lock is not protecting the read-modify-write"
    )
    bodies = {e.body for e in parsed.entries}
    assert len(bodies) == n, "duplicate or missing entry bodies"
    # File and FTS must agree.
    with fts.cursor() as conn:
        rebuilt_files, rebuilt_entries = entries_mod.rebuild_index(conn)
        assert rebuilt_files == 1
        assert rebuilt_entries == n


def test_concurrent_supersede_then_append_serializes(ac_root: Path) -> None:
    """A supersede + an append on the same file must both land cleanly.

    Without the per-path lock, supersede's two-write read-modify-write
    can interleave with an append in a way that produces a file the
    next ``read_file`` won't even parse. With the lock, both operations
    serialize and the resulting file has 1 superseded original + 1
    superseder + 1 fresh append, all parseable.
    """
    name = "person-bob.md"
    with fts.cursor() as conn:
        entries_mod.create_file(conn, name=name, description="Bob", tags=["person"])
        original = entries_mod.append_entry(
            conn, name=name, content="Bob is at OpenAI as ML lead.", tags=["person"],
        )

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def supersede_worker() -> None:
        try:
            barrier.wait()
            with fts.cursor() as conn:
                entries_mod.supersede_entry(
                    conn, name=name, old_entry_id=original,
                    new_content="Bob moved from OpenAI to Anthropic in 2026-04.",
                    reason="role change", tags=["person"],
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def append_worker() -> None:
        try:
            barrier.wait()
            with fts.cursor() as conn:
                entries_mod.append_entry(
                    conn, name=name,
                    content="Bob's preferred IDE is Cursor.",
                    tags=["person", "preference"],
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=supersede_worker),
        threading.Thread(target=append_worker),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20.0)

    assert errors == [], f"workers errored: {errors}"

    parsed = files_mod.read_file(files_mod.memory_path(name))
    # 1 superseded original + 1 superseder + 1 fresh append = 3 entries.
    assert len(parsed.entries) == 3, (
        f"expected 3 entries, got {len(parsed.entries)} — interleaved writes "
        f"likely lost or corrupted one"
    )
