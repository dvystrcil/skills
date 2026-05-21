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
| `scope` | one of `simple`, `task`, `complex` | Controls how OWUI loads the skill |

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

Different schema (the `args:` block per the canonical template). See `homelab/prompts/dmf-tasks/templates/new-mcp-repo.md`; validator at `homelab/bin/tests/test_skill_schema.py`.
