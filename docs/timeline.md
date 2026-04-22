# Timeline

The timeline is the mandatory **verbatim-preserving normalizer** between raw captures and the S2 reducer. Always-on — there is no toggle.

- Raw AX trees run 200–400 KB for Electron apps. Passing a session's raw captures directly to the reducer would blow out the prompt budget.
- But downstream stages depend on knowing *what the user actually typed* — a TODO, a message draft, a search query, a URL, a window title. The timeline stage is careful NOT to throw that content away; it strips UI chrome and collapses duplicate snapshots while keeping authored text, URLs, titles, and proper nouns verbatim.
- The real compression happens one stage later in the session reducer, which consumes a batch of timeline blocks per flush.

## Wall-clock alignment

Windows are aligned to the real clock: with the default `window_minutes = 1`, that's `[10:00, 10:01)`, `[10:01, 10:02)`, …, **not** rolling from an arbitrary start moment. This means:

- Concurrent daemons, restarts, or clock skew don't produce overlapping blocks.
- Blocks have a natural UNIQUE key `(start_time, end_time)` → production is idempotent.
- A human looking at the timeline can reason about "the 10:15 block" without mental arithmetic.

Change `window_minutes` in `[timeline]` and the change takes effect for **future** windows only — existing blocks keep their original boundaries.

Why 1-minute blocks? Two reasons:

1. The timeline prompt is now a verbatim-preserving normalizer, not a summarizer. Short windows carry few captures each, so each authored text snippet can round-trip through the prompt without being dropped or paraphrased.
2. The reducer's flush tick already does 5-min-scale work every `session.flush_minutes`, so there's no need for the timeline itself to be 5 min wide. A 5-min flush now consumes ~5 timeline blocks.

## Production cadence

`timeline/tick.py::run_forever` fires every 60s inside the daemon. Each tick:

1. Loads `get_latest_end()` from `timeline_blocks`.
2. Iterates closed windows from that boundary (or `cold_lookback_minutes` ago on first run) up to *now minus one window*.
3. For each window without an existing block, calls `produce_block_for_window`.
4. After the scan, cleans buffer files older than the newest block's `end_time` AND older than `capture.buffer_retention_hours` — captures covered by a closed block are safe to drop.

Only closed windows are produced. The current half-formed window sits as "trailing captures" in the buffer until it closes.

## The aggregator LLM call

`timeline/aggregator.py` reads each capture's S1 fields (`focused_element`, `visible_text`, `url`, `window_meta`) — **not** the raw AX tree. This keeps the prompt tractable:

- `visible_text` is a pre-rendered, length-capped markdown view of the AX tree (capped at 10 KB per capture by S1, then capped at 4 KB per capture by the timeline prompt).
- `focused_element` carries the user's current cursor / input context (role, title, value, editable flag). When `is_editable=true` and `value_length > 0`, the value is the user's own typed content — the prompt treats this as the highest-priority signal to preserve verbatim.
- `url` is regex-extracted from visible text when present.

Up to `_MAX_EVENTS_PER_WINDOW = 30` events per window (rarely hit at 1-min granularity). The prompt (`prompts/timeline_block.md`) commands the model to emit a JSON array of normalized activity records, one per distinct conversation / context / tab / file. Each record follows this shape:

```
[<app name>] <context (title/URL/file)>: <what happened>. <Authored text verbatim, in quotes, if any>. Involving: <people/topics/files named in this conversation>.
```

Examples:

```
[Notes] Shopping list: user drafted a list, latest version "milk, eggs, flour, butter".
[Google Chrome] ACME Q3 roadmap (https://docs.example/roadmap): read the document; noted priorities with Owner Alice and Deadline Oct 14. Involving: Alice, ACME Q3 roadmap.
[Cursor] openchronicle/timeline/aggregator.py: editing the _stem_to_dt parser. Involving: openchronicle/timeline/aggregator.py, _stem_to_dt.
```

Explicit rules (see the prompt for the full list):

- **Verbatim preservation.** Authored text from editable inputs must be carried into the entry in quotes, not paraphrased. URLs, window titles, file paths, and proper nouns must be verbatim.
- **Anti-hallucination.** Topics and people seen in one conversation must not be cross-attributed to another conversation in the same app (multiple tabs, multiple chats).
- **Authorship guard.** Typing into a search box / address bar is not chat participation.
- **De-duplication.** Collapse consecutive identical passive reads; keep the longest version of an in-progress draft.

On any failure (JSON parse, LLM timeout, empty), the code falls back to a heuristic entry built from `window_meta.app_name` counts. Never silently drops a window.

## Schema

```sql
CREATE TABLE timeline_blocks (
  id TEXT PRIMARY KEY,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT '',
  entries TEXT NOT NULL,         -- JSON array of strings (one record per conversation/context)
  apps_used TEXT NOT NULL,       -- JSON array of app names
  capture_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(start_time, end_time)
);
```

Stored in the same `index.db` as the FTS tables. Not FTS-indexed — the reducer queries them directly by time range for each session / flush.

## CLI

```bash
openchronicle timeline tick         # synchronous: build all closed windows now
openchronicle timeline list -n 24   # last 24 blocks, oldest → newest
```

Production is idempotent — manual ticks are always safe.

## Interaction with the S2 reducer

Both the flush tick and the terminal reduce query:

```sql
SELECT * FROM timeline_blocks
 WHERE end_time > :start_bound AND start_time < :end_bound
 ORDER BY start_time ASC
```

Where `:start_bound` is `flush_end` (or `session.start` on the first flush) and `:end_bound` is `now` (flush) or `session.end` (terminal). All overlapping blocks are fed to the reducer LLM along with the window's wall-clock range. The reducer emits per-window-range sub_tasks like `[13:25-13:30, Cursor] edited tick.py; "fixed _stem_to_dt for negative offsets"; involving openchronicle/timeline/aggregator.py`.

## Tuning

- Timeline runs every 60s even with no captures; the LLM call is skipped when the window has zero events.
- If your `timeline` model is slow (>30s per call), that's your bottleneck — consider a faster model for this stage. Since the prompt is now bigger (1-min window but more verbatim content), a mid-tier model may be worth it; a too-weak model will start summarizing instead of normalizing.
- `window_minutes` can be tuned but changing it doesn't migrate existing blocks. A larger window cuts LLM calls per hour but risks the model over-summarizing a crowded window; a smaller window costs more calls but keeps fidelity high.
- Drop all timeline data with `openchronicle clean timeline`. The aggregator will re-produce blocks from whatever captures are still in the buffer on the next tick.
