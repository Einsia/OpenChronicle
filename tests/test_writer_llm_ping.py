"""Unit tests for ``writer.llm.ping_stage``.

The integration path (status command rendering ✓ / ✗) is covered in
``test_cli_status.py``. These tests pin down ping_stage's own contract:
mock-env shortcut, success latency, error label format, and truncation.
"""

from __future__ import annotations

import pytest

from openchronicle.config import Config, ModelConfig
from openchronicle.writer import llm as llm_mod


def _cfg_with_model(model: str = "gpt-5.4-nano", api_key: str = "sk-test") -> Config:
    return Config(models={"default": ModelConfig(model=model, api_key=api_key)})


def test_ping_stage_mock_env_returns_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENCHRONICLE_LLM_MOCK=1 short-circuits before any litellm import."""
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    cfg = _cfg_with_model()

    res = llm_mod.ping_stage(cfg, "timeline")

    assert res.ok is True
    assert res.mocked is True
    assert res.latency_ms == 0
    assert res.error is None
    assert res.stage == "timeline"
    assert res.model == "gpt-5.4-nano"


def test_ping_stage_success_records_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal litellm.completion return yields ok=True with a non-negative latency."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    import litellm

    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return object()  # ping_stage doesn't read the response

    monkeypatch.setattr(litellm, "completion", fake_completion)
    cfg = _cfg_with_model()

    res = llm_mod.ping_stage(cfg, "reducer")

    assert res.ok is True
    assert res.mocked is False
    assert res.error is None
    assert res.latency_ms is not None and res.latency_ms >= 0
    # ping should keep the request small and bounded.
    assert calls[0]["max_tokens"] == 4
    assert "timeout" in calls[0]


def test_ping_stage_failure_label_includes_class_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception becomes 'ClassName: <first-line>' truncated to 80 chars."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    import litellm

    class AuthenticationError(Exception):
        pass

    def boom(**kwargs):
        raise AuthenticationError("Invalid api key sk-bo***ee")

    monkeypatch.setattr(litellm, "completion", boom)
    cfg = _cfg_with_model()

    res = llm_mod.ping_stage(cfg, "classifier")

    assert res.ok is False
    assert res.error is not None
    assert res.error.startswith("AuthenticationError")
    assert "Invalid api key" in res.error
    assert len(res.error) <= 80


def test_ping_stage_failure_with_empty_message_falls_back_to_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When str(exc) is empty, the error label is just the class name."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    import litellm

    class Timeout(Exception):
        pass

    def boom(**kwargs):
        raise Timeout()

    monkeypatch.setattr(litellm, "completion", boom)
    cfg = _cfg_with_model()

    res = llm_mod.ping_stage(cfg, "compact")

    assert res.ok is False
    assert res.error == "Timeout"


def test_ping_stage_truncates_long_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Error labels are capped so a verbose provider message can't blow up status output."""
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    import litellm

    class ProviderError(Exception):
        pass

    def boom(**kwargs):
        raise ProviderError("x" * 500)

    monkeypatch.setattr(litellm, "completion", boom)
    cfg = _cfg_with_model()

    res = llm_mod.ping_stage(cfg, "timeline")

    assert res.ok is False
    assert res.error is not None
    assert len(res.error) <= 80
