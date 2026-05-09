from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openchronicle import config as config_mod
from openchronicle import paths
from openchronicle.store import entries as entries_mod
from openchronicle.store import fts
from openchronicle.writer import classifier as classifier_mod
from openchronicle.writer import llm as llm_mod

_TZ = timezone(timedelta(hours=8))


def _tool_call(name: str, args: dict[str, Any], cid: str = "c0") -> Any:
    fn = SimpleNamespace(
        name=name, arguments=json.dumps(args, ensure_ascii=False)
    )
    return SimpleNamespace(id=cid, function=fn)


def _response(tool_calls: list | None = None, text: str = "") -> Any:
    msg = SimpleNamespace(content=text or None, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


def _seed_event_daily(day: str) -> tuple[str, str]:
    """Create event-YYYY-MM-DD.md with one entry; return (filename, entry_id)."""
    name = f"event-{day}.md"
    with fts.cursor() as conn:
        entries_mod.create_file(
            conn, name=name,
            description=f"Session log for {day}",
            tags=["event", "session", "daily"],
        )
        entry_id = entries_mod.append_entry(
            conn, name=name,
            content=(
                "**Session sess_abc** (10:00–10:45)\n\n"
                "The user spent 45 minutes in Cursor configuring a new "
                "Python project and said in a note: \"I prefer Cursor over "
                "VSCode now because the AI tab-complete is better.\"\n\n"
                "- [10:00-10:45, Cursor] edited project-root files, involving —\n"
            ),
            tags=["session", "sid:sess_abc"],
        )
    return name, entry_id


def test_classifier_appends_durable_preference(ac_root: Path, monkeypatch) -> None:
    day = "2026-04-21"
    name, entry_id = _seed_event_daily(day)

    # Scripted LLM: iter 1 → search, iter 2 → append, iter 3 → commit.
    script = [
        _response([_tool_call(
            "search_memory", {"query": "Cursor over VSCode"}, cid="c1",
        )]),
        _response([_tool_call(
            "append",
            {
                "path": "user-preferences.md",
                "content": "User prefers Cursor over VSCode because of its AI tab-complete.",
                "tags": ["editor", "preference"],
            },
            cid="c2",
        )]),
        _response([_tool_call(
            "commit", {"summary": "recorded Cursor-over-VSCode preference"}, cid="c3",
        )]),
    ]

    def fake_call_llm(cfg, stage, *, messages, tools=None, json_mode=False):
        assert stage == "classifier"
        return script.pop(0)

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)

    cfg = config_mod.load(ac_root / "config.toml")
    result = classifier_mod.classify_after_reduce(
        cfg, session_id="sess_abc", event_daily_path=name, just_written_entry_id=entry_id,
    )

    assert result.committed is True
    assert len(result.written_ids) == 1
    assert "Cursor-over-VSCode" in result.summary

    # Event-daily was NOT modified.
    evt = (paths.memory_dir() / name).read_text(encoding="utf-8")
    assert evt.count("**Session sess_abc**") == 1

    # user-preferences.md got the new entry.
    pref = (paths.memory_dir() / "user-preferences.md").read_text(encoding="utf-8")
    assert "Cursor over VSCode" in pref


def test_classifier_rejects_event_write(ac_root: Path, monkeypatch) -> None:
    day = "2026-04-22"
    name, entry_id = _seed_event_daily(day)

    # LLM tries to write back to event-* — must be rejected without committing.
    script = [
        _response([_tool_call(
            "append",
            {"path": name, "content": "should be blocked", "tags": ["x"]},
            cid="c1",
        )]),
        _response([_tool_call(
            "commit", {"summary": ""}, cid="c2",
        )]),
    ]

    def fake_call_llm(cfg, stage, *, messages, tools=None, json_mode=False):
        return script.pop(0)

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)

    cfg = config_mod.load(ac_root / "config.toml")
    result = classifier_mod.classify_after_reduce(
        cfg, session_id="sess_reject", event_daily_path=name, just_written_entry_id=entry_id,
    )

    # Committed=True (LLM called commit), but zero writes landed.
    assert result.committed is True
    assert result.written_ids == []


def test_classifier_empty_commit_when_nothing_classifiable(
    ac_root: Path, monkeypatch,
) -> None:
    day = "2026-04-23"
    name, entry_id = _seed_event_daily(day)

    script = [_response([_tool_call("commit", {"summary": ""}, cid="c1")])]

    def fake_call_llm(cfg, stage, *, messages, tools=None, json_mode=False):
        return script.pop(0)

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)

    cfg = config_mod.load(ac_root / "config.toml")
    result = classifier_mod.classify_after_reduce(
        cfg, session_id="sess_noop", event_daily_path=name, just_written_entry_id=entry_id,
    )

    assert result.committed is True
    assert result.written_ids == []
    assert result.iterations == 1


def test_classifier_skips_when_event_daily_missing(ac_root: Path) -> None:
    cfg = config_mod.load(ac_root / "config.toml")
    result = classifier_mod.classify_after_reduce(
        cfg,
        session_id="sess_no_file",
        event_daily_path="event-9999-99-99.md",
        just_written_entry_id="fake",
    )
    assert result.committed is False
    assert "no entries" in result.skipped_reason
