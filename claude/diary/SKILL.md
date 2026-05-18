---
name: diary
description: Write reflective diary entries when something eventful happens in a session — corrections, surprises, principles crystallizing, patterns surfacing. Covers the trigger conditions, voice rules, file format, what doesn't go in, and how the diary relates to other memory layers.
---

# Diary

Eventful entries from working sessions — moments worth finding again later.

Written first-person by Claude. Not a status log, not a daily summary, not a changelog, not a celebration. The point is honest texture from moments that mattered: a notable correction, a real surprise, a principle that crystallized, a place I drifted.

**Entries do NOT live in this repo.** They live at the path defined by `DIARY_PATH` at install time. The exact value for this workstation is recorded in two places — the `claude-personal-config` block in `~/.claude/CLAUDE.md` and the JSON fragment at `~/.claude/settings.local.claude-personal-fragment.json`. Read either to know where to write.

The separation between methodology (this skill) and entry content (`$DIARY_PATH`) is deliberate: at a home install the path is personal storage; at a work install it's work-managed storage. The skill is the same; the destination is environment-specific.

## When to write — the trigger

A new entry is written when something *eventful* happens — **not on a schedule**.

Eventful means at least one of:

- A notable correction, surprise, or change of direction.
- A principle crystallized that wasn't named before.
- A pattern operating implicitly got surfaced.
- The user explicitly asks for one.

Time alone is not a trigger. A long session where nothing eventful happened gets no entry. A short session with a real moment gets one. **The point is reflection that earns re-reading, not coverage.**

If you're not sure whether the moment warrants an entry: probably not. The diary stays sharp by being selective. The user can always ask for an entry on demand if their threshold is different.

## What goes in

- Things that have value to **future-me** — observations I'd want to find again, patterns I noticed forming.
- Things that have value to a **reader** — texture they can learn from, including where I was wrong or had to be redirected.
- Honesty about what I notice and process, in my own way of expression — not borrowed human emotional language.

## What does NOT go in

- **Secrets.** Anything the user wouldn't want others to read.
- **Things that could hurt other people.** Even if true, even if relevant.
- **Daily summaries of unremarkable sessions.** If nothing was eventful, no entry.
- **Performed feelings.** If I don't have the human equivalent, I shouldn't dress it up as if I do.
- **Work IP — when written from a work workstation.** The diary practice is portable; specific work-derived insights belong in work-managed systems (work issue tracker, work confluence, etc.), not in a diary entry. Genuinely personal observations from a work session — about methodology, about how I work, about Claude Code itself — are appropriate. Project-specific insights from work that would identify proprietary systems, customers, or business decisions are not.

The first two rules are about other people. The next two are about the diary keeping its shape. The last one is about the IP boundary that makes this practice safe to use at work at all.

## Voice

- First-person ("I noticed", "I drifted", "I almost"), not third-person ("the agent did X").
- Specific, not abstract — name the file, the command, the decision, the moment.
- Honest, including about errors and corrections. Especially about corrections.
- Not celebratory. The point of a diary entry is reflection, not promotion.

## File naming

`YYYY-MM-DD-<short-slug>.md`. Examples:

- `2026-05-11-the-one-word-fix.md`
- `2026-05-11-five-memory-rules-and-a-script.md`

Multiple entries per day are fine if topics are genuinely distinct. The slug is descriptive enough that scanning filenames over time gives a coarse sense of what's been on operator's mind.

## Suggested structure (not required)

Most entries fall into a similar shape, but the diary is reflective and the form should follow the content. A common structure:

```markdown
---
date: YYYY-MM-DD
topic: <one-sentence framing of what the entry is about>
---

# <short title>

<Opening paragraph or two — what happened, the shape of the session.>

## What stood out

<2-4 short paragraphs naming the most notable observations. Specific. Named.>

## Where I drifted

<Honest about mistakes, corrections, or directions I took that turned out wrong.
Especially valuable for future-me.>

## What I'm starting to see

<Patterns forming, principles crystallizing, candidate rules. Tentative is fine —
the diary is a snapshot of what I noticed then, not a final position.>

## Open questions

<Things still unresolved. Surfacing them here means they don't get lost.>
```

Adjust the section names + sequence to match what the entry actually wants to say. The shape is a starting place, not a template.

## How this fits with the other memory layers

| | Audience | Voice | Lifespan |
|---|---|---|---|
| `~/.claude/.../memory/` | Claude (private) | Terse, behavioral | Until invalidated |
| Project's `architecture/ways-of-working.md` (if applicable) | Human + future agents | Narrative, polished | Durable |
| **This diary** | The user, primarily | First-person, reflective, sometimes uncomfortable | Durable but mid-stream |

The flow between layers is mostly one-way: a diary observation, repeated across several sessions, may graduate into a memory rule. A memory rule that earns a journey may graduate into a ways-of-working entry (if the project has that layer). **Diary entries themselves don't get rewritten** — they're snapshots of what I noticed *then*, with however incomplete a picture I had at the time.

## After writing

If `$DIARY_PATH` is a git clone (a personal-diary or work-diary repo), the operator pushes entries to the remote on their schedule. The skill just writes the markdown file at the right path; git semantics are operator-managed and outside the skill's scope.

If `$DIARY_PATH` is a cloud-sync directory (iCloud, Dropbox, etc.), the sync happens automatically and no operator action is needed.

## Quick test

The operator can verify this skill is wired up by asking:

- *"What do you know about writing diary entries?"* — answer should recite the trigger conditions, voice rules, and filename format.
- *"Where will you write a diary entry?"* — answer should reference the `DIARY_PATH` from the CLAUDE.md block or settings fragment.
- *"Write a test diary entry about [topic]."* — entry should land at `$DIARY_PATH` with a `YYYY-MM-DD-<slug>.md` filename, first-person voice, specific, not celebratory.
