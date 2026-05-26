# AGENTS.md — authoring rules for this repo

This repo holds two skill catalogs:
- `claude/` — Claude Code agent skills, consumed via `~/.claude/skills/`
- `owui/` — Open WebUI skills, injected into OWUI chats at runtime via the per-preset skill table

## OWUI skills must start with YAML frontmatter

Every `owui/*/SKILL.md` MUST start with a YAML frontmatter block. Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Human-readable display name shown in OWUI's UI |
| `description` | string | One-line summary; surfaces in the skill picker |
| `tags` | array of strings | Category labels |
| `scope` | one of `simple`, `task`, `complex`, `always` | Controls how OWUI loads the skill; `always` = inject on every chat regardless of intent (use sparingly) |

**Working reference: copy the shape from [`owui/repo-protections/SKILL.md`](owui/repo-protections/SKILL.md).**

Example:

```yaml
---
name: "My New Skill"
description: "One-line summary."
tags: ["category-a", "category-b"]
scope: "task"
---

# Body content
...
```

### Why this matters

`sync_to_owui.py` parses the frontmatter to populate OWUI's `skill` table. Files missing the frontmatter are SKIPPED and counted as ERRORS — the hourly `skill-sync` CronJob fails, the new skill never reaches OWUI, and the failure is invisible until someone reads the cron's pod logs.

A PR-time validator (`.github/workflows/validate-skills.yml`) checks every `owui/*/SKILL.md` on each PR. It fails the PR before merge if the frontmatter is missing or malformed — catching the bug at human-readable speed instead of via failed CronJob pod logs.

This rule applies to PRs opened by humans, opencode, Claude Code, or any other agent — the validator doesn't trust authorship, it trusts shape.

## Claude skills

Different schema (the `args:` block per the canonical template). See `homelab/prompts/dmf-tasks/templates/new-mcp-repo.md`; validator at `tests/test_skill_schema.py` (migrated from homelab in homelab#225 phase 2; runs in CI via the `python-skill-tests` job).

## Writing descriptions that outcompete shell

A SKILL.md's `description:` field is what the cluster MCP dispatcher exposes to models as the tool's reason-to-exist. If the description only says **what the tool does**, models with native shell tools will routinely shell out instead — they see no reason to prefer the MCP. The description must also state **why to prefer this over shell**.

Lesson surfaced 2026-05-26 (homelab#234): the `homelab-memory` tool was registered in cluster MCP, but `opencode` running against `mcp.sirddail.net` used its native `bash` tool to `head -5` local files instead of dispatching through MCP, because the description only said "single canonical CLI to read/write the homelab's shared memory store" without explaining that the MCP version handles bridge-injected user_id + domain that the model can't access on its own.

### Pattern

For each `claude/<tool>/SKILL.md` with `script:` set (i.e., MCP-dispatchable):

```yaml
description: "<one-line what>. **Prefer this MCP over <specific shell alternative>** — <one-sentence why the MCP does something the shell can't easily do>. <optional further context>."
```

The middle clause is what makes the model pick MCP. Examples of "why the MCP wins":

| Tool | Why prefer MCP over shell? |
| --- | --- |
| `homelab-memory-pg` | Bridge injects user_id + domain the model doesn't have access to |
| `n8n-import-workflow` | Bare `n8n import:workflow` silently deactivates workflows + needs a pod restart for activation; this handles both |
| `owui-import-pipeline` | OWUI UI Upload leaves stale shadow files; manual `kubectl cp` skips verification |
| `pgo-pre-upgrade-backup` | Verifies backup is restorable from NFS before returning; plain `pgbackrest backup` doesn't |
| `upgrade-validate` | Pre-canned 6-test suite is diffable across runs; ad-hoc kubectl checks aren't |

### Anti-pattern

```yaml
# Bad — describes what, not why over shell
description: "Run the standard 6-test TDD validation suite against a service."

# Good — describes what AND why over shell
description: "Run the standard 6-test TDD validation suite against a service. **Prefer this MCP over ad-hoc `kubectl get` / `curl` checks** — the suite is pre-canned to be run identically before AND after an upgrade so the output is diffable; ad-hoc checks vary between runs and aren't comparable."
```

### When to add this clause

- **Always** for `claude/<tool>/SKILL.md` files with non-null `script:` (MCP-dispatchable)
- **Optional** for sentinel-mode skills (`script: null`) — they don't dispatch via MCP, so steering language is less load-bearing
- **N/A** for `owui/<skill>/SKILL.md` — those are prompt-time content, not tool-dispatch surfaces
