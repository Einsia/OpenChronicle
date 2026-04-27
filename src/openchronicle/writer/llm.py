"""litellm wrapper with per-stage model resolution."""

from __future__ import annotations

import json
import os
from typing import Any

from ..config import Config, resolve_api_key
from ..logger import get

logger = get("openchronicle.writer")

# litellm.completion() defaults to no client-side timeout and zero
# retries. Without these, a stuck connection (slow provider, partial
# response, dead TCP socket) blocks the reducer / classifier daemon
# thread *forever* — the daemon stays "alive" but no durable facts
# get written.  Two minutes is generous for a long session reduce
# without being absurdly long; a slow local model can override per
# stage via ``[models.<stage>] timeout_seconds = N``.
DEFAULT_TIMEOUT_SECONDS = 120
# Two retries gives 3 total attempts. litellm uses tenacity-style
# backoff between attempts and respects Retry-After headers from
# providers, so this is enough to absorb a brief 429 / 502 blip
# without piling on extra latency.
DEFAULT_NUM_RETRIES = 2


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
    timeout = (
        model_cfg.timeout_seconds
        if model_cfg.timeout_seconds is not None
        else DEFAULT_TIMEOUT_SECONDS
    )
    num_retries = (
        model_cfg.num_retries
        if model_cfg.num_retries is not None
        else DEFAULT_NUM_RETRIES
    )
    kwargs: dict[str, Any] = {
        "model": model_cfg.model,
        "messages": messages,
        "timeout": timeout,
        "num_retries": num_retries,
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

    logger.debug(
        "llm call stage=%s model=%s timeout=%ds retries=%d",
        stage, model_cfg.model, timeout, num_retries,
    )
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
