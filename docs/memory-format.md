# Memory Format

Memory files are plain Markdown under `~/.openchronicle/memory/`. Three rules:

1. One file per entity. Filename encodes the entity type and name.
2. Each file is YAML frontmatter + a list of append-only entries.
3. When information changes, the *old entry* is struck through in place; new content is appended.

A human can read, grep, diff, and hand-edit these files. The SQLite FTS index (`index.db`) is a derived mirror — rebuild it from the files any time with `openchronicle rebuild-index`.

## File prefixes

| Prefix | Purpose | Example |
|---|---|---|
| `user-` | Persistent facts about the user themselves | `user-profile.md`, `user-preferences.md` |
| `project-` | A specific project with clear boundaries | `project-openchronicle.md` |
| `tool-` | A software, service, or command-line tool | `tool-cursor.md`, `tool-slack.md` |
| `topic-` | A knowledge domain or ongoing area of attention | `topic-rust-async.md` |
| `person-` | Another person the user interacts with | `person-alice.md` |
| `org-` | A company, team, or institution | `org-anthropic.md` |
| `event-` | Per-day session-level activity log (written by the S2 reducer) | `event-2026-04-22.md` |

`user-profile.md` and `user-preferences.md` are preseeded on first install; everything else is created by the writer on demand. See `prompts/schema.md` for the full decision tree (also available via MCP `get_schema`).

## File layout

```markdown
---
description: Identity and background of the user
tags: [identity, background]
status: active            # active | dormant | archived
created: 2026-04-20T14:02:11+08:00
updated: 2026-04-21T09:15:00+08:00
entry_count: 4
needs_compact: false
---

# User Profile

## [2026-04-20T14:02:11] {id: 20260420-1402-a1b23c} #identity
User goes by Kming. Based in Shanghai.

## [2026-04-20T16:30:05] {id: 20260420-1630-3f0e99} #work #employer
~~User works at Old Corp as a principal engineer.~~ #superseded-by:20260421-0915-c4f1a5

## [2026-04-21T09:15:00] {id: 20260421-0915-c4f1a5} #work #employer
User joined Acme Corp as a senior engineer.
```

### Frontmatter fields

| Field | Written by | Meaning |
|---|---|---|
| `description` | create | One-line summary shown in `list_memories`. |
| `tags` | create / append | File-level topical tags (not entry tags). |
| `status` | index_md | `active` / `dormant` (untouched > `auto_dormant_days`) / `archived` (manual). |
| `created` | create | ISO-8601 with TZ. |
| `updated` | any write | Refreshed on every entry. |
| `entry_count` | any write | Cached count; kept in sync by store. |
| `needs_compact` | flag_compact / writer | Signals the compact stage on the next round. |

Hand-editing frontmatter is allowed; run `rebuild-index` afterward to sync the FTS tables.

### Entry heading

```
## [{iso-timestamp}] {id: YYYYMMDD-HHMM-xxxx} #tag1 #tag2
```

- **Timestamp.** ISO-8601 in the user's local timezone. Seconds precision.
- **Id.** `YYYYMMDD-HHMM` + 6 hex chars from `blake2s(os.urandom(8), digest_size=3)`. Collision probability <0.1% even under heavy batched writes within the same minute.
- **Tags.** 1–3 per entry, hashtag-style. Indexed for `read_memory(tags=...)` and `search`.

### Body

1–3 sentences. Self-contained — a reader should understand the fact without the surrounding entries. See `prompts/schema.md` for tense / subject-clarity rules.

## Supersede semantics

When a fact changes, the writer calls `supersede(path, old_id, new_content, reason)`:

1. Old entry's body is wrapped in `~~...~~`.
2. A trailing `#superseded-by:{new_id}` tag is appended to the old heading.
3. The old entry's FTS row gets `superseded = 1` — hidden from default search.
4. A new entry is appended with the replacement content.

Nothing is deleted. The timeline is intact, and `read_memory` / `search` with `include_superseded=true` surfaces the chain.

## Compaction

When a file's entry count gets large, the writer can flag it with `flag_compact`. The compact stage rewrites the file to preserve the *facts* while reducing tokens — e.g., by merging multiple supersedes into a single "current state" + historical note.

A regex-based fact-preservation check rejects any rewrite that drops >5% of unique noun phrases. Rejected rewrites leave the file flagged for manual review; they never silently lose information.

Trigger knobs live in `[writer]`:

```toml
soft_limit_tokens = 20000    # suggest compaction above this
hard_limit_tokens = 50000    # emergency: always flag
```

## Reading & writing from the outside

**Reading.** Any tool that can read Markdown works. `grep -r user- ~/.openchronicle/memory/` is a valid first pass.

**Writing.** Don't. The FTS index and frontmatter counters will drift. Either:

- Let the writer do it (normal path), or
- Edit the Markdown, then run `uv run openchronicle rebuild-index` to resync.

The rebuild is safe and idempotent — it parses every file and rebuilds the `entries`, `files`, and `entries_fts` tables from scratch.

## Wiping memory

```bash
uv run openchronicle clean memory       # asks to confirm; empties memory/ and the FTS tables
uv run openchronicle clean all          # ...plus captures, timeline blocks, writer state
```

Config (`config.toml`) is never touched by `clean` commands.
