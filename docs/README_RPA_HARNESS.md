# OpenChronicle RPA Harness

OpenChronicle now has a lightweight RPA component system under
`openchronicle.rpa`. It is additive: the existing capture, timeline, session,
writer, store, MCP, and prompt pipeline remains the memory system of record.
RPA traces are stored separately and can later be distilled into reusable
skills.

## Provider model

An RPA provider implements `RPAProvider`:

- `observe()` returns current state, such as screenshot, OCR text, current app,
  screen size, window title, or control tree.
- `act(action)` executes one whitelisted action.
- `capabilities()` declares supported actions and observations.
- `run_task()` and `stop()` are optional higher-level hooks.

To add a provider, create:

- `src/openchronicle/rpa/providers/<name>/manifest.json`
- `src/openchronicle/rpa/providers/<name>/adapter.py`
- any provider-local action, screenshot, input, or safety helpers

The registry discovers providers by scanning `providers/*/manifest.json` and
loading `openchronicle.rpa.providers.<name>.adapter.Provider`.

## Built-in providers

- `android_adb`: Android device automation through the existing safe
  `ADBController`. It supports screenshots, current app, screen size, UI XML,
  OCR, tap, normalized tap, text tap, text input, swipe, back, home, launch app,
  wait, and takeover.
- `windows_uia`: Windows UI Automation skeleton. It registers successfully,
  observes current window metadata and a best-effort UIA control tree, and
  supports `wait`. `click`, `type`, and `hotkey` are intentionally placeholders
  until the desktop input policy is tightened.

## Workflow format

Workflows are JSON files with `schema_version`, `id`, `provider`, `inputs`,
`steps`, `failure_policy`, and optional memory hints. Version `1.0` is the only
supported workflow schema today. Template placeholders like `{{keyword}}` are
replaced from runtime inputs before execution.

Run the debug CLI:

```powershell
python -m openchronicle.rpa.cli list-providers
python -m openchronicle.rpa.cli validate-workflow examples\rpa\workflows\xiaohongshu_search.workflow.json
python -m openchronicle.rpa.cli run-workflow examples\rpa\workflows\android_open_app.workflow.json --provider android_adb --inputs "{\"package\":\"com.android.settings\"}"
```

If ADB or a device is unavailable, the provider returns structured errors and
the runner writes a trace instead of crashing.

## Trace output

Each workflow execution gets a `task_id`. Step records are written as JSONL to:

```text
<OPENCHRONICLE_ROOT>/rpa/traces/<task_id>.trace.jsonl
```

Screens and reusable workflow artifacts belong under:

```text
<OPENCHRONICLE_ROOT>/rpa/screens/
<OPENCHRONICLE_ROOT>/rpa/workflows/
```

Each trace record contains timestamp, workflow id, provider, step id,
observation summary, action, result, and safety assessment. Later distillation
can promote repeated successful traces into workflow skill candidates without
polluting the core Markdown memory files.

## OCR

OCR is optional. `EmptyOCRObserver` returns an empty result and keeps the RPA
framework usable. `PaddleOCRObserver` is available when `paddleocr` is installed
and is loaded lazily on the first OCR call.

`tap_text` first tries OCR boxes and clicks the matching text center. If OCR is
empty or misses the text, it can use `fallback_area` and click that rectangle's
center. Without a fallback area, the action fails and the runner records the
failed step in trace.

Providers expose screenshot concepts through observe options: `keyframe` for
important workflow checkpoints, `region` for bounded OCR/crop work, and `full`
for explicit full-screen debugging. The runner does not request full-screen
screenshots for ordinary steps by default.

## Safety

The shared safety policy blocks raw shell style actions and requires explicit
confirmation for categories such as payment, order, delete, send_message,
login, and permission_grant. Android does not expose arbitrary `adb shell`
through the RPA provider; it only calls fixed, whitelisted `ADBController`
methods, which also retain the existing ADB denylist.

Safety refusals are written to trace as blocked step results.

## Add a new RPA Provider

A provider is a small package under `src/openchronicle/rpa/providers/`. Keep it
thin: the adapter should translate OpenChronicle's common workflow actions into
the backend's native automation API, while trace, workflow loading, retry, and
safety stay in the shared harness.

Provider directory structure:

```text
src/openchronicle/rpa/providers/<provider_name>/
├─ __init__.py
├─ manifest.json
├─ adapter.py
├─ actions.py          optional action helpers
├─ screenshot.py       optional screenshot/keyframe helpers
├─ input.py            optional input/coordinate helpers
└─ safety.py           optional provider-specific policy helpers
```

Minimal `manifest.json`:

```json
{
  "name": "browser_playwright",
  "type": "browser_rpa",
  "platform": ["browser"],
  "actions": ["click", "type", "wait", "navigate", "takeover"],
  "observe": ["page_title", "url", "accessibility_tree", "screenshot"],
  "safety_level": "medium",
  "requires_confirmation": [
    "payment",
    "order",
    "delete",
    "send_message",
    "login",
    "permission_grant"
  ],
  "memory_output": ["trace", "keyframes", "workflow_result", "skill_candidate"]
}
```

Minimal `adapter.py`:

```python
from __future__ import annotations

from typing import Any

from openchronicle.rpa.provider import RPAProvider
from openchronicle.rpa.safety import assess_action


class Provider(RPAProvider):
    name = "browser_playwright"
    platform = "browser"

    def observe(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        return {
            "ok": True,
            "provider": self.name,
            "platform": self.platform,
            "errors": [],
            "page_title": "",
            "url": "",
            "screenshot": "" if options.get("screenshot") else "",
        }

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        safety = assess_action(action)
        if not safety["allowed"]:
            return {
                "ok": False,
                "status": "blocked",
                "message": safety["reason"],
                "action": action,
                "safety": safety,
            }

        kind = str(action.get("action") or action.get("type") or "")
        if kind == "wait":
            return {
                "ok": True,
                "status": "success",
                "message": "waited",
                "action": action,
            }
        return {
            "ok": False,
            "status": "unsupported",
            "message": f"unsupported action: {kind}",
            "action": action,
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "actions": ["click", "type", "wait", "navigate", "takeover"],
            "observe": ["page_title", "url", "accessibility_tree", "screenshot"],
            "screenshot_modes": ["keyframe", "region", "full"],
            "safety": {
                "requires_confirmation": [
                    "payment",
                    "order",
                    "delete",
                    "send_message",
                    "login",
                    "permission_grant",
                ]
            },
        }

    def stop(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "stopped",
            "provider": self.name,
        }
```

Unified return formats:

- `observe(options)` should return `ok`, `provider`, `platform`, `errors`, and
  any observation fields such as `screenshot`, `ocr`, `screen_size`,
  `page_title`, `url`, `window_title`, or `control_tree`.
- `act(action)` should return `ok`, `status`, `message`, and `action`.
  Use `status` values such as `success`, `failed`, `blocked`, `unsupported`, or
  `takeover`.
- `capabilities()` should return supported `actions`, supported `observe`
  fields, optional `screenshot_modes`, and provider safety notes.
- `stop()` should return `ok`, `status`, and `provider`.

Workflow provider selection:

```json
{
  "schema_version": "1.0",
  "id": "open_dashboard",
  "provider": "browser_playwright",
  "platform": "browser",
  "steps": [
    {
      "id": "navigate",
      "action": "navigate",
      "url": "https://example.com/dashboard"
    }
  ]
}
```

Trace output is provider-neutral JSONL. Each line follows this shape:

```json
{
  "task_id": "6f2d...",
  "workflow_id": "open_dashboard",
  "provider": "browser_playwright",
  "step_id": "navigate",
  "timestamp": "2026-04-27T16:30:00+08:00",
  "observation": {
    "app": "",
    "window_title": "",
    "screen_size": [],
    "ocr_texts": [],
    "screenshot": "",
    "errors": []
  },
  "action": {
    "action": "navigate",
    "url": "https://example.com/dashboard"
  },
  "result": {
    "ok": true,
    "status": "success",
    "message": ""
  },
  "safety": {
    "risk": "low",
    "confirmed": false,
    "allowed": true,
    "requires_confirmation": [],
    "reason": ""
  }
}
```

New provider tests should cover:

- manifest loads and registry discovers the provider
- missing manifest fields fail validation
- `capabilities()` includes the actions used by example workflows
- `observe()` returns the common shape and does not crash when the backend is
  unavailable
- `act()` succeeds for at least one safe action
- blocked or confirmation-required actions return `status: "blocked"`
- workflow execution writes a trace line for success and failure
- screenshot modes stay lightweight: ordinary steps should not save full-screen
  screenshots by default
- provider-specific fallback behavior, such as OCR fallback areas or browser
  selector fallback

Future provider guidance:

- Playwright should prefer DOM, URL, title, and accessibility-tree observation
  before screenshots. Use screenshots as keyframes, region captures, or failure
  artifacts.
- iOS should expose a fixed action surface over XCTest/WebDriverAgent-style
  primitives. Do not expose arbitrary device shell commands through workflows.
- HarmonyOS should mirror the Android provider shape where possible: app
  identity, screen size, UI tree, tap/swipe/type, back/home, and takeover.
- API RPA should model HTTP calls as actions, observations as structured
  response summaries, and safety checks around mutation, deletion, payment, and
  bulk-send endpoints.

## Open-AutoGLM influence

The harness borrows the useful separation of phone observation, action
execution, and repair hooks from Open-AutoGLM, but it does not import or require
Open-AutoGLM. The default path is OCR plus `workflow.json` plus trace replay.
VLM repair can be added later for unknown pages, repeated OCR failure, or
exception recovery, not as a per-step dependency.

## Future providers

Playwright browser automation, iOS, HarmonyOS, and API automation should join by
adding a provider manifest and adapter. Workflows should continue to target the
same provider-neutral step shape so successful traces remain reusable across
automation backends where possible.
