# Reader MCP Server

The daemon hosts a read-only MCP server at `http://127.0.0.1:8742/mcp` (by default, via Streamable HTTP). Any MCP client on the machine can attach — Claude Code, Claude Desktop, Codex, opencode, custom agents…

> ChatGPT Desktop is a special case: its MCP client lives in OpenAI's cloud and can't reach `127.0.0.1`. It requires a public tunnel (ngrok / Cloudflare Tunnel) with the obvious data-egress trade-offs — see [the ChatGPT Desktop section below](#chatgpt-desktop).

> **Note (2026-04-01).** We default to `streamable-http` because the older SSE transport was deprecated and sunset per MCP spec 2025-03-26. SSE (`/sse`) is still available if you set `transport = "sse"` in config — kept for clients that haven't migrated — but it's on borrowed time.

## Why in-daemon

Two reasons:

1. **Stable URL.** Your clients can be configured once. They don't need to know how to spawn OpenChronicle.
2. **Warm process.** A stdio-per-client server would have to boot litellm / SQLite / read the config on every connection. Hosting inside the daemon means all that is already loaded.

stdio is still available for clients that only speak it (`openchronicle mcp`).

## Server instructions

`build_server` passes a server-level `instructions` string to FastMCP so MCP-aware clients know **this is the user's personal memory** and should be consulted before answering personal questions. The gist:

> OpenChronicle is the user's local personal memory — calendar, identity, preferences, projects, people, recent activity. CALL THESE TOOLS FIRST whenever the user asks about THEMSELVES: *"when is my interview?" / "what am I working on?" / "do I prefer X or Y?" / "who is Alice?"* — prefer this memory over replying "I don't know."

The instructions teach the client there are **two layers** of memory and that compressed memory rarely tells the whole story:

- **Compressed memory** (Markdown files) — the durable, distilled layer. Tools: `list_memories`, `read_memory`, `search`, `recent_activity`.
- **Raw captures** (the S1 buffer) — what was literally on screen. Tools: `current_context`, `search_captures`, `read_recent_capture`.

The canonical flows spelled out for the client are:

- "What am I doing right now?" → `current_context()` (one call, returns recent S1 + timeline blocks).
- Keyword that might be on screen but not yet in memory → `search_captures` (raw layer) before falling back to `search` (compressed).
- Compressed → raw drill-down: every event-daily sub_task ends with an inline breadcrumb like `— raw: read_recent_capture(at="14:30", app_name="Cursor")` — call it verbatim.

## Tools

All tools return JSON strings. Defined in `mcp/server.py`. Descriptions below match the docstrings the MCP client receives (trimmed).

### `list_memories(include_dormant=false, include_archived=false)`

*"First-hop tool. List all memory files with their descriptions and entry counts. Call this whenever the user asks about themselves, their schedule, preferences, or ongoing work."*

Returns metadata for every memory file (not the contents).

```json
{
  "count": 3,
  "files": [
    {
      "path": "user-profile.md",
      "description": "Identity and background",
      "tags": ["identity"],
      "status": "active",
      "entry_count": 4,
      "created": "2026-04-20T14:02:11+08:00",
      "updated": "2026-04-21T09:15:00+08:00"
    },
    ...
  ]
}
```

Good prompt strategy: call this first, let the model decide which files look relevant, then `read_memory` only those.

### `read_memory(path, since?, until?, tags?, tail_n?)`

*"Read the full contents of ONE memory file the user has on disk. Use after `list_memories` / `search` points you at a promising file."*

Fetch one file. Supports filtering:

- `since` / `until` — ISO timestamp bounds on entries.
- `tags` — keep only entries intersecting these tags.
- `tail_n` — only the last N (after other filters).

```json
{
  "path": "user-profile.md",
  "description": "Identity and background",
  "tags": ["identity"],
  "status": "active",
  "updated": "2026-04-21T09:15:00+08:00",
  "entry_count": 4,
  "entries": [
    {
      "id": "20260421-0915-c4f1",
      "timestamp": "2026-04-21T09:15:00+08:00",
      "tags": ["work", "employer"],
      "body": "User joined Acme Corp as a senior engineer.",
      "superseded_by": null
    }
  ]
}
```

Superseded entries include their replacement ID, so agents can follow the chain.

### `search(query, paths?, since?, until?, top_k=5, include_superseded=false)`

*"BM25 full-text search across every entry in every memory file. Best tool when you have specific keywords — a person's name, project / company name, topic, date, file path, or a phrase the user might have used."* Example invocations surfaced in the docstring: `search("interview")`, `search("Alice Q3 roadmap")`, `search("deadline Friday")`.

BM25 full-text search across `entries_fts`.

- `paths` — list of GLOB patterns (`project-*.md`, `user-*.md`). Omit to search everywhere.
- `since` / `until` — ISO timestamp bounds.
- `top_k` — default from `search.default_top_k`.
- `include_superseded` — surface old versions too. Default `false` per `search.filter_superseded_by_default`.

Result entries carry `rank` (BM25 score, lower = better match).

### `recent_activity(since?, limit=20, prefix_filter?)`

*"Newest-first cross-file feed of recent memory entries. Best tool for open-ended 'what's new / what has the user been up to' questions."*

Cross-file timeline of recent entries, newest first. `prefix_filter` keeps only entries whose path starts with any of `["project-", "user-", …]`.

### `search_captures(query, since?, until?, app_name?, limit=10)`

*"Keyword search over RAW screen captures (the uncompressed S1 layer). PREFER this over `search` when the user mentions a keyword they would have typed or read on screen — error messages, code symbols, file paths, URLs, content from a doc they were reading."*

BM25 + snippet search backed by `captures_fts` (an FTS5 virtual table populated write-through by the capture scheduler — see [capture.md](capture.md#search-index-captures_fts)). Tokens in the snippet are wrapped with `[…]` for highlighting. Each hit's `file_stem` is the handle to drill in via `read_recent_capture(at=<timestamp>, app_name=<app>)`.

Arguments:

- `query` — free-text keywords. FTS5-tokenized (case-insensitive). Special chars (`":*()`) are stripped to avoid query-syntax crashes.
- `since` / `until` — ISO timestamp bounds on capture time.
- `app_name` — case-insensitive substring on the capturing app name (`window_meta.app_name`).
- `limit` — top-K BM25 hits.

Returns:

```json
{
  "query": "rate limiter",
  "results": [
    {
      "timestamp": "2026-04-22T14:32:08+08:00",
      "app_name": "Safari",
      "bundle_id": "com.apple.Safari",
      "window_title": "How rate limiters work",
      "url": "https://example.com/rate-limiters",
      "snippet": "…about how a [rate] [limiter] interacts with…",
      "rank": -1.49e-06,
      "file_stem": "2026-04-22T14-32-08p08-00",
      "focused_role": "",
      "focused_value_preview": ""
    }
  ]
}
```

### `current_context(app_filter?, headline_limit=5, fulltext_limit=3, timeline_limit=8)`

*"First-hop tool for 'what is the user doing RIGHT NOW' questions. Returns a one-shot snapshot of the current screen state."*

This ports the payload that Einsia-Partner auto-injects into every chat turn. Three sections:

- `recent_captures_headline` — last N captures as compact lines (`{time, app_name, window_title, focused_role, file_stem}`). Quick scan of "what's live".
- `recent_captures_fulltext` — top M captures deduplicated by `(app_name, window_title)`, carrying the **full** `visible_text` and `focused_value`. The actual content on screen.
- `recent_timeline_blocks` — the last K 1-min timeline blocks (LLM-summarized activity slices), chronological order so the model can see the trajectory into "now".

Use whenever the user's question depends on what's on their screen this moment, not on durable memory: *"我在干嘛?"*, *"summarize the doc I'm reading"*, *"is the deploy log still streaming?"*. For drill-down on any specific moment, follow with `read_recent_capture(at=..., app_name=...)`.

### `read_recent_capture(at?, app_name?, window_title_substring?, include_screenshot=false, max_age_minutes=15)`

*"Uncompressed screen content from the raw capture buffer. Use when a compressed memory entry is not specific enough (e.g. an event-daily entry says 'edited main.py at 14:30' but you need the actual code/text)."*

Reads straight out of `~/.openchronicle/capture-buffer/*.json`. The buffer is retained per `[capture]` (7 days by default); captures older than `screenshot_retention_hours` have their `screenshot` field stripped but keep `visible_text` + `focused_element` + `url`.

Arguments:

- `at` — ISO timestamp (`"2026-04-22T14:30"`) or bare `"HH:MM[:SS]"` (today, local). Omit for the newest matching capture.
- `app_name` — case-insensitive substring of `window_meta.app_name`.
- `window_title_substring` — case-insensitive substring of the window title.
- `include_screenshot` — include the base64 JPEG. Default false — screenshots are large.
- `max_age_minutes` — when `at` is given, only return captures within this many minutes of `at`. Default 15.

Returns `null` if nothing matches. Otherwise:

```json
{
  "timestamp": "2026-04-22T14:30:12+08:00",
  "file": "2026-04-22T14-30-12p08-00.json",
  "app_name": "Cursor",
  "bundle_id": "com.todesktop.230313mzl4w4u92",
  "window_title": "main.py — openchronicle",
  "url": null,
  "focused_element": {
    "role": "AXTextArea",
    "title": "",
    "value": "def read_recent_capture(...):\n    ...",
    "is_editable": true,
    "value_length": 182
  },
  "visible_text": "### main.py — openchronicle\n\n...(~10k chars of rendered AX)",
  "screenshot_stripped": false
}
```

**Typical flow.** Read an event-daily entry, see `[14:30-14:35, Cursor] 编辑了 main.py` → call `read_recent_capture(at="14:30", app_name="Cursor")` → get the actual file contents from that moment. This is the bridge between the compressed activity log and the uncompressed screen state.

### `get_schema()`

*"Return the memory organization spec (file naming, what each prefix means). Rarely needed at query time."*

Returns the verbatim contents of `prompts/schema.md`. For normal "look up a fact" flows, prefer `search` / `list_memories` — `get_schema` is really only useful if the agent needs to reason about *where* a new fact would be stored, or explain the memory layout to the user.

## Client setup

### Claude Code

```bash
openchronicle install claude-code            # add / refresh the entry
openchronicle uninstall claude-code          # remove it
```

`install` runs `claude mcp add --transport http -s user openchronicle http://127.0.0.1:8742/mcp` under the hood. Every invocation is idempotent — if an `openchronicle` entry already exists at the target scope, it's removed and re-registered with the current URL/transport. `uninstall` calls `claude mcp remove -s user openchronicle`; a missing entry is treated as success. Change scope on either command with `--scope {user,local,project}` — `uninstall` must match the scope `install` used.

### Codex CLI

```bash
openchronicle install codex            # add / refresh the entry
openchronicle uninstall codex          # remove it
```

`install` shells out to `codex mcp add openchronicle --url http://127.0.0.1:8742/mcp` (Codex CLI's native streamable-HTTP registration). The entry lands in `~/.codex/config.toml`, which is shared between the Codex CLI and the Codex IDE extension — one install covers both. Re-running is idempotent: an existing `openchronicle` entry is removed and re-registered with the current URL. `uninstall` calls `codex mcp remove openchronicle`; a missing entry is treated as success.

Requires `codex` on `PATH`. Install from [openai/codex](https://github.com/openai/codex) if needed.

### opencode

```bash
openchronicle install opencode            # add / refresh the entry
openchronicle uninstall opencode          # remove it
```

`install` merges this entry into `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "openchronicle": {
      "type": "remote",
      "url": "http://127.0.0.1:8742/mcp",
      "enabled": true
    }
  }
}
```

[opencode](https://opencode.ai) supports remote streamable-HTTP MCP servers natively (top-level `mcp` key, not `mcpServers`), so the daemon's always-on endpoint is the right target. Re-running is idempotent: the `openchronicle` entry is overwritten with the current URL while every other `mcp.*` entry and top-level key is preserved. `uninstall` removes just that entry; a missing config / missing entry is treated as success.

If your opencode config lives in `opencode.jsonc` (JSON-with-comments), `install` bails rather than stripping your comments — add the entry by hand in that case.

### Claude Desktop

```bash
openchronicle install claude-desktop            # add / refresh the entry
openchronicle uninstall claude-desktop          # remove it
```

Writes `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openchronicle": {
      "command": "/Users/kming/.local/bin/openchronicle",
      "args": ["mcp"]
    }
  }
}
```

**Important constraints** (from [Anthropic's MCP docs](https://modelcontextprotocol.io/docs/develop/connect-local-servers)):

- Claude Desktop's JSON config accepts **only stdio servers** — remote SSE / Streamable HTTP URLs must be added via Settings → Integrations in the UI. So we register `openchronicle mcp` as a subprocess command, not a URL.
- Absolute paths are required. Claude Desktop runs from the GUI with a minimal `PATH`; `shutil.which("openchronicle")` is used to resolve the full path. If `openchronicle` isn't on `PATH`, install it first with `uv tool install .` from the repo.
- **Restart required.** Claude Desktop only reads this file at launch. After install / uninstall, completely quit the app (**Cmd+Q**) and reopen it — you don't need to log in again, your session persists. Merely closing the window is not enough.
- Existing `mcpServers` entries are preserved. The command does a read-merge-write, not a clobber.

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "openchronicle": {
      "url": "http://127.0.0.1:8742/mcp"
    }
  }
}
```

### ChatGPT Desktop

> ⚠️ **This path requires exposing OpenChronicle's MCP endpoint to the public internet.** ChatGPT's MCP client runs in OpenAI's cloud, not on your Mac — it dispatches tool calls from OpenAI's servers, so `127.0.0.1:8742` is unreachable from its side. If that trade-off isn't acceptable for you, stick to Claude Desktop / Claude Code / Cursor, which all speak to the local endpoint directly.

There is **no stdio option for ChatGPT Desktop today**, and there is no `openchronicle install chatgpt-desktop` command because the connector config is UI-only on OpenAI's side. The flow is documented end-to-end below so you understand what data leaves your machine before you enable it.

#### What actually happens to your data

When ChatGPT calls any OpenChronicle tool, the request and response traverse:

```
ChatGPT Desktop (your Mac)
     ↓ over the internet
OpenAI's MCP dispatcher (their cloud)
     ↓ over the internet
Your public tunnel (ngrok / Cloudflare Tunnel / …)
     ↓ localhost loopback
OpenChronicle daemon on :8742
```

The response flows back the same way. That means *every* `current_context` payload (full visible_text of your screen), *every* `read_memory` / `search_captures` hit (your memory entries + raw captured text), and *every* `read_recent_capture` (what you were looking at at a given minute) is transmitted across at least two third-party networks. This is the opposite of the "nothing leaves the machine" property advertised in the project README, so opt in deliberately.

#### Setup

1. **Enable Developer Mode** in ChatGPT. Web or desktop: Settings → Apps & Connectors → Advanced → toggle "Developer Mode". (Beta feature; your plan must have access. Team / Enterprise users may need an admin to allow `Create custom MCP connectors` in Workspace Settings → Permissions & Roles.)

2. **Expose the daemon via a tunnel.** The daemon must already be running (`openchronicle start`). Pick one:

    ```bash
    # ngrok (simplest; free tier gives a rotating URL)
    ngrok http 127.0.0.1:8742

    # Cloudflare Tunnel (free, supports a stable *.trycloudflare.com URL)
    cloudflared tunnel --url http://127.0.0.1:8742
    ```

    Both print a public HTTPS URL. Take note — the full MCP endpoint is that URL plus the `/mcp` path (e.g. `https://abcd-1234.ngrok-free.app/mcp`).

3. **Create the connector in ChatGPT.** Settings → Connectors → the "Create" button in the top-right. Fill in:
    - **Name:** `openchronicle`
    - **Server URL:** the `https://<tunnel-host>/mcp` from step 2
    - **Authentication:** None (we don't ship auth today — see warning below)
    - **Transport:** Streamable HTTP (matches our default `mcp.transport = "streamable-http"`)

4. **Start a chat in Developer Mode** — in the Plus menu of the composer, select Developer Mode and tick the `openchronicle` connector. Tool calls now route through the tunnel.

5. **Refresh on changes.** If you upgrade OpenChronicle and the tool list changes, open Settings → Connectors → `openchronicle` → Refresh to re-pull the tool schemas. ChatGPT caches them per connector.

#### Hard caveats

- **No auth on the endpoint.** Anyone who discovers your tunnel URL can query your memory. ngrok's default URLs are long random strings (not brute-forceable in practice), but they're sent over TLS to OpenAI unencrypted from ngrok's perspective, and ngrok's free tier keeps traffic logs. A future OpenChronicle release will likely add a `mcp.auth_token` config for this path — until then, treat the tunnel URL as a secret.
- **URL rotates on free ngrok.** Each `ngrok http` invocation gets a new URL. Either pay for a reserved domain, use Cloudflare Tunnel's `--url` mode, or re-paste the URL into ChatGPT on restart. Cloudflare's free `trycloudflare.com` URLs are also ephemeral but tend to be more stable than ngrok's.
- **Daemon must be running.** If you `openchronicle stop` or the daemon crashes, the tunnel still forwards — but to nothing. ChatGPT will surface a tool error.
- **Latency.** Two internet hops means each tool call takes 100–500 ms even though the local DB query is <10 ms. Usable, but noticeable vs the direct-stdio clients.

If the security trade-off isn't worth it but you still want ChatGPT-style workflows, Codex CLI (`openchronicle install codex`) speaks to `127.0.0.1` directly and stays on your machine.

### Other agent frameworks (Cline, Continue, Zed, Windsurf, custom)

Most local agent frameworks consume an `mcpServers` JSON object with the same shape. The quickest path:

```bash
openchronicle install mcp-json                 # writes ./mcp.json (stdio entry)
openchronicle install mcp-json --http          # emits a URL entry using the configured HTTP endpoint
openchronicle install mcp-json --name memory --filename .mcp.json --force
```

Flags:

- `--name <str>` — server key inside `mcpServers` (default `openchronicle`).
- `--filename <str>` — output filename (default `mcp.json`, written to CWD).
- `--http` — emit `{url, transport}` instead of the default `{command, args}`. Requires `mcp.transport` to be `sse` or `streamable-http`.
- `--force` / `-f` — overwrite if the file already exists.

Default (stdio) output:

```json
{
  "mcpServers": {
    "openchronicle": {
      "command": "/Users/kming/.local/bin/openchronicle",
      "args": ["mcp"]
    }
  }
}
```

With `--http`:

```json
{
  "mcpServers": {
    "openchronicle": {
      "url": "http://127.0.0.1:8742/mcp",
      "transport": "http"
    }
  }
}
```

Merge this into your framework's existing MCP config (or point it at the file directly). There is no matching `uninstall` — delete the file or remove the key by hand.

### stdio fallback

For clients that don't yet support SSE/HTTP, run a stdio proxy:

```json
{
  "mcpServers": {
    "openchronicle": {
      "command": "uv",
      "args": ["--directory", "/path/to/openchronicle", "run", "openchronicle", "mcp"]
    }
  }
}
```

`openchronicle mcp` spins up a fresh `FastMCP` server on stdio. It reads the same `index.db` as the daemon (SQLite WAL allows concurrent readers) — so the daemon and this proxy can run side by side safely.

## Transport in config

```toml
[mcp]
auto_start = true
transport = "streamable-http"   # "streamable-http" | "sse" (deprecated) | "stdio"
host = "127.0.0.1"
port = 8742
```

- `auto_start = false` disables the in-daemon server entirely. Useful if you want stdio-only.
- `transport = "stdio"` tells the daemon *not* to host a network server — use only if you know your clients all use stdio.
- `host = "127.0.0.1"` is deliberate. Binding to 0.0.0.0 would expose your memory to the LAN. Don't.

## Permissions model

Every tool is read-only. There is no MCP tool to mutate memory — writes are the writer's job alone. This is a hard guarantee, not a convention; `mcp/server.py` imports only read paths from `store/`.

If you want to let an agent *write* (e.g., a dedicated "learn this fact" command), don't add a tool here. Instead, add a capture of the agent's explicit statement to the capture buffer and let the normal writer pipeline decide.
