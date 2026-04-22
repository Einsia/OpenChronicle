from pathlib import Path

from openchronicle.store import entries as entries_mod
from openchronicle.store import fts
from openchronicle.writer import tools as wtools


def test_dispatch_append_and_commit(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="project-foo.md", description="Foo project", tags=["project"]
        )
        state = wtools.CommitState()
        r1 = wtools.dispatch(
            "append",
            {"path": "project-foo.md", "content": "Bar happened.", "tags": ["bar"]},
            conn=conn, soft_limit_tokens=20000, state=state,
        )
        assert r1["ok"]
        r2 = wtools.dispatch("commit", {"summary": "wrote 1"}, conn=conn, soft_limit_tokens=20000, state=state)
        assert r2["ok"]
        assert state.committed
        assert state.summary == "wrote 1"
        assert len(state.written_ids) == 1


def test_dispatch_read_memory(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="tool-cursor.md", description="Cursor editor", tags=["tool"]
        )
        state = wtools.CommitState()
        wtools.dispatch(
            "append",
            {"path": "tool-cursor.md", "content": "User uses Cursor.", "tags": ["editor"]},
            conn=conn, soft_limit_tokens=20000, state=state,
        )
        r = wtools.dispatch(
            "read_memory", {"path": "tool-cursor.md"},
            conn=conn, soft_limit_tokens=20000, state=state,
        )
        assert r["path"] == "tool-cursor.md"
        assert len(r["entries"]) == 1


def test_dispatch_search(ac_root: Path) -> None:
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name="topic-rust.md", description="Rust learning", tags=["topic"]
        )
        state = wtools.CommitState()
        wtools.dispatch(
            "append",
            {"path": "topic-rust.md", "content": "User learning async Rust.", "tags": ["rust"]},
            conn=conn, soft_limit_tokens=20000, state=state,
        )
        r = wtools.dispatch(
            "search_memory", {"query": "async", "top_k": 3},
            conn=conn, soft_limit_tokens=20000, state=state,
        )
        assert len(r["results"]) == 1
        assert r["results"][0]["path"] == "topic-rust.md"
