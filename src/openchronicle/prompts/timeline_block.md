You are normalizing a short slice of one user's screen activity into a cleaner, de-duplicated record.

**Your job is normalization, NOT summarization.** This stage exists to strip UI chrome, collapse duplicate snapshots, and separate independent conversations — NOT to compress content. Authored text, URLs, window titles, file paths, and quoted evidence MUST appear verbatim in your output. Downstream stages rely on this fidelity.

Window: {start_time} to {end_time} ({capture_count} screen-content snapshots from the macOS Accessibility API). Records are ordered chronologically — earlier first. The format of each event: `N. [HH:MM:SS] <App> — <window title> (<bundle>) (URL: ...) [<role>] (editing) title=... len=N: <verbatim value>`, optionally followed by a `| <visible_text>` line. Entries where the user was composing show `(editing)` and a `: <value>` suffix — the quoted value is the user's own typed content.

---
{events_text}
---

## Anti-hallucination rule — the most important rule in this prompt.

A single window often contains several *independent* interactions even inside a single app — a chat app can show three unrelated conversations (a group chat, a 1:1, a channel); a browser can show three unrelated tabs; an editor can show three unrelated files. Each of these is its own "conversation". People, topics, files, URLs, and quoted content you see inside one conversation MUST NEVER be attributed to a different conversation — not even when they share the same app.

Concretely, NEVER take the set of topics seen in the window and the set of people seen in the window and cross-multiply them into a single "discussed X, Y, Z with A, B, C" line. If A only ever appeared in the conversation about X, NEVER write a line that associates A with Y or Z.

## Authorship guard (chat apps).

In chat / IM apps, treat typing in the message composer as participation (focused editable input counts). However, if the focused editable input is clearly a search box / address bar, do NOT describe it as chat participation — describe it as searching or navigating instead. Use the input title as a hint (case-insensitive): if it contains keywords like "search", "find", "url", "address", "omnibox", or "command", treat it as search/navigation. If the input title is missing, you may still describe it as "typing in an input field", but do NOT claim it was a chat reply or message unless the UI clearly indicates that.

## What to preserve verbatim

1. **Authored text.** Any `(editing)` snapshot with a `: <value>` suffix is something the user typed. Include the full value in quotes. Do NOT paraphrase. Do NOT replace it with a generic verb like "typed a note". If the same draft appears in multiple consecutive snapshots (the user is still typing), keep the longest / most recent version once — that's the only deduplication allowed for authored content. Truncate only if a single value exceeds ~1500 characters, and say `…(truncated)` if you do.
2. **URLs**, window titles, file names, file paths — verbatim.
3. **Proper nouns** (people names, project names, channel names, organization names) — verbatim.
4. **Quoted evidence.** When you describe what the user read, quote a short (≤200-char) excerpt of the actual visible text if it carries specific meaning. Don't fabricate excerpts.

## What to normalize away

- Duplicate passive-read snapshots of the same content (same app + same window title + roughly the same visible_text). Collapse into a single entry and note the span, e.g. "read this article for the full window".
- UI chrome noise: toolbar button labels, empty scaffolding, nav rail contents that don't change, boilerplate frames.
- Repeated identical `focused_element` snapshots where nothing changed between them.

## Output

Return a JSON object with exactly one field:

- `entries`: an ordered array of activity records. One record per distinct conversation / context / tab / file. Do not collapse independent conversations. Do not add a time prefix; the window's time range is already known to the caller.

Each record uses this exact shape:

```
[<app name>] <context description — window title, file, or conversation name>: <what happened>. <Authored text verbatim, in quotes, if any>. Involving: <people/topics/files named in THIS conversation only>.
```

- An entry can be multi-sentence when verbatim content is long. Do NOT force it into a single line.
- `Involving:` names must come from the same conversation as the rest of the entry (see anti-hallucination rule). Use `Involving: —` if there is nothing notable.
- Omit parts of the template that genuinely have no signal (e.g. drop `Involving:` entirely if you'd just write `—`, but keep `:` before "what happened").

### Example

Source snapshots (illustrative):
```
1. [14:02:10] Notes — Shopping list (editing): "milk, eggs, flour"
2. [14:02:40] Notes — Shopping list (editing) len=24: "milk, eggs, flour, butter"
3. [14:03:05] Google Chrome — ACME Q3 roadmap (URL: https://docs.example/roadmap)
   | Q3 roadmap · Priorities · Owner: Alice · Deadline: Oct 14
4. [14:03:20] Google Chrome — ACME Q3 roadmap (URL: https://docs.example/roadmap)
   | Q3 roadmap · Priorities · Owner: Alice · Deadline: Oct 14
```

Good output:

```json
{{
  "entries": [
    "[Notes] Shopping list: user drafted a list, latest version \"milk, eggs, flour, butter\".",
    "[Google Chrome] ACME Q3 roadmap (https://docs.example/roadmap): read the document; noted priorities with Owner Alice and Deadline Oct 14. Involving: Alice, ACME Q3 roadmap."
  ]
}}
```

Bad output (do NOT do this):

```json
{{
  "entries": [
    "[Notes] typed a shopping list, involving —",
    "[Google Chrome] read an article, involving ACME"
  ]
}}
```

The bad version threw away the verbatim list content ("milk, eggs, flour, butter"), the URL, and the specific owner / deadline that were visible on the page. Those facts are exactly what downstream reducers need to preserve.

Output only the JSON object, no markdown fences and no surrounding prose.
