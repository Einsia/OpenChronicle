from __future__ import annotations

import json

from openchronicle.rpa.trace import TraceWriter


def test_trace_jsonl_writes_step(ac_root) -> None:
    writer = TraceWriter(task_id="task", workflow_id="wf", provider="fake")

    writer.write_step(
        step_id="s1",
        observation={
            "app": "Example",
            "screen_size": [100, 200],
            "ocr": [{"text": "Hello", "box": [1, 2, 3, 4]}],
        },
        action={"action": "tap", "x": 1, "y": 2},
        result={"status": "success"},
        safety={"risk": "low", "confirmed": False},
    )

    rows = writer.trace_path.read_text(encoding="utf-8").splitlines()
    data = json.loads(rows[0])
    assert data["workflow_id"] == "wf"
    assert data["observation"]["ocr_texts"] == ["Hello"]
    assert data["result"]["status"] == "success"
