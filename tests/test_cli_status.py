"""Tests for `openchronicle status` — particularly the per-stage LLM probes."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from openchronicle import cli
from openchronicle.writer import llm as llm_mod


def test_status_renders_mocked_pings(ac_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENCHRONICLE_LLM_MOCK=1 short-circuits each stage probe to '✓ mocked'."""
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    runner = CliRunner()
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Model (timeline)" in out
    assert "Model (reducer)" in out
    assert "Model (classifier)" in out
    assert "Model (compact)" in out
    # All four stages share the default model, so they all show the mocked tick.
    assert out.count("mocked") >= 4


def test_status_renders_probe_failure(ac_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ping_stage raises, status shows ✗ <ErrorClass> and still exits 0."""
    # Make sure mock-mode is OFF so the real ping_stage path runs.
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)

    def boom(cfg, stage, *, timeout=5.0):  # noqa: ARG001
        return llm_mod.PingResult(
            stage=stage,
            model=cfg.model_for(stage).model,
            ok=False,
            latency_ms=None,
            error="AuthenticationError",
        )

    monkeypatch.setattr(llm_mod, "ping_stage", boom)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "AuthenticationError" in result.output
    assert "✗" in result.output
