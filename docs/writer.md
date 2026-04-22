# Writer

The writer is two LLM stages wired behind session boundaries:

1. **S2 reducer** (`writer/session_reducer.py`) — writes incremental `[flush]` entries during an active session and a final entry when it closes, both to `event-YYYY-MM-DD.md`.
2. **Classifier** (`writer/classifier.py`) — runs on a timer during the active session, then one last trailing-window pass at the terminal reduce. Scans the newly-appended event-daily entries for durable facts and persists them to `user-/project-/tool-/topic-/person-/org-*.md` via a tool-call loop.

Both the reducer and the classifier are periodic during long sessions. The reducer flushes every `session.flush_minutes` so event-daily surfaces activity in near-real-time; the classifier fires every `classifier.interval_minutes` (default 30, min 5) so durable facts are extracted in the same long-running session without waiting for it to end. Each stage tracks its own progress on the sessions row (`flush_end` for the reducer, `classified_end` for the classifier), so every entry is processed exactly once. Session boundaries come from `session/manager.py` (see [session.md](session.md)). No capture-level triage, no global writer loop.

## Triggers

| Trigger | What fires |
|---|---|
| Flush tick (every `session.flush_minutes`, min 5) | `flush_active_session` runs the reducer with `is_final=False` over new closed blocks since `flush_end`. Appends a `[flush]`-tagged entry to today's event-daily. The classifier does **not** fire. |
| Classifier tick (every `classifier.interval_minutes`, min 5) | For the currently-active session, classifies entries appended since `classified_end` (fallback: `session_start`). On a committed pass advances `classified_end`. Silent no-op when no new entries landed since last tick. |
| `SessionManager.on_session_end` callback | `reduce_session_async` spawns a daemon thread with `is_final=True`, covering whatever wasn't flushed yet. On success, its `on_done` callback invokes the classifier over the trailing window `[classified_end, now)` — whatever the 30-min tick hadn't reached yet. |
| Daily 23:55 safety-net cron | `reduce_all_pending` picks up any `ended`/`failed` session rows whose async work didn't finish (e.g. daemon crashed mid-reduce). Also force-ends the currently-open session so day boundaries are clean. |
| `openchronicle writer run` (CLI) | Same as the safety net — useful manually after pulling new code or for recovery. |

## Stage 1 — S2 reducer

For each session that ended, `reduce_session`:

1. Reads `timeline_blocks` in `[flush_end or session.start, session.end)` from SQLite. (For the terminal reduce, `session.end` is set; for a flush tick, the tick uses `now` as the upper bound and the session stays `active`.)
2. If the range is empty, marks the session `reduced` (no-op, terminal only) and returns.
3. Renders the blocks into `prompts/session_reduce.md` and calls the `reducer` LLM stage with `json_mode=True`.
4. Parses `{summary: str, sub_tasks: [str]}`. Each sub_task must look like `[HH:MM-HH:MM, <app>] <action>, involving <...>`.
5. Appends one entry to `event-YYYY-MM-DD.md` (the date of `session.start`). Entry header: `**Session <sid>** (HH:MM–HH:MM)` for terminal reduces, or `**Session <sid> [flush]** (HH:MM–HH:MM)` for flush passes. Flush entries carry a `flush` tag alongside `sid:<sid>` so they're easy to filter later.
6. Advances `flush_end` on the session row. For the terminal reduce, also sets `status=reduced`.

### Retry + heuristic fallback

If the LLM call fails or returns unparseable JSON:

- **Retry queue.** Backoff schedule `5 / 15 / 30 / 60 / 120` minutes (verbatim from Einsia). The session row moves to `status=failed` with `next_retry_at` set; the daily safety-net picks it up. (Flush failures don't schedule retries — the next flush covers a bigger window, and the terminal reduce is authoritative.)
- **Exhausted retries.** A heuristic entry is written (one sub_task per distinct app, tagged `heuristic`), and the row is marked `reduced`. A session is never silently lost.

### Event-daily file ownership

Event-daily files are owned by the reducer. The classifier is **forbidden** from writing to any `event-*.md` path — there's a hard guard in the classifier's tool loop that rejects such calls with an explicit error.

## Stage 2 — Classifier

Two entry points, same core (`classifier.classify_window`):

- **Tick path** — `session/tick.run_classifier_tick` fires every `classifier.interval_minutes` (default 30). For the currently-active session, it classifies the window `[classified_end or session_start, now)` and, on a committed pass, advances `classified_end` so the next tick picks up where it left off.
- **Terminal path** — the reducer's `on_done` callback classifies the trailing window `[classified_end or session_start, now)` right after the final reduce lands. This covers whatever the tick didn't reach (sessions shorter than one interval, or the tail between the last tick and the session close).

Both paths assemble the same prompt inputs:

1. The event-daily entries tagged `sid:<session_id>` whose timestamps fall in the window — these are the focus entries.
2. The timeline blocks covering the window — verbatim-preserving activity slices so the classifier can ground any durable fact against raw evidence.
3. The preceding-day's trailing entries as dedup context (terminal path only — the tick runs inside the day so it doesn't need cross-day context).
4. The memory-file index filtered to exclude `event-*` files.

Both paths then run a bounded tool-call loop over `writer/tools.py`:

| Tool | Purpose |
|---|---|
| `read_memory(path, tail_n?)` | Fetch a memory file's frontmatter + last N entries (default 10). |
| `search_memory(query, top_k?, include_superseded?)` | BM25 search — dedup check before appending. |
| `append(path, content, tags)` | Add a new entry to an existing file. |
| `create(path, description, tags)` | Make a new (empty) memory file. A first entry must be added via `append` in the same round. |
| `supersede(path, old_entry_id, new_content, reason, tags?)` | Replace an old entry. |
| `flag_compact(path, reason)` | Mark a file for compaction (run after commit). |
| `commit(summary)` | End the round. Always called exactly once. |

Iteration cap: `writer.max_tool_iterations = 12`.

The prompt is biased toward **doing nothing**: default action is an empty `commit` if no durable signal is present. Raw activity ("used Cursor for 2h", "played Slay the Spire") is explicitly *not* classifiable — that's already captured in the event-daily entry.

## Stage 3 — Compact

Unchanged from v1. After a classifier commit, any file flagged for compaction (by `flag_compact` or by exceeding `soft_limit_tokens`) runs through `writer/compact.py`: LLM rewrite + fact-preservation check (rejects if >5% noun-phrase loss). Separate module so a bad compact can't take the classifier down with it.

## Sessions table

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,             -- sess_<12hex>
  start_time TEXT NOT NULL,
  end_time TEXT,
  status TEXT NOT NULL,            -- active | ended | reduced | failed
  flush_end TEXT,                  -- reducer bookmark: upper bound of last reduced window
  classified_end TEXT,             -- classifier bookmark: upper bound of last classifier pass
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  last_error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Lives in `index.db` alongside `entries` / `files` / `timeline_blocks`. The reducer uses it to bookkeep retries; the safety-net cron uses `status IN ('ended','failed')` to find anything still owed work.

## Per-stage model picks

Defaults inherit from `[models.default]`. Override in `config.toml`:

- **`[models.reducer]`** — prompt is short (timeline blocks are already compressed), but output precision matters (time ranges, per-app attribution). A mid-tier model is usually the right trade-off.
- **`[models.classifier]`** — accuracy-sensitive. The classifier decides what becomes long-term memory; a weak model here means either missed facts or poisoned dedup.
- **`[models.timeline]`** — runs every minute of activity as a verbatim-preserving normalizer. Keep it cheap, but don't go too weak — a too-weak model will summarize instead of normalizing and drop authored text.
- **`[models.compact]`** — runs only when files fatten. Match reducer or stronger.

## Logs

```
~/.openchronicle/logs/writer.log    # reducer + classifier tool-call loops, commit summaries
~/.openchronicle/logs/session.log   # flush tick + classifier tick + terminal reduce callback lines
~/.openchronicle/logs/compact.log   # compact rounds + preservation ratios
```

A flush (every 5 min) produces one reducer line in writer.log + a "flushed" line in session.log. A classifier tick (every 30 min) produces either a "skipped (no session entries in window)" line in session.log, or a write-summary + tool-call trail in writer.log. At session-end you'll see the terminal reducer followed by the terminal classifier callback in session.log; the classifier's own tool calls land in writer.log.
