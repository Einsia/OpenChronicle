# Memory Organization Spec

## Core principles
1. **Prefer silence over noise.** The default action each round is "write nothing."
2. Every entry must be **self-contained** — readable without surrounding context.
3. **Preserve timelines.** When new information overrides old, use supersede — do not delete.
4. **No duplication.** If a similar fact was recorded recently, skip.
5. **Route by the nature of the fact, not by what file happens to exist.** Forcing a time-bounded event into a preferences or identity file distorts the fact to fit the bucket. Pick the right home first.

## File prefixes

| Prefix | What it's for | Example files |
|---|---|---|
| `user-` | Durable facts about the user themselves: identity, long-term preferences, habits, tool choices, working style | user-profile.md, user-preferences.md |
| `project-` | A specific project or product with clear boundaries | project-openchronicle.md |
| `tool-` | A software, service, SaaS, or CLI tool | tool-cursor.md, tool-slack.md |
| `topic-` | A knowledge domain or ongoing area of attention | topic-rust-async.md |
| `person-` | Another person the user mentions or interacts with | person-alice.md |
| `org-` | A company, team, or institution | org-anthropic.md |
| `event-` | **Session-level activity log.** One file per day: `event-YYYY-MM-DD.md`. Each entry is a time-ranged sub-task list written by the S2 reducer (the Classifier never writes here). Scheduled events / appointments / interviews belong in the non-event file for whichever entity anchors them (person-/org-/project-) when they represent a durable fact; transient occurrences stay in the event log only. | event-2026-04-22.md |

`event-YYYY-MM-DD.md` is **owned by the S2 reducer, not the classifier.** You never write there. Transient one-off activity ("played Slay the Spire", "had a 1:1 with Alice on Tuesday") is already in that file — do not mirror it into a durable file just because it has a date. Only durable facts with lasting value belong in the non-event files.

## Decision tree

### Step 1: Is this worth writing?
- User is only browsing / reading / scrolling → SKIP
- Behavior is brief and unlikely to persist → SKIP
- A similar entry exists in recent memory → SKIP
- Clear preference change, decision, project progress, new identity info, or durable context about a person/org/tool/topic → WRITE

### Step 2: What *kind* of fact is this?

Ask in this order:

1. **Is it a durable property of the user themselves?** (new job title, relocation, "I prefer X over Y", always uses dark mode…) → `user-profile.md` or `user-preferences.md`.
2. **Is it a durable property of a project/tool/topic/person/org?** (Project X uses DB Y; Tool Z's new v4 API; Alice joined Acme) → the corresponding entity file.
3. **It has a specific date but nothing durable attached** (one-off meeting, routine appointment, a task you finished today) → **SKIP**. The event-daily log already has it.
4. **It has a specific date *and* durable context** (interview at Xiaomi on 2026-04-24 → Xiaomi is an org the user is actively engaging with) → append the *durable* part to `org-xiaomi.md` (that they are in an interview loop there), NOT a restated copy of the time-bounded event.

### Step 3: append / create / supersede?
- Target file exists + new info conflicts with existing entry → `supersede`
- Target file exists + new info complements → `append`
- Target file exists + new info is redundant → skip
- Target file does not exist → `create` (description is required)

## What user-preferences.md is and isn't

**Is:** "User prefers Cursor over VSCode." "User works in 90-min focus blocks." "User always writes commit messages in present tense."

**Isn't:** "User asked AI to remind them about an interview" (that's an event, not a preference). "User had a call with Alice on Tuesday" (event). "User is interviewing at Xiaomi on 4/24" (event).

If you find yourself writing "this indicates the user has a preference for X" to justify the file choice, stop — you've picked the wrong file. Skip instead; the raw fact is already in the event-daily log.

## Entry content spec

- **Length**: 1–3 sentences. Complex facts may be longer but avoid paragraphs.
- **Don't rewrite the fact to match the bucket.** Log the concrete event; don't paraphrase it into a generalization.
- **Tense**:
  - Stable facts use simple present: "User prefers X"
  - Events use past / future tense with explicit date: "User has an interview at 20:00 on 2026-04-21"
- **Subject clarity**: Not "this feature is great" → write "User rates Cursor's AI features highly"
- **Tags**: 1–3 per entry, covering activity / type / domain

## Edge cases

- A fact fits multiple durable files → pick the most focused one by the rule in Step 2; cross-file duplication is OK only when both files genuinely benefit (distinct angles on the same fact)
- Uncertain where it belongs → SKIP. The event-daily log already has the raw activity; forcing a bad fit poisons dedup later.
- User says one thing and does another → record both with `#contradiction` tag
- A session spanning hours → write one summary at session end, not per-capture

## Cold start (first 24h after install)

Stricter thresholds:
- Only record very clear identity / preference information.
- Defer project, tool, and topic entries until a pattern emerges across multiple sessions.
- Goal: avoid poisoning the library with early noise. A missed real signal will show up again next session.
