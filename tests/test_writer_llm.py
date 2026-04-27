"""Tests for the litellm wrapper: timeout / retries / per-stage override."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from openchronicle.config import Config, ModelConfig
from openchronicle.writer import llm as llm_mod


def _cfg_with_models(models: dict[str, ModelConfig]) -> Config:
    """Build a Config whose ``model_for(stage)`` returns the given mapping.

    The real ``Config.model_for`` falls back from stage → 'default' →
    bare ``ModelConfig()``, so we make sure 'default' exists.
    """
    if "default" not in models:
        models["default"] = ModelConfig()
    cfg = Config()
    cfg.models = models
    return cfg


def _stub_completion_response() -> Any:
    """Return-shape doesn't matter for these tests — they only inspect kwargs."""
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_call_llm_passes_default_timeout_and_retries(monkeypatch) -> None:
    """Stage with no explicit override → module defaults are forwarded to litellm."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    cfg = _cfg_with_models({})

    with patch("litellm.completion", return_value=_stub_completion_response()) as mock:
        llm_mod.call_llm(
            cfg, "reducer",
            messages=[{"role": "user", "content": "hi"}],
        )
        kwargs = mock.call_args.kwargs

    assert kwargs["timeout"] == llm_mod.DEFAULT_TIMEOUT_SECONDS
    assert kwargs["num_retries"] == llm_mod.DEFAULT_NUM_RETRIES


def test_call_llm_per_stage_timeout_override(monkeypatch) -> None:
    """A stage-level timeout_seconds in the config overrides the default."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    cfg = _cfg_with_models(
        {
            "reducer": ModelConfig(timeout_seconds=300, num_retries=5),
        }
    )

    with patch("litellm.completion", return_value=_stub_completion_response()) as mock:
        llm_mod.call_llm(
            cfg, "reducer",
            messages=[{"role": "user", "content": "hi"}],
        )
        kwargs = mock.call_args.kwargs

    assert kwargs["timeout"] == 300
    assert kwargs["num_retries"] == 5


def test_call_llm_other_stages_keep_defaults_when_one_is_overridden(monkeypatch) -> None:
    """Setting timeout for ``reducer`` must not leak into ``classifier``."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    cfg = _cfg_with_models(
        {
            "reducer": ModelConfig(timeout_seconds=300),
            "classifier": ModelConfig(),  # no override
        }
    )

    with patch("litellm.completion", return_value=_stub_completion_response()) as mock:
        llm_mod.call_llm(
            cfg, "classifier",
            messages=[{"role": "user", "content": "hi"}],
        )
        kwargs = mock.call_args.kwargs

    assert kwargs["timeout"] == llm_mod.DEFAULT_TIMEOUT_SECONDS


def test_call_llm_mock_path_bypasses_litellm(monkeypatch) -> None:
    """OPENCHRONICLE_LLM_MOCK=1 still short-circuits before importing litellm."""
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    cfg = _cfg_with_models({})

    with patch("litellm.completion") as mock:
        resp = llm_mod.call_llm(
            cfg, "reducer",
            messages=[{"role": "user", "content": "hi"}],
        )

    assert mock.call_count == 0
    # The mock response shape: choices[0].message.content is a string.
    assert resp.choices[0].message.content
