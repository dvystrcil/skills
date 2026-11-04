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

1. **Pick candidates.** Archiving moves whole lines verbatim into
   `MEMORY-ARCHIVE.md` (same dir; the harness does not load it). Topic files
   stay on disk and are still recalled on relevance via their `description:`,
   so de-indexing ≠ deleting.
   Best candidates: entries not *read* in recent sessions (transcripts show
   which `memory/*.md` files were opened), then project status, `reference_*`,
   and narrow app-specific gotchas. Keep behavioural `feedback_*` guards.
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
