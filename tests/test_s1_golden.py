"""Golden fixture tests for S1 parser output.

Each fixture directory under ``tests/fixtures/s1`` contains an
``input.json`` (a minimal capture object) and an ``expected.json``
(the expected S1 output fields).  The test calls ``s1_parser.enrich``
and compares only the S1 fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openchronicle.capture import s1_parser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "s1"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _fixture_ids() -> list[str]:
    return sorted(
        d.name for d in FIXTURES_DIR.iterdir() if d.is_dir()
    )


@pytest.mark.parametrize("name", _fixture_ids())
def test_s1_golden(name: str) -> None:
    fixture_dir = FIXTURES_DIR / name
    input_capture = _read_json(fixture_dir / "input.json")
    expected = _read_json(fixture_dir / "expected.json")

    s1_parser.enrich(input_capture)

    actual: dict = {
        "focused_element": input_capture.get("focused_element"),
        "visible_text": input_capture.get("visible_text"),
        "url": input_capture.get("url"),
    }
    if "app_context" in input_capture:
        actual["app_context"] = input_capture["app_context"]

    assert actual == expected
