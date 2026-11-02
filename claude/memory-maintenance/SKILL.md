---
name: memory-maintenance
description: Keep Claude Code's auto-memory index (MEMORY.md) inside the loader's budget — 200 lines / 25,000 characters, measured from the binary — and compact it by archiving, never deleting. Use when the "MEMORY.md is … Only part of it was loaded" warning appears, before adding memories to a nearly-full index, or when asked to audit/compact memory.
---

# memory-maintenance

Claude Code auto-loads only a **prefix** of each project's `MEMORY.md`. Past the
cut-off, entries are in no session's context, and the only signal is a warning
in the system prompt that is easy to miss. On the homelab laptop (2026-11-01)
33 of 37 retained sessions ran with a truncated index, and the hidden tail grew
from 3 lines to 79 — the **newest** lessons first, because new entries are
appended at the bottom.

## The real limits

Read from the claude-code 2.1.316 binary, not assumed from docs:

| Limit | Value | Notes |
|---|---|---|
| lines | 200 | after `trim()` |
| size | **25,000 characters** | JS `.length` (UTF-16 units), **not bytes** — the char cap bites first |

When over, the loader keeps the first 200 lines, then cuts at the last newline
at or before index 25,000. Many write-ups (and some third-party "optimizers")
assume a 200-line limit only; an index can be under 200 lines and still lose a
third of itself.

## Check

```bash
~/.claude/skills/memory-maintenance/bin/check-memory-index.py         # every project on this machine
~/.claude/skills/memory-maintenance/bin/check-memory-index.py PATH    # one file
```

Exit 0 = every index loads whole; 1 = something is invisible or a line is over
200 chars (it prints the exact line where the loader cuts); 2 = nothing to
check. It finds `projects/*/memory/MEMORY.md` under `$CLAUDE_CONFIG_DIR` or
`~/.claude`, so it needs no per-machine path.

**Keep ≥ ~3,000 chars of headroom.** The homelab index grew ~230 chars/day;
headroom is a runway, not a fix.

## Compact — archive, never delete

1. **Snapshot first:** copy `MEMORY.md` and `MEMORY-ARCHIVE.md` somewhere
   outside the memory dir.
2. **Archive whole lines verbatim** into `MEMORY-ARCHIVE.md` (same dir; the
   harness does not load it). Topic files stay on disk and are still recalled
   on relevance via their `description:` — de-indexing ≠ deleting.
   Best candidates: entries not *read* in recent sessions (transcripts show
   which `memory/*.md` files were opened), then project status, `reference_*`,
   and narrow app-specific gotchas. Keep behavioural `feedback_*` guards.
3. **Shorten long hooks** (`- [title](file.md) — hook`, aim ≤ 150 chars) and
   put the **original line verbatim** in an archive section, so no wording is
   lost.
4. **Verify losslessly with a script**, not by eye: every pre-compaction line
   from both files exists verbatim in the new index or new archive, no `.md`
   link was dropped, and every index link resolves to a file.
5. **Re-run the check** — exit 0, and note the headroom.

Never let a tool rewrite the whole index from an LLM's judgment without step 4.

## Memory is per machine

This skill is shared across machines; **memory content is not**. Work-session
memory describes an employer's systems — do not sync or back it up to personal
storage. Backups (if any) are configured per machine, outside this repo.
