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

## Audit — orphans and unused entries (report only)

```bash
~/.claude/skills/memory-maintenance/bin/memory-audit.py --memory-dir "$M"            # text
~/.claude/skills/memory-maintenance/bin/memory-audit.py --memory-dir "$M" --json     # machine
~/.claude/skills/memory-maintenance/bin/memory-audit.py --memory-dir "$M" --names-only --days 30
```

It never writes. Exit 0 = clean, 1 = findings, 2 = usage / no `MEMORY.md`.

- **Orphans.** Every topic file, and every `](x.md)` link in the index and
  archive, is LIVE, ORPHAN (a `type_name.md` file with no line, or a line whose
  file is gone) or UNDECIDED (a stray `.md` outside the
  `(user|feedback|project|reference)_*.md` pattern, or a link out of the dir).
  Salvage an ORPHAN file into the archive before removing anything.
- **Unused.** Index entries whose file no transcript (`projects/**/*.jsonl`)
  shows a session using in N days, oldest first. "Used" = a Read/Write/Edit
  `tool_use` on the file, or its re-attachment after a compaction. Relevance
  recall (`<system-reminder>` injection) is **not** recorded per file, so it
  can't be counted. Sessions rarely Read memory: on the homelab laptop
  (2026-11-04) 117 of 139 entries had never been Read in 40 days. Treat the
  list as a review queue, never as an archive command.

## Compact — archive, never delete

1. **Pick candidates.** Archiving moves whole lines verbatim into
   `MEMORY-ARCHIVE.md` (same dir; the harness does not load it). Topic files
   stay on disk and are still recalled on relevance via their `description:`,
   so de-indexing ≠ deleting.
   Start from `memory-audit.py`'s unused list, reviewed by hand: an entry
   never Read can still be doing its job through the always-loaded index. Then
   project status, `reference_*`, and narrow app-specific gotchas. Keep
   behavioural `feedback_*` guards. `--names-only` output goes to the archiver
   unchanged (`| xargs -d '\n' archive-memory-lines.py ... --dry-run`).
2. **Archive with the script**, never by hand. Names are the link text,
   `- [name](file.md)`:

   ```bash
   A=~/.claude/skills/memory-maintenance/bin/archive-memory-lines.py
   M=~/.claude/projects/<project>/memory
   $A --memory-dir "$M" --section "narrow gotchas" --dry-run name-one name-two
   $A --memory-dir "$M" --section "narrow gotchas" name-one name-two
   ```

   In one run it:
   - refuses, writing nothing, any name that matches 0 or more than 1 index
     lines (prefixes don't count)
   - backs up both files to `~/.local/state/claude-memory/archive-backups/<ts>/`
     (`--backup-dir` to change; refused if inside the memory dir)
   - moves the lines verbatim under `## Archived <date> — <section>`
   - recounts the `> N more hooks` pointer as distinct archived-only links,
     compared byte-exact (`LC_ALL=C` semantics)
   - re-reads both files and checks that no line was lost, no `.md` link was
     dropped, every index link resolves, and the pointer is right. If any of
     that fails it **restores both files from the backup** (exit 3).
   - runs `check-memory-index.py` on the result

   Exit 0 = archived and the index loads whole. 1 = archived, but the check
   still fails, so archive more. 2 = refused. 3 = restored.
3. **Shorten long hooks** (`- [title](file.md) — hook`, aim ≤ 150 chars) and
   put the **original line verbatim** in an archive section, so no wording is
   lost. The script doesn't do this one. Snapshot both files first and verify
   the same way: every old line is still present in one of the two files, and
   no link was dropped.
4. **Note the headroom** from the check's output.

Never let a tool rewrite the whole index from an LLM's judgment without the
lossless verify.

## Format check — one file you just wrote

```bash
~/.claude/skills/memory-maintenance/bin/check-memory-file.py --require-index "$M/feedback_x.md"
```

Claude Code and opencode write into the same dir (homelab#2002), so a new file
must be in the shape both read: frontmatter with `name:`, `description:` and a
type (`metadata:` → `type:`); a `<type>_<snake_case>.md` name; for feedback and
project memories a `**Why:**` line and a `**How to apply:**` line with text in
the body; with `--require-index`, a link from `MEMORY.md` or the archive. Exit
0 = ok, 1 = problems (printed per file), 2 = usage. It checks files as they
are written. It doesn't check the legacy store: on 2026-11-09, 112 older
feedback/project files had no `**Why:**`.

## Archive recall — both tools

`bin/memory-recall.py` brings an archived entry back when a prompt is about
it. Neither tool loads `MEMORY-ARCHIVE.md` otherwise. It prints the entry's
absolute path and hook, so the agent can read the file.

| tool | wiring |
|---|---|
| Claude Code | `UserPromptSubmit` hook: `memory-recall.py --claude-hook` (memory dir taken from the hook's `transcript_path`) |
| opencode | `prompt` hook plugin, `homelab/opencode/plugins/memory-recall/` |

The matching is deterministic, with no model call. An entry needs **two
matching words that are rare** across the archive (in at most 1% of entries,
minimum 3). Prompts over 40 distinct words are skipped. On 120 real prompts
this put a block on 6 of them, against 18 of 30 for "any two matching words".

## History + backup (hourly)

`bin/memory-backup.sh` (systemd units in `systemd/`):

1. **Local-only git** in each memory dir: commits any change. A memory dir
   with a git **remote is refused**; no remote means one writer, nothing
   to diverge from, nothing pushed in clear.
2. Runs the index gate (reported, never blocks the backup).
3. Runs `gitleaks` over the dir if installed.
4. If `BACKUP_ENABLED=1`: restic snapshot (`.git` included) + retention
   48h/30d/26w/24m, then writes `~/.local/state/claude-memory/last-backup`.

`bin/memory-session-check.sh` is a report-only SessionStart line: index
headroom (WARN < 3,000 chars, FAIL if truncated) and snapshot age (WARN > 24h).

Config is per machine, in `~/.config/claude-memory/backup.env`, never in a repo:

```bash
BACKUP_ENABLED=0                       # default: local history only
RESTIC_REPOSITORY=sftp:host-alias:/path/repo
RESTIC_PASSWORD_FILE=$HOME/.config/restic/claude-memory.pass   # mode 600; escrow it off this machine
PATH=/home/linuxbrew/.linuxbrew/bin:$PATH   # systemd user units do not see brew; the job names a missing restic/gitleaks
```

For an SFTP target, give the backup key a root-owned home and `.ssh`, with
the repo in a user-owned subdir, and pin the key with
`restrict,command="/usr/lib/openssh/sftp-server"`. A user-owned
`authorized_keys` lets the key holder strip the pin.

## Memory is per machine

This skill is shared across machines; **memory content is not**. Work-session
memory describes an employer's systems — do not sync or back it up to personal
storage. Backups (if any) are configured per machine, outside this repo.
