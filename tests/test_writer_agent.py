"""Writer CLI entry point (``writer.agent.run``) — catches up pending sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openchronicle import config as config_mod
from openchronicle.session import store as session_store
from openchronicle.store import fts
from openchronicle.timeline import store as timeline_store
from openchronicle.writer import agent
from openchronicle.writer import llm as llm_mod


_TZ = timezone(timedelta(hours=8))


def _tool_call(name: str, args: dict[str, Any], cid: str = "c0") -> Any:
    fn = SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))
    return SimpleNamespace(id=cid, function=fn)


def _choice_response(tool_calls: list | None = None, text: str = "") -> Any:
    msg = SimpleNamespace(content=text or None, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def test_writer_run_noop_when_nothing_pending(ac_root: Path) -> None:
    cfg = config_mod.load(ac_root / "config.toml")
    result = agent.run(cfg)
    assert result.reduced == 0
    assert result.classified == 0
    assert result.written_ids == []


def test_writer_run_reduces_pending_and_classifies(
    ac_root: Path, monkeypatch
) -> None:
    """One stranded `ended` session → reducer runs → classifier runs."""
    start = datetime(2026, 4, 21, 9, 0, tzinfo=_TZ)
    end = start + timedelta(minutes=5)
    with fts.cursor() as conn:
        timeline_store.insert(
            conn,
            timeline_store.TimelineBlock(
                start_time=start,
                end_time=end,
                entries=["[Cursor] editing, involving —"],
                apps_used=["Cursor"],
                capture_count=1,
            ),
        )
        session_store.insert(
            conn,
            session_store.SessionRow(
                id="sess_cli", start_time=start, end_time=end, status="ended",
            ),
        )

    # Reducer: one LLM call that returns sub_tasks. Classifier: one commit call.
    reducer_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(
                {"summary": "cursor work", "sub_tasks": ["[09:00-09:05, Cursor] edit, involving —"]}
            ),
            tool_calls=[],
        ), finish_reason="stop")]
    )
    classifier_resp = _choice_response([_tool_call("commit", {"summary": ""}, cid="c1")])
    script = [reducer_resp, classifier_resp]

    def fake_call_llm(cfg, stage, *, messages, tools=None, json_mode=False):
        return script.pop(0)

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)

    cfg = config_mod.load(ac_root / "config.toml")
    result = agent.run(cfg)

    assert result.reduced == 1
    assert result.classified == 1  # classifier called commit (with no writes)

    with fts.cursor() as conn:
        row = session_store.get_by_id(conn, "sess_cli")
    assert row is not None
    assert row.status == "reduced"


def test_writer_run_respects_reducer_disabled(ac_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCHRONICLE_TEST_NO_REDUCER", "1")  # marker (informational)
    cfg = config_mod.load(ac_root / "config.toml")
    # Disable reducer at runtime.
    cfg.reducer.enabled = False
    result = agent.run(cfg)
    assert result.reduced == 0
