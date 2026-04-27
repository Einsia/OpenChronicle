# OpenChronicle RPA Harness Audit and Fix

Date: 2026-04-27

## Scope

This pass was intentionally small:

- audit the current repository state without refactoring
- classify the RPA harness into real, mock, and missing pieces
- fix only small and explicit issues
- verify the backend and frontend build/test surfaces

## Current Core Module Inventory

### Real backend modules

- `src/openchronicle/capture/*`
- `src/openchronicle/session/*`
- `src/openchronicle/timeline/*`
- `src/openchronicle/store/*`
- `src/openchronicle/writer/*`
- `src/openchronicle/mcp/server.py`
- `src/openchronicle/mcp/captures.py`
- `src/openchronicle/mcp/adb_server.py`
- `src/openchronicle/adb/*`
- `src/openchronicle/rpa/*`
- `src/openchronicle/rpa/providers/android_adb/*`
- `src/openchronicle/rpa/providers/windows_uia/*`

### UI and demo layer

- `ui/src/pages/rpa/*`
- `ui/src/components/rpa/*`
- `ui/src/mock/rpaHarnessMock.ts`
- `ui/src/mock/rpaMultiPageMock.ts`
- `ui/src/types/rpa.ts`

## Closed-Loop Assessment

### 1. Provider 接入

Implemented.

- Provider discovery and loading exist in `src/openchronicle/rpa/registry.py`
- Provider contract exists in `src/openchronicle/rpa/provider.py`
- Built-in providers exist for Android ADB and Windows UIA

### 2. Device 管理

Partial.

- Android device control is real through `src/openchronicle/adb/*`
- Windows foreground/control-tree capture is real through `src/openchronicle/capture/windows_uia.py`
- There is no dedicated persistent fleet manager or device inventory service in the backend
- The UI device pages are mock-driven

### 3. Workflow 录制

Partial.

- Workflow JSON examples exist under `examples/rpa/workflows`
- The runner can execute workflows and write traces
- The UI recording flow is presentation-only
- There is no backend recorder that converts live interaction events into a canonical workflow artifact

### 4. Workflow Schema

Implemented.

- `src/openchronicle/rpa/workflow.py` validates schema version, provider, steps, and inputs
- `schema_version = "1.0"` is enforced

### 5. 校验断言

Implemented.

- `verify_step()` performs simple verification checks
- Safety policy enforcement exists in `src/openchronicle/rpa/safety.py`
- Android-specific safety is stricter in `src/openchronicle/rpa/providers/android_adb/safety.py`

### 6. Runner 执行

Implemented.

- `src/openchronicle/rpa/runner.py` executes workflows step by step
- It records trace output and blocks unsupported or unsafe actions

### 7. Trace 回放

Partial.

- Trace writing exists in `src/openchronicle/rpa/trace.py`
- The UI has replay views, but they are mock-backed
- There is no dedicated backend replay executor that can faithfully replay a trace against a provider

### 8. Skill 沉淀

Missing as backend logic.

- Provider manifests advertise `skill_candidate`
- The UI has Skill Builder screens and mock data
- There is no backend trace-to-skill promotion pipeline yet

### 9. Memory 写入

Implemented.

- Durable memory storage exists in `src/openchronicle/store/*`
- Session and timeline reduction exist in `src/openchronicle/session/*` and `src/openchronicle/timeline/*`
- Writer / classifier / reducer paths are present

### 10. MCP 查询

Implemented.

- Compressed memory tools exist in `src/openchronicle/mcp/server.py`
- Raw capture query tools exist in `src/openchronicle/mcp/captures.py`
- ADB tool exposure exists in `src/openchronicle/mcp/adb_server.py`

### 11. Safety 安全治理

Implemented.

- Shared RPA safety policy exists in `src/openchronicle/rpa/safety.py`
- Android provider safety denylist and confirmation policy exist
- Tests cover blocked actions and confirmation-required actions

## Mock Modules

- `ui/src/mock/rpaHarnessMock.ts`
- `ui/src/mock/rpaMultiPageMock.ts`
- most of `ui/src/pages/rpa/*`
- most of `ui/src/components/rpa/*`
- `ui/src/types/rpa.ts` is a UI contract layer, not the backend source of truth

The UI is intentionally mock-first and currently does not drive the backend directly.

## Missing Modules

The main missing backend pieces are:

- a real workflow recorder that emits workflow JSON from live UI actions
- a backend trace replay engine
- a trace-to-skill distillation pipeline
- a persistent device-fleet manager
- a real UI/backend integration layer for the RPA console

## RPA Harness Architecture (Second Execution Chain)

The RPA Harness is intentionally additive to the memory daemon. The current backend shape is:

- **Provider layer**: `openchronicle.rpa.provider` contract, `openchronicle.rpa.registry` manifest-backed discovery.
- **Device backends**: provider implementations (today: `android_adb`, `windows_uia`) translate actions/observe into native automation primitives.
- **Workflow layer**: `openchronicle.rpa.workflow` validates schema + renders `{{inputs}}` templates.
- **Safety layer**: `openchronicle.rpa.safety` blocks dangerous actions and enforces confirmation categories.
- **Runner layer**: `openchronicle.rpa.runner` executes steps with optional retries and simple verify assertions.
- **Trace layer**: `openchronicle.rpa.trace` writes provider-neutral JSONL traces to `<OPENCHRONICLE_ROOT>/rpa/traces`.
- **Future distillation layer (missing)**: promote successful traces into reusable skill artifacts.
- **Future memory bridging (missing for RPA)**: write distilled skills (not raw traces) into the memory store and expose via MCP.

This chain is separate from the capture/timeline/session/writer pipeline described in `docs/architecture.md`.

## Open-AutoGLM Reuse Notes (Local Copy Under `../Open-AutoGLM`)

Open-AutoGLM is an LLM-driven interactive agent loop, not a workflow recorder/replay engine. The most reusable pieces are:

- **Device abstraction**: `Open-AutoGLM/phone_agent/device_factory.py` and its concrete backends (`adb/`, `hdc/`, `xctest/`) map well to additional OpenChronicle providers.
- **Safety/confirmation hooks**: `Open-AutoGLM/phone_agent/actions/handler.py` uses a confirmation callback for sensitive operations and a takeover hook for login/captcha style manual steps. Those concepts align with OpenChronicle's `confirmed` safety flag and future "takeover" steps.
- **Sensitive screenshot fallback**: `Open-AutoGLM/phone_agent/adb/screenshot.py` returns a black placeholder with an `is_sensitive` flag when screenshots are blocked. OpenChronicle can adopt the same pattern for provider observations so traces record "sensitive" explicitly.

What is NOT directly reusable (needs new modules in OpenChronicle):

- **Trace -> Skill distillation**: Open-AutoGLM does not provide a trace-mining pipeline for reusable skills.
- **Workflow recorder**: Open-AutoGLM actions are produced by a model, not recorded from user actions into a canonical workflow artifact.
- **Replay engine**: Open-AutoGLM is "decide then act"; it doesn't implement deterministic "replay this recorded trace" with assertion checks.

New backend modules to add for the above goals (suggested minimal surface):

- `openchronicle.rpa.recorder`: normalize live provider events into `workflow.json` + attach keyframes to `rpa/screens/`
- `openchronicle.rpa.replay`: deterministic executor that replays a trace file (or workflow) and produces a new trace with diffs
- `openchronicle.rpa.distill`: trace clustering + step canonicalization + metadata -> `skill.json` candidates
- `openchronicle.mcp.rpa`: MCP tools for listing traces, reading a trace, and listing distilled skills (not raw UI mocks)

## Fixes Made

### Production-side fixes already present in the working tree

These were the small, explicit runtime fixes in the working tree when this audit ran:

- `src/openchronicle/capture/scheduler.py`: read capture JSON as bytes
- `src/openchronicle/capture/windows_uia.py`: avoid comparing a `None` focused control against foreground identity
- `src/openchronicle/cli.py`: read config / capture JSON as bytes
- `src/openchronicle/mcp/captures.py`: read capture JSON as bytes
- `src/openchronicle/rpa/manifest.py`: read manifest JSON as bytes
- `src/openchronicle/rpa/workflow.py`: read workflow JSON as bytes

### Additional fix applied in this pass

- `tests/conftest.py`: added a local-only pytest `tmp_path` fixture and `pytest_configure()` setup so tests use a writable workspace path instead of the restricted system temp directory

This was a test-harness fix only. It does not change production behavior.

### Additional fixes in this pass (ADB connectivity)

- `src/openchronicle/adb/tools.py`: add `adb_pair` and `adb_connect` helpers for wireless debugging endpoints (useful for Wi-Fi ADB; Bluetooth tethering can work if it provides IP connectivity)
- `src/openchronicle/mcp/adb_server.py`: expose `adb_pair` and `adb_connect` MCP tools
- `tests/test_adb_control.py`: add coverage for pairing/connect recording and safety allowlist

## Remaining Risks

- `skill_candidate` is still only a declared output class; there is no production pipeline that turns traces into reusable skills
- the UI is still mock-driven and does not currently consume the backend as a live API
- trace replay is not yet a first-class backend service
- there is still a Pytest cache warning because `.pytest_cache` on this machine is not writable, though the test run itself passes

## Top 3 Next Fixes

1. Add a real trace-to-skill distillation pipeline and persist generated skill artifacts.
2. Add a backend replay service for traces, not just a UI replay page.
3. Wire the RPA UI to a real API surface and replace the mock data layer incrementally.

## Verification

### Backend

- `python -m compileall src` -> **environment-blocked** on this machine (WinError 5 when writing `.pyc` under `src/**/__pycache__`)
- `uv run pytest --basetemp <writable_dir>` -> passed (workaround: system temp is restricted on this machine)

Final test result:

- `156 passed`
- `1 skipped`
- `1 warning`

### Frontend

The UI package exists and dependencies are already installed (`ui/node_modules` present).

- `npx tsc -b` in `ui/` -> passed (TypeScript project build/typecheck)
- `npm run build` in `ui/` -> failed: `esbuild` cannot spawn its native binary (`spawn EPERM`) in this Windows environment

## Notes

- This Windows environment denies access to the default pytest temp root (`%LOCALAPPDATA%\\Temp\\pytest-of-*`). The test harness overrides `tmp_path` to a known-writable directory under `C:\\Users\\111\\.codex\\memories\\openchronicle-test\\tmp`.
- `uv run pytest` required setting `UV_CACHE_DIR` to a writable directory under `C:\\Users\\111\\.codex\\memories\\...` to avoid OS error 5 from uv's default cache location.
- The frontend `esbuild` native binary is blocked from spawning on this machine; this appears environmental (ACL / security policy / antivirus) rather than a code issue in the repo.
- The repository still contains mock-heavy UI artifacts by design; they should not be mistaken for backend implementation.
