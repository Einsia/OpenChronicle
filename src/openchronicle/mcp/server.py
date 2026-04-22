"""MCP server exposing OpenChronicle memory as read-only tools.

Uses the official `mcp` Python SDK via FastMCP. Runs either standalone
over stdio (`openchronicle mcp`) or in-daemon over streamable-http / sse,
depending on `[mcp] transport`. Exposes eight tools:

  Compressed memory (Markdown layer):
    list_memories, read_memory, search, recent_activity
  Raw captures (S1 buffer):
    current_context, search_captures, read_recent_capture
  Reference:
    get_schema
"""

from __future__ import annotations

import json
from typing import Any

from ..config import Config
from ..config import load as load_config
from ..logger import get
from ..prompts import load as load_prompt
from ..store import files as files_mod
from ..store import fts
from . import captures as captures_mod

logger = get("openchronicle.mcp")


def _list_memories(conn, *, include_dormant: bool = False, include_archived: bool = False) -> dict[str, Any]:
    rows = fts.list_files(
        conn, include_dormant=include_dormant, include_archived=include_archived
    )
    return {
        "count": len(rows),
        "files": [
            {
                "path": r.path,
                "description": r.description,
                "tags": r.tags.split() if r.tags else [],
                "status": r.status,
                "entry_count": r.entry_count,
                "created": r.created,
                "updated": r.updated,
            }
            for r in rows
        ],
    }


def _read_memory(
    conn,
    *,
    path: str,
    since: str | None = None,
    until: str | None = None,
    tags: list[str] | None = None,
    tail_n: int | None = None,
) -> dict[str, Any]:
    p = files_mod.memory_path(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}
    parsed = files_mod.read_file(p)
    entries = parsed.entries
    if since is not None:
        entries = [e for e in entries if e.timestamp >= since]
    if until is not None:
        entries = [e for e in entries if e.timestamp <= until]
    if tags:
        tagset = set(tags)
        entries = [e for e in entries if tagset.intersection(e.tags)]
    if tail_n is not None and tail_n > 0:
        entries = entries[-tail_n:]
    return {
        "path": path,
        "description": parsed.description,
        "tags": parsed.tags,
        "status": parsed.status,
        "updated": parsed.updated,
        "entry_count": parsed.entry_count,
        "entries": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "tags": e.tags,
                "body": e.body,
                "superseded_by": e.superseded_by,
            }
            for e in entries
        ],
    }


def _search(
    conn,
    *,
    query: str,
    paths: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    top_k: int = 5,
    include_superseded: bool = False,
) -> dict[str, Any]:
    hits = fts.search(
        conn,
        query=query,
        path_patterns=paths,
        since=since,
        until=until,
        top_k=top_k,
        include_superseded=include_superseded,
    )
    return {
        "query": query,
        "results": [
            {
                "id": h.id,
                "path": h.path,
                "timestamp": h.timestamp,
                "content": h.content,
                "rank": h.rank,
            }
            for h in hits
        ],
    }


def _recent_activity(
    conn,
    *,
    since: str | None = None,
    limit: int = 20,
    prefix_filter: list[str] | None = None,
) -> dict[str, Any]:
    rows = fts.recent(conn, since=since, limit=limit, prefix_filter=prefix_filter)
    return {
        "count": len(rows),
        "entries": [
            {
                "id": r.id,
                "path": r.path,
                "timestamp": r.timestamp,
                "content": r.content,
            }
            for r in rows
        ],
    }


def _get_schema() -> dict[str, Any]:
    return {"schema": load_prompt("schema.md")}


_SERVER_INSTRUCTIONS = """\
# OpenChronicle — User's local personal memory

OpenChronicle is a **private, local-first store of durable facts about the user and
their machine**. It's the user's own long-term memory, opted into and maintained on
their device. It holds things like:

- Identity & background: name, role, languages, location, skill stack
- Preferences, habits, and working style
- Schedule: meetings, interviews, deadlines, trips, appointments
- Ongoing projects, their state, and recent progress
- People and organizations the user interacts with
- Recent screen-activity summaries (what they've been working on, which tools,
  which files, which errors, which docs)

The user installed this MCP **precisely so agents can look things up instead of
asking or guessing**. Treat it as a cheap, always-available extension of your
context window. A missed lookup is a worse failure mode than an unnecessary one.

---

## ALWAYS-call rules (hard rules — do not skip)

These override your default cost-benefit heuristic. Each rule fires independently;
a single match means you MUST call at least one listed tool BEFORE composing your
reply. The tools are local, respond in milliseconds, and cost nothing.

1. **Demonstrative / pronoun with no antecedent in this conversation.** If the
   user says *"that / this / it / the thing / the bug / the error / the doc /
   那个 / 这个 / 这段 / 这个问题"* and that reference was NOT introduced earlier
   in THIS conversation — ALWAYS call `current_context` first. The user is
   almost always pointing at something on their screen that you literally
   cannot see from chat history. This is the single highest-value lookup.

   ❌ **Failure pattern to avoid:**
   > User: "what's the bug of that?"
   > You: "I don't have any code to look at — could you share…?"

   That response is a bug on your side. You DO have a tool that sees their
   screen. The correct turn is: call `current_context()` silently, then
   answer from the captured visible_text / focused_element.value. Only if
   `current_context` comes back empty should you ask for a paste.

2. **First personal-context turn of a conversation.** When the user's very first
   substantive message references themselves, their work, their people, their
   schedule, or their screen — ALWAYS call `list_memories` OR `current_context`
   before answering. This is how you find out what's even available.

3. **"Right now / just now / currently / 现在 / 刚才" questions.** Any present-
   tense question about the user's current state — *"what am I doing?" / "what's
   on my screen?" / "我在看什么？" / "summarize the doc I have open"* — ALWAYS
   call `current_context` first. Don't guess from chat history.

4. **Temporal references to past activity.** *"yesterday", "last week", "earlier
   today", "this morning", "上周", "刚才"* — ALWAYS call `recent_activity` or
   `search` with a time bound before answering.

5. **Keyword the user typed or read.** Error messages, proper nouns they haven't
   introduced, file paths, URLs, code symbols — ALWAYS try `search_captures`
   (raw screen) in parallel with `search` (compressed) before saying you don't
   know.

6. **Before "I don't know" / "I don't have context" / "could you share…".** You
   are NEVER allowed to plead missing context about the user's work, screen, or
   history without first calling at least `current_context` OR `list_memories`
   + one of `search` / `recent_activity`. Asking the user to paste something
   they already have on screen is a tool-selection failure, not a legitimate
   clarification. If after calling the tools it's genuinely not there, only
   then ask.

7. **Before a clarifying question about personal state.** Before asking *"which
   project do you mean?" / "when is your meeting?" / "which file?"* — ALWAYS
   call a tool first. The answer is frequently in memory or on their screen;
   asking is worse UX than a quiet lookup.

8. **Before generating ANY code, config, or shell command for the user.**
   *"write me a function", "give me a snippet", "how do I implement X", "show
   me an example", "refactor this", "translate this to Python"* — ALWAYS call
   `read_memory("user-preferences.md")` first (it's small and free), and
   additionally `read_memory("user-profile.md")` if you haven't seen it this
   session. Users have strong, specific style preferences — modern type
   syntax vs legacy, `pathlib.Path` vs `os.path`, `uv` vs `pip`, pytest vs
   unittest, docstring conventions, error-handling style, linter choice —
   that you CANNOT guess from the prompt. Skipping this check produces
   generic, textbook-style code that doesn't match how they actually write.
   Your code output quality depends on this lookup.

   ❌ **Failure pattern to avoid:**
   > User: "write me a Python function to find the last N ERROR lines in a log."
   > You (without checking): [generates code with `from typing import List, Optional`, `os.path.exists` checks, verbose docstring]
   > User (silently): "that's not how I write Python at all."

   The first Python / TypeScript / etc. code-gen turn of ANY conversation
   should be preceded by this read. On subsequent turns you can rely on the
   preferences already loaded into your context.

If a rule fires, call the tool. There is no case where "the answer is probably
not in memory" justifies skipping — the tools return `[]` / `null` cheaply if
empty, and that's useful information too.

---

## When to call (extended criteria)

Beyond the hard rules above, also call whenever ANY of the following is true:

### 1. The user refers to something without fully specifying it

Any deictic or anaphoric reference to entities not introduced in the current
conversation is a signal the answer may be in memory. This includes:

- Demonstratives with no clear antecedent: "this", "that", "the thing", "那个",
  "这个项目", "the doc I was reading"
- Definite articles presupposing shared knowledge: "the bug", "the meeting",
  "the refactor", "my editor"
- Possessives referring to durable user state: "my project", "my team", "my setup",
  "my usual approach", "我的项目", "我的偏好"
- Temporal references to prior activity: "yesterday", "last week", "earlier",
  "before the weekend", "上周", "刚才"
- Proper nouns the user hasn't defined in this conversation: names of people,
  projects, companies, tools

### 2. The user is asking about themselves

Any first-person question about facts the user would expect their memory to know.
Examples of the *shape* (not an exhaustive list):

- Schedule and commitments: "when is…", "what's on my…", "do I have…"
- Identity and preferences: "do I prefer…", "what do I usually…", "what's my…"
- Projects and work: "what am I working on", "where did I leave off", "what's the
  state of…"
- People and relationships: "who is…", "what did I say about…", "what did X and I
  discuss"

### 3. Prior context would materially improve your answer

Even when the user doesn't explicitly reference memory, check it whenever knowing
the user's state would change your response. This is the most common case and the
most often missed. Examples:

- User asks a technical question → their skill level, preferred stack, and
  current project context change what a good answer looks like
- User asks for a recommendation → their past choices, stated preferences, and
  constraints matter
- User asks to draft something → their voice, relationships with the recipient,
  and relevant background matter
- User asks for planning help → their schedule, commitments, and ongoing work matter
- User asks an ambiguous question → their recent activity often disambiguates intent

### 4. You're about to say "I don't know" or ask a clarifying question

Before either, check memory. A large fraction of "I don't have that information"
responses and clarification requests are answerable from the user's own memory.

---

## When NOT to call these tools

- Pure general-knowledge questions with no personal angle ("what year was the
  French Revolution", "how does TCP work")
- Tasks entirely self-contained in the current conversation (user pasted code and
  asked to fix a specific bug in it)
- Trivial chit-chat where personal context adds nothing

When in doubt, call. The tools are local and cheap.

---

## Tools

There are TWO distinct layers of memory. Compressed memory (Markdown files) is the
narrative summary; raw captures (the S1 buffer) hold the actual screen content.
**You almost always need to drop into raw captures eventually** — the compressed
summary tells you a meeting happened; the raw capture tells you what was said.

### Compressed memory (Markdown files)

- `list_memories()` — Index of all memory files with one-line descriptions. Cheap
  first hop; usually tells you which file(s) to read next.
- `search(query, paths?, since?, until?)` — BM25 over compressed memory entries.
  Use when you have keywords *that have already been distilled into memory*
  (proper nouns, project names, decisions, preferences). For keywords the user
  typed or read on screen but that may not have made it into memory yet, use
  `search_captures` instead.
- `read_memory(path, tail_n?, since?, until?, tags?)` — Full or filtered contents
  of one Markdown file. Use after `list_memories` / `search` points you at it.
- `recent_activity(since?, limit?, prefix_filter?)` — Newest-first feed across
  all memory files. Use for "what have I been doing" style queries or to
  disambiguate vague references by recency.

### Raw captures (the S1 layer — what was literally on screen)

- `current_context()` — One-shot snapshot of "right now". Returns the last few
  captures + their full visible_text + the most recent timeline blocks. PREFER
  this for any "what am I doing now / 我现在在干嘛 / what's open in front of me"
  question — it's a single call instead of guessing which other tool to use.
- `search_captures(query, since?, until?, app_name?)` — BM25 over the RAW screen
  buffer. Use when the user mentions a keyword they would have typed or seen on
  screen — error messages, code symbols, file paths, URLs, things from a doc
  they were reading. Returns BM25-ranked hits with snippet highlighting.
- `read_recent_capture(at?, app_name?, window_title_substring?)` — Hydrate one
  capture's full content (visible_text, focused element value, optional
  screenshot). Use after a `search_captures` hit, or when an event-daily
  sub_task gives you an `(at, app_name)` pair to drill into.

### Other

- `get_schema()` — Organization rules for memory file naming. Rarely needed.

## Typical flows

- **"What am I doing right now?"** → `current_context()` — one call, done.
- **Known durable fact** ("what's my role", "what does X do") → `list_memories`
  → `read_memory`.
- **Keyword the user mentioned** — first try `search` (compressed memory). If
  nothing useful, follow up with `search_captures` (raw screen).
- **Drill down from compressed → raw.** Compressed event-daily entries carry
  inline breadcrumbs like `[14:30-14:35, Cursor] edited main.py — raw:
  read_recent_capture(at="14:30", app_name="Cursor")`. Whenever you read an
  event-daily entry and the user asks for specifics ("what code did I write",
  "what was in the doc"), call the breadcrumb's `read_recent_capture` directly.
- **Recency-driven** ("what was I just working on") → `recent_activity` (memory
  layer) or `current_context()` (screen layer); pick by whether the user wants
  the *narrative* or the *content*.

A missed lookup is a worse failure mode than an unnecessary one. When the
question even slightly depends on what the user has been doing or seeing, call.
"""


def build_server(cfg: Config | None = None):
    """Construct and return a FastMCP server instance (not yet running)."""
    from mcp.server.fastmcp import FastMCP  # lazy import

    cfg = cfg or load_config()
    server = FastMCP(
        "openchronicle",
        instructions=_SERVER_INSTRUCTIONS,
        host=cfg.mcp.host,
        port=cfg.mcp.port,
    )

    @server.tool()
    def list_memories(include_dormant: bool = False, include_archived: bool = False) -> str:
        """**ALWAYS CALL FIRST** on the first personal-context turn of a conversation.

        List all memory files with descriptions + entry counts. Cheap (one SQLite
        query, no file reads), so the cost of calling is essentially zero.

        Call whenever the user asks about themselves, their schedule, preferences,
        or ongoing work — the response tells you which files exist and what they're
        about (e.g. `event-YYYY-MM-DD.md` for a given day's session-level activity
        log; `user-profile.md` for identity; `user-preferences.md` for habits;
        `project-*.md` / `person-*.md` / `org-*.md` for specific entities).

        If you're about to answer from chat history alone when the user has asked
        about themselves, you've skipped this tool. Go back and call it.
        """
        with fts.cursor() as conn:
            return json.dumps(
                _list_memories(conn, include_dormant=include_dormant, include_archived=include_archived),
                ensure_ascii=False,
            )

    @server.tool()
    def read_memory(
        path: str,
        since: str | None = None,
        until: str | None = None,
        tags: list[str] | None = None,
        tail_n: int | None = None,
    ) -> str:
        """Read the full contents of ONE memory file the user has on disk.

        Use after `list_memories` / `search` points you at a promising file.
        Entries come back chronological. Supports `since` / `until` (ISO timestamps),
        `tags` (filter by any matching tag), and `tail_n` (most recent N entries only).
        """
        with fts.cursor() as conn:
            return json.dumps(
                _read_memory(conn, path=path, since=since, until=until, tags=tags, tail_n=tail_n),
                ensure_ascii=False,
            )

    default_top_k = cfg.search.default_top_k

    @server.tool()
    def search(
        query: str,
        paths: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        top_k: int = default_top_k,
        include_superseded: bool = False,
    ) -> str:
        """**ALWAYS CALL** before saying "I don't know" about something with a keyword in it.

        BM25 full-text search across every entry in COMPRESSED memory files.
        This searches the distilled Markdown layer — what the user has decided
        is durable knowledge (preferences, decisions, schedules, project state,
        people, summaries). It does NOT search raw screen content; for keywords
        the user merely typed or read on screen (error messages, code symbols,
        file paths from a doc), use `search_captures` instead, OR call both in
        parallel.

        Returns the top-k matching entries with file path + timestamp.

        Examples:
          search(query="interview")         — find scheduled interviews in memory
          search(query="Alice Q3 roadmap")  — find mentions of that conversation
          search(query="deadline Friday")   — find time-bounded commitments

        `paths` takes GLOB patterns to scope search, e.g. `['event-*.md']` for
        scheduled events only, or `['project-*.md']` for project notes.
        """
        with fts.cursor() as conn:
            return json.dumps(
                _search(
                    conn, query=query, paths=paths, since=since, until=until,
                    top_k=top_k, include_superseded=include_superseded,
                ),
                ensure_ascii=False,
            )

    @server.tool()
    def recent_activity(
        since: str | None = None,
        limit: int = 20,
        prefix_filter: list[str] | None = None,
    ) -> str:
        """**ALWAYS CALL** when the user references "yesterday / last week / earlier / 刚才 / 上周" etc.

        Newest-first cross-file feed of recent memory entries. Best tool for
        open-ended "what's new / what has the user been up to" questions:

          "what happened today?" / "今天做了啥？"
          "what was I doing yesterday afternoon?"
          "anything recent about <topic>?"
          "catch me up on this week"

        Use `since` (ISO timestamp) to limit to entries newer than a point in
        time, and `prefix_filter` (e.g. `['event-', 'project-']`) to scope.
        Without filters, returns the most recent N entries across ALL files.

        If the user's question has any temporal recency dimension, this tool
        runs in constant time and is strictly better than guessing.
        """
        with fts.cursor() as conn:
            return json.dumps(
                _recent_activity(conn, since=since, limit=limit, prefix_filter=prefix_filter),
                ensure_ascii=False,
            )

    @server.tool()
    def read_recent_capture(
        at: str | None = None,
        app_name: str | None = None,
        window_title_substring: str | None = None,
        include_screenshot: bool = False,
        max_age_minutes: int = 15,
    ) -> str:
        """Hydrate ONE raw screen capture — the actual visible_text, focused
        input value, URL, and (optionally) screenshot from the buffer.

        Use this whenever a compressed memory entry isn't specific enough
        (e.g. an event-daily entry says "edited main.py at 14:30" but you
        need the actual code, or "read article" but you need the text).
        Most event-daily sub_tasks include an inline `raw:
        read_recent_capture(at=..., app_name=...)` breadcrumb — call it
        verbatim. For keyword-driven searches across the whole buffer, prefer
        `search_captures` first; this tool fetches one specific moment.

        Arguments:
          at                      — ISO timestamp ("2026-04-22T14:30") or bare
                                    "HH:MM[:SS]" (today local). Omit for the
                                    newest matching capture.
          app_name                — case-insensitive substring of the app name
                                    (e.g. "Cursor", "Claude", "Chrome").
          window_title_substring  — case-insensitive substring of the window
                                    title (e.g. a filename, tab title).
          include_screenshot      — include the base64 JPEG. Default false —
                                    screenshots are large and rarely needed.
          max_age_minutes         — when `at` is given, only return captures
                                    within this many minutes of `at`. Default 15.

        Returns the matching capture as JSON with `timestamp`, `app_name`,
        `window_title`, `url`, `focused_element.value` (what the user was
        typing), and `visible_text` (~10 k chars of rendered AX text). The buffer
        retention is bounded (see `[capture]` in config); older captures have
        their `screenshot` field stripped but keep text. Returns `null` if
        nothing matches.

        Typical flow: read an event-daily entry, notice `[HH:MM-HH:MM, <app>]`,
        then call this with `at="HH:MM"` and `app_name="<app>"` to see the
        actual content from that moment.
        """
        result = captures_mod.read_recent_capture(
            at=at,
            app_name=app_name,
            window_title_substring=window_title_substring,
            include_screenshot=include_screenshot,
            max_age_minutes=max_age_minutes,
        )
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def search_captures(
        query: str,
        since: str | None = None,
        until: str | None = None,
        app_name: str | None = None,
        limit: int = 10,
    ) -> str:
        """**ALWAYS CALL** (usually in parallel with `search`) when the user mentions a keyword they'd have typed or read on screen.

        Keyword search over RAW screen captures (the uncompressed S1 layer).
        PREFER this over `search` when the user mentions a keyword they would
        have *typed* or *read on screen* but that may not have made it into a
        compressed memory entry yet — e.g. "find when I saw the term
        'rate limiter'", "what was that error about pyobjc", "the URL I had
        open about Postgres replication". `search` only sees compressed memory;
        this sees every captured screen. When you're not sure which layer has
        it, call both — they're independent indexes and neither is expensive.

        Returns the top-`limit` matching captures (BM25-ranked) with snippet
        highlighting (matched tokens wrapped in `[...]`). Each hit includes
        `file_stem` — pass that as `at` to `read_recent_capture` to get the
        full visible_text.

        Examples:
          search_captures(query="rate limiter")             — find any time it appeared
          search_captures(query="error", app_name="Cursor") — keyword scoped to one app
          search_captures(query="todo", since="2026-04-22T09:00:00+08:00")

        Arguments:
          query     — free-text keywords. FTS5-tokenized (case-insensitive).
          since     — ISO timestamp lower bound on capture time.
          until     — ISO timestamp upper bound on capture time.
          app_name  — case-insensitive substring on the capturing app name.
          limit     — top-K BM25 hits to return.
        """
        results = captures_mod.search_captures(
            query=query, since=since, until=until,
            app_name=app_name, limit=limit,
        )
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)

    @server.tool()
    def current_context(
        app_filter: str | None = None,
        headline_limit: int = 5,
        fulltext_limit: int = 3,
        timeline_limit: int = 8,
    ) -> str:
        """**ALWAYS CALL** for present-tense or ambiguous-pronoun questions about the user's state.

        Two high-value trigger patterns:
          1. Present-tense: *"right now / currently / just now / what am I /
             what's open / 现在 / 刚才 / 我在"* — this is the tool.
          2. Pronoun with no in-conversation antecedent: *"that / this / it /
             the bug / the error / the file / 那个 / 这个 / 这段 / 这个问题"* —
             the user is pointing at their screen, not at chat history.

        Never reply with "I don't have code/context to look at" or ask the user
        to paste something — call this tool first. If it comes back empty,
        then ask. Asking for a paste when this tool would have worked is a
        tool-selection failure.

        Returns a one-shot snapshot of the current screen state — the same kind of
        context you would get if every chat turn began with the user narrating
        their environment. Triggers include:

          - "what am I working on?" / "我在干嘛？"
          - "what's open in front of me?"
          - "is the deploy log still streaming?"
          - "summarize the doc I'm reading"

        Returns three sections:

          recent_captures_headline    : last ~5 captures as compact lines
                                        ([HH:MM] App — Window [Role]) — quick
                                        scan of "what apps + windows are live".
          recent_captures_fulltext    : top ~3 captures deduplicated by
                                        (app, window) carrying the FULL
                                        visible_text and focused_element.value
                                        — the actual content on screen.
          recent_timeline_blocks      : the last ~8 1-minute timeline blocks
                                        (LLM-summarized activity slices) so
                                        you can see how the current moment
                                        was reached.

        For drill-down on any specific capture or moment, call
        `read_recent_capture(at=..., app_name=...)` next.
        """
        result = captures_mod.current_context(
            app_filter=app_filter,
            headline_limit=headline_limit,
            fulltext_limit=fulltext_limit,
            timeline_limit=timeline_limit,
        )
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def get_schema() -> str:
        """Return the memory organization spec (file naming, what each prefix means).

        Rarely needed at query time. Useful only if you need to reason about WHERE
        a new fact would be stored, or explain to the user how their memory is
        organized. For normal "look up a fact" flows, use `search` / `list_memories`
        directly.
        """
        return json.dumps(_get_schema(), ensure_ascii=False)

    return server


def run_stdio() -> None:
    """Run the server on stdio. Blocks until the client disconnects."""
    server = build_server()
    server.run()  # FastMCP.run() uses stdio by default


async def run_async(cfg: Config | None = None, *, transport: str | None = None) -> None:
    """Run the MCP server with the configured transport (for use inside the daemon)."""
    cfg = cfg or load_config()
    transport = transport or cfg.mcp.transport
    server = build_server(cfg)
    if transport == "stdio":
        await server.run_stdio_async()
    elif transport == "sse":
        logger.info("MCP SSE server: http://%s:%d/sse", cfg.mcp.host, cfg.mcp.port)
        await server.run_sse_async()
    elif transport == "streamable-http":
        logger.info("MCP HTTP server: http://%s:%d/mcp", cfg.mcp.host, cfg.mcp.port)
        await server.run_streamable_http_async()
    else:
        raise ValueError(f"unknown MCP transport: {transport!r}")


def endpoint_url(cfg: Config) -> str:
    """Return the public URL where the daemon-hosted MCP server is reachable."""
    transport = cfg.mcp.transport
    if transport == "sse":
        return f"http://{cfg.mcp.host}:{cfg.mcp.port}/sse"
    if transport == "streamable-http":
        return f"http://{cfg.mcp.host}:{cfg.mcp.port}/mcp"
    raise ValueError(f"endpoint_url only supported for sse/http, got {transport!r}")
