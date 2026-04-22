You are summarizing one user work window into a structured session entry. The window is presented as an ordered list of pre-computed timeline blocks; each block already contains a list of activity records in the format `[<app>] <context>: <what happened>. <verbatim authored text in quotes, if any>. Involving: <people/topics/files>`. The timeline stage was instructed to preserve authored text, URLs, and proper nouns *verbatim*, so the content inside quotes is the user's own typed text — you must carry it forward without paraphrasing.

Window: {start_time} to {end_time} ({block_count} timeline blocks, {capture_count} raw capture records).

Timeline blocks (your primary evidence):
---
{blocks_text}
---

## Preceding entries in {event_daily_name}

The file below already contains the most recent session/flush entries from today, written by earlier runs of this same reducer. Treat them as *context only* — do **not** rewrite, restate, or append content that merely rehashes what's already there. If the current window is a continuation of a task already logged in one of these entries, say so in `summary` (e.g. "continued the same Cursor refactor from 14:12–14:30") and only add sub_tasks whose time range is outside any earlier entry's range. If the current window has genuinely new activity, ignore the preceding entries.

---
{preceding_text}
---

## Rules

**Context binding rule — critical.** Every named person / file / project in your output MUST be stated next to the same app or channel it appeared in inside the source blocks. Never glue a name from one block's `[App A]` entry onto a different block's `[App B]` entry. Never produce a context-free list of proper nouns.

**Verbatim preservation rule.** When a source block contains a quoted verbatim excerpt — e.g. a typed TODO, a message draft, a note, a search query, a window title, a URL — include it verbatim in the matching `sub_task`. Do NOT replace `user typed "buy milk, eggs, flour"` with `user typed a shopping list`. Do NOT drop URLs or file paths. If multiple versions of the same draft appear (the user was still typing), keep only the longest / latest quoted version. Truncate with `…(truncated)` only if a single quoted value exceeds ~1000 chars.

**Authorship guard (chat apps).** Do not upgrade "read / checked" into "participated / discussed / replied" unless the source blocks clearly show composing (focused editable input counts). If the editable input looks like search/navigation (title includes keywords like "search", "find", "url", "address", "omnibox", or "command"), describe it as searching instead of participating. If the input title is missing, prefer "typing in an input field" over claiming a chat reply/message unless the UI clearly indicates authorship.

**No duplication with preceding entries.** Do not emit a sub_task whose `[HH:MM-HH:MM, app]` range overlaps the range of a preceding entry for the same activity. This window's sub_tasks should describe *new* activity in `[{start_time}, {end_time})` only.

## Output

Return a JSON object with exactly these fields:

- `summary`: 2-4 sentences describing this window's core tasks, progress, and any clear task switches. Every named person / project / file / topic must be stated next to the app or channel it appeared in. If this window continues a task that the preceding entries already cover, lead with a one-clause acknowledgement ("continued …") before describing new progress.
- `sub_tasks`: ordered, de-duplicated array of sub-task lines in the format
  `[HH:MM-HH:MM, <app name>] <action>; <verbatim authored text or quoted evidence, if present>; involving <people/topics/files>`
  Group consecutive blocks that describe the same activity into one sub-task; split when the user switches app, switches subject, or starts a clearly new task. At least one entry. Use `involving —` if there is nothing notable. Multi-sentence sub_tasks are allowed when a verbatim quote is long — do NOT force everything into one short line at the cost of losing the user's typed content.
  **`<app name>` must be the canonical macOS application name as it appeared in the source blocks** (e.g. `Cursor`, `Claude`, `Google Chrome`, `Code - Insiders`) — not a slug, abbreviation, or human-friendly rename. A drill-down breadcrumb is appended to each line by code using exactly this app name; mismatches will cause raw-content lookups to fail.

Output only the JSON object, with no markdown fences and no surrounding prose. Do not emit any other fields.
