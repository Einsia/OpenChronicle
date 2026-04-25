"""litellm wrapper with per-stage model resolution."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from ..config import Config, resolve_api_key
from ..logger import get

logger = get("openchronicle.writer")


@dataclass
class PingResult:
    stage: str
    model: str
    ok: bool
    latency_ms: int | None
    error: str | None
    mocked: bool = False


def call_llm(
    cfg: Config,
    stage: str,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    json_mode: bool = False,
) -> Any:
    """Invoke litellm for the given stage. Returns the raw ModelResponse.

    Respects OPENCHRONICLE_LLM_MOCK=1 for tests: returns a minimal stub.
    """
    if os.environ.get("OPENCHRONICLE_LLM_MOCK") == "1":
        return _mock_response(stage, messages, tools, json_mode)

    import litellm  # imported lazily to keep CLI startup fast

    model_cfg = cfg.model_for(stage)
    kwargs: dict[str, Any] = {
        "model": model_cfg.model,
        "messages": messages,
    }
    if model_cfg.base_url:
        kwargs["api_base"] = model_cfg.base_url
    api_key = resolve_api_key(model_cfg)
    if api_key:
        kwargs["api_key"] = api_key
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if model_cfg.max_tokens:
        kwargs["max_tokens"] = model_cfg.max_tokens

    logger.debug("llm call stage=%s model=%s", stage, model_cfg.model)
    return litellm.completion(**kwargs)


def _mock_response(stage: str, messages, tools, json_mode):
    """Minimal stub for offline tests. Customize via OPENCHRONICLE_LLM_MOCK_JSON."""
    override = os.environ.get("OPENCHRONICLE_LLM_MOCK_JSON")
    content = override if override else '{"worth_writing": false, "brief_reason": "mock"}'

    class _Msg:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    class _Choice:
        def __init__(self, msg):
            self.message = msg
            self.finish_reason = "stop"

    class _Resp:
        def __init__(self, choices):
            self.choices = choices

    return _Resp([_Choice(_Msg(content))])


def extract_text(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return ""


def ping_stage(cfg: Config, stage: str, *, timeout: float = 5.0) -> PingResult:
    """Send a tiny round-trip request to the stage's configured model.

    Returns a PingResult with success, latency, and a short error label on
    failure. Honors OPENCHRONICLE_LLM_MOCK=1 by returning a mocked-ok result
    without touching the network. Never raises — `status` and similar
    informational callers must remain non-fatal.
    """
    model_cfg = cfg.model_for(stage)
    if os.environ.get("OPENCHRONICLE_LLM_MOCK") == "1":
        return PingResult(
            stage=stage, model=model_cfg.model, ok=True,
            latency_ms=0, error=None, mocked=True,
        )

    try:
        import litellm  # lazy import — keeps CLI startup fast
    except ImportError as exc:
        return PingResult(
            stage=stage, model=model_cfg.model, ok=False,
            latency_ms=None, error=f"ImportError: {exc}",
        )

    kwargs: dict[str, Any] = {
        "model": model_cfg.model,
        "messages": [{"role": "user", "content": "Reply with 'ok'."}],
        "max_tokens": 4,
        "timeout": timeout,
    }
    if model_cfg.base_url:
        kwargs["api_base"] = model_cfg.base_url
    api_key = resolve_api_key(model_cfg)
    if api_key:
        kwargs["api_key"] = api_key

    start = time.monotonic()
    try:
        litellm.completion(**kwargs)
    except Exception as exc:  # noqa: BLE001
        label = type(exc).__name__
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        if msg:
            label = f"{label}: {msg[:60]}"
        return PingResult(
            stage=stage, model=model_cfg.model, ok=False,
            latency_ms=None, error=label[:80],
        )
    latency_ms = int((time.monotonic() - start) * 1000)
    return PingResult(
        stage=stage, model=model_cfg.model, ok=True,
        latency_ms=latency_ms, error=None,
    )


def extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    try:
        calls = response.choices[0].message.tool_calls or []
    except (AttributeError, IndexError):
        return []
    out: list[dict[str, Any]] = []
    for c in calls:
        fn = getattr(c, "function", None) or c.get("function", {})
        args_raw = getattr(fn, "arguments", None) if hasattr(fn, "arguments") else fn.get("arguments")
        name = getattr(fn, "name", None) if hasattr(fn, "name") else fn.get("name")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            args = {}
        out.append(
            {
                "id": getattr(c, "id", None) or c.get("id"),
                "name": name,
                "arguments": args,
            }
        )
    return out
