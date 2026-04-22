# Configuration

Runtime config lives at `~/.openchronicle/config.toml` (or `$OPENCHRONICLE_ROOT/config.toml`). It's created with sensible defaults the first time you run `openchronicle status`.

View the resolved config any time with:

```bash
openchronicle config
```

## `[models.*]` — LLM per stage

Every LLM stage goes through [litellm](https://github.com/BerriAI/litellm), so anything litellm speaks will work: OpenAI, Anthropic, Azure, Bedrock, Gemini, Mistral, Ollama, DeepSeek, any OpenAI-compatible gateway…

```toml
[models.default]
model = "gpt-5.4-nano"
api_key_env = "OPENAI_API_KEY"
# base_url = "https://your-gateway/v1"
# api_key  = "sk-..."        # overrides api_key_env if set

[models.timeline]     # short-window normalizer — runs constantly, keep cheap but not weak
# inherits from default

[models.reducer]      # session → event-daily entry
# Consider a stronger model:
# model = "claude-haiku-4-5"
# api_key_env = "ANTHROPIC_API_KEY"

[models.classifier]   # durable-fact extraction via tool calls
# Accuracy-sensitive; a weak model here poisons dedup.

[models.compact]      # file compaction — accuracy matters
# e.g. same as classifier
```

Each stage section **inherits every field** from `[models.default]` and overrides only what it sets. If you want a single model everywhere, set `[models.default]` and leave the rest empty.

Stage → purpose:

| Stage | Runs | What it does |
|---|---|---|
| `timeline` | every 60s while captures exist | Normalizes a short (default 1-min) capture window into a list of activity records with authored text preserved verbatim. |
| `reducer` | on session end + daily safety net | Turns a session's timeline blocks into one event-daily entry with time-ranged sub_tasks. |
| `classifier` | after each successful reducer run | Reads the just-written entry + context, extracts durable facts into user-/project-/tool-/topic-/person-/org- files via a tool-call loop. |
| `compact` | after commits that flag files | Rewrites a fat file; rejects if >5% noun-phrase loss. |

### Fully local with Ollama

OpenChronicle has no hard dependency on a cloud provider — any model litellm can reach works, including a local [Ollama](https://ollama.com/) server. Minimum config:

```toml
[models.default]
model = "ollama/llama3.1:8b"            # any model you've pulled; prefix with ollama/ or ollama_chat/
base_url = "http://localhost:11434"
api_key_env = ""                        # leave blank — Ollama needs no key
```

Tiered assignment is usually worth the trouble — timeline fires every minute, classifier is accuracy-sensitive:

```toml
[models.timeline]
model = "ollama/qwen2.5:7b"             # cheap-but-not-weak; runs constantly

[models.reducer]
model = "ollama/qwen2.5:14b"            # compresses a whole session — precision matters

[models.classifier]
model = "ollama/qwen2.5:14b"            # tool-calling; weak models here poison dedup

[models.compact]
model = "ollama/qwen2.5:14b"            # match classifier or stronger
```

Things to check before trusting a local setup:

- **Tool-calling support is required for the classifier.** It drives `append` / `create` / `supersede` through a function-call loop. `qwen2.5`, `llama3.1`, `mistral-nemo` and `command-r` all work; small Llama-3.2 and Phi variants are unreliable.
- **JSON mode is required for `timeline` and `reducer`.** They pass `response_format={"type":"json_object"}`, which litellm forwards to Ollama as `format: "json"`. If the model ignores it and returns prose, both stages will log parse errors — pick a bigger model.
- **Context window.** Timeline blocks are 1-min, reducer flushes consume ~5 blocks, a 2-hour session can stack ~24 blocks. Set Ollama's `num_ctx` to ≥ 16 k for `timeline`, ≥ 32 k for `reducer` / `classifier`. Tiny defaults (2–4 k) will silently truncate.
- **Leave `api_key_env` empty.** If you keep the default `"OPENAI_API_KEY"` and don't have one exported, litellm complains even though Ollama wouldn't use it.

## `[capture]`

```toml
[capture]
event_driven = true                  # consume mac-ax-watcher events
heartbeat_minutes = 10               # periodic capture even when nothing happens (0 disables entirely)
debounce_seconds = 3.0               # AXValueChanged bursts collapse to one capture
min_capture_gap_seconds = 2.0        # hard floor between consecutive captures, regardless of event reason
dedup_interval_seconds = 1.0         # same-event-type dedup window
same_window_dedup_seconds = 5.0      # non-focus-change events in the same bundle+window are dropped if within this gap
buffer_retention_hours = 168         # 7 days; stale absorbed captures past this are deleted
screenshot_retention_hours = 24      # after 24h, strip screenshot (77% of bytes) but keep AX+text
buffer_max_mb = 2000                 # hard ceiling (MB); oldest absorbed files evicted first (0 disables)
include_screenshot = true
screenshot_max_width = 1920
screenshot_jpeg_quality = 80
ax_depth = 100                       # Electron apps need deep trees; 8 only reaches chrome
ax_timeout_seconds = 3
```

Tuning notes:

- **`ax_depth`.** Native Cocoa apps are fine at 20. Electron apps (Claude Desktop, VS Code, Slack, Notion) put user content past layer 20 — stay at 100 unless you're CPU-constrained.
- **`debounce_seconds`.** Lower = more captures during typing; higher = fewer near-duplicates.
- **`same_window_dedup_seconds`.** When the user types for a long time in the same document, this is the knob that decides how frequently you re-capture the same (bundle, window) pair. Focus changes always bypass this.
- **`heartbeat_minutes`.** Periodic capture as a safety net. `0` disables it completely (watcher-only). Values `>0` are clamped to a 60s floor.
- **`buffer_retention_hours`.** Whole-JSON deletion cutoff. Default 7 days lets `read_recent_capture` reach back that far — shrink to a few hours if you only care about the current work session, bump if you want longer recall.
- **`screenshot_retention_hours`.** After this many hours the screenshot field is stripped (rest of the JSON stays). Screenshots aren't used by timeline / reducer / classifier today — setting this ≪ `buffer_retention_hours` is what makes long retention cheap. `0` or very large values keep screenshots for the full window.
- **`buffer_max_mb`.** Hard ceiling in MB. When exceeded, the cleanup pass evicts oldest absorbed files until under. Set to `0` to disable (pure time-based retention).

## `[timeline]`

```toml
[timeline]
window_minutes = 1                # wall-clock aligned (:00/:01/:02/...)
cold_lookback_minutes = 30        # on first run, at most backfill this far
recent_context_blocks = 720       # ~12h of 1-min blocks; consulted by tooling
```

Timeline is always-on and acts as a **verbatim-preserving normalizer** — it de-duplicates snapshots and strips UI chrome but preserves the user's typed text, URLs, titles, and proper nouns unchanged. Real compression happens in the reducer.

`window_minutes` is effectively locked in once blocks exist — changing it later produces new-sized blocks going forward, but old blocks keep their original boundaries (they're keyed by `(start_time, end_time)`). The default 1-min size pairs with the reducer's flush tick (default 5-min) so each flush consumes ~5 blocks. A larger timeline window cuts LLM calls per hour but risks the model sliding from normalization into summarization.

## `[session]`

```toml
[session]
gap_minutes = 5                 # hard cut: idle > 5 min ends the session
soft_cut_minutes = 3            # soft cut: single unrelated app > 3 min
max_session_hours = 2           # forced cut at 2h
tick_seconds = 30               # check_cuts() interval
flush_minutes = 5               # incremental reducer tick inside an active session (min 5)
```

See [session.md](session.md) for what each rule means and how to tune it.

**Flush ticks.** While a session is still active, every `flush_minutes` the reducer wakes up and compresses any new closed timeline blocks into a partial entry in today's `event-YYYY-MM-DD.md`. This makes long sessions visible in near-real-time instead of waiting for the final cut. Minimum effective value is 5 (clamped) to keep LLM cost bounded — at the default 1-min timeline window, a 5-min flush consumes ~5 blocks. The classifier runs on its own separate cadence (see `[classifier] interval_minutes` below) and does not fire per flush.

## `[reducer]`

```toml
[reducer]
enabled = true                   # run S2 reducer on session end + daily safety net
daily_tick_hour = 23             # local-time hour for the daily safety-net tick
daily_tick_minute = 55
```

Setting `enabled = false` disables both the S2 reducer and the classifier. Sessions still close and persist to the `sessions` table, but no event-daily entries or classifier writes land — useful for capture-only debugging.

## `[classifier]`

```toml
[classifier]
interval_minutes = 30           # durable-fact extraction cadence inside active sessions (min 5)
```

While a session is active, the classifier wakes up every `interval_minutes` and extracts durable facts from event-daily entries written since its last pass. The terminal reduce (at session end) runs one more classifier pass over whatever trailing window the tick didn't reach, so nothing is lost between the final tick and the session close. Each pass advances the session's `classified_end` bookmark so entries are never double-classified.

Values `< 5` are clamped to 5 to keep LLM cost bounded. Pair with `[session] flush_minutes`: the reducer flushes at a higher frequency than the classifier, so a classifier tick always has fresh entries to look at.

## `[writer]`

```toml
[writer]
soft_limit_tokens = 20000        # compact trigger on any single file above this
hard_limit_tokens = 50000        # emergency ceiling
dedup_window_hours = 24          # dedup search horizon before appending
cold_start_conservative_hours = 0 # 0 = off
max_tool_iterations = 12         # classifier tool-call loop hard cap
```

The old per-capture trigger knobs are gone — the writer is driven by session boundaries now. See [writer.md](writer.md) for the full trigger model.

## `[memory]`

```toml
[memory]
auto_dormant_days = 30           # files untouched this long are marked dormant in the index
```

Dormant files don't show in `list_memories` by default. Pass `include_dormant=true` from the MCP client to see them. They're never deleted automatically.

## `[search]`

```toml
[search]
default_top_k = 5
filter_superseded_by_default = true
```

Both apply to MCP `search` calls. Superseded entries are still searchable with `include_superseded=true`.

## `[mcp]`

```toml
[mcp]
auto_start = true                 # run an always-on MCP server inside the daemon
transport = "streamable-http"     # "streamable-http" | "sse" (deprecated) | "stdio"
host = "127.0.0.1"                # keep localhost-only
port = 8742
```

- `streamable-http` — default. Served at `http://<host>:<port>/mcp`.
- `sse` — legacy. Still works but deprecated.
- `stdio` — don't set this in the daemon config; stdio is for per-client spawns via `openchronicle mcp`.

## Environment overrides

- `OPENCHRONICLE_ROOT=/some/path` — move `~/.openchronicle/` entirely. Good for tests, throwaway envs, or separating work and personal memory.
- `OPENAI_API_KEY` (or whichever `api_key_env` you set) — picked up at runtime.

## Validating changes

The daemon reads config once on startup. After editing `config.toml`:

```bash
openchronicle stop && openchronicle start
openchronicle status
```

`status` prints the resolved model for each stage, so a typo in `[models.timeline]` is visible immediately.
