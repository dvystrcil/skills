---
name: owui-memory-loader
description: Open WebUI filter that injects homelab memory entries into the system prompt at chat-start. Mirrors Claude Code's auto-memory pattern in OWUI. Source-of-truth Python lives in homelab/prompts/owui/filters/; user installs into OWUI via the Functions UI.
---

# OWUI Memory Loader Filter

You are working with the Open WebUI filter that gives OWUI conversations the same memory-injection behavior Claude Code's auto-memory provides. The filter reads markdown-with-frontmatter files from a configured directory and prepends a structured memory section to the system message before the LLM sees the conversation.

This skill is for two audiences:
- An agent (Claude Code, opencode) being asked to modify, debug, or extend the filter.
- An agent recommending whether OWUI should have this behavior at all.

## When to use this skill

- The user asks "why is OWUI not seeing my memory?" or "how does memory injection work in chat?"
- A new memory-related capability needs to land (e.g. user-scoped memory, dynamic relevance ranking, etc.) and the filter is where it goes.
- Debugging missing-memory or duplicate-injection issues in OWUI conversations.

## When NOT to use it

- For agents that aren't OWUI — Claude Code reads memory natively; opencode is configured separately. This filter is OWUI-specific.
- For *writing* memory — that's `homelab-memory.sh add` (the CLI). This filter only reads.
- For low-level memory schema questions — see the `homelab-memory` skill, which describes the storage primitive this filter reads from.

## Source-of-truth location

```
/home/dan/Code/homelab/prompts/owui/filters/memory_loader.py
```

Tests at `tests/test_memory_loader.py`. README at `README.md` in the same directory.

The filter is **not deployed via GitOps** — it's installed into OWUI through the Functions UI per the established homelab pattern (skills/filters managed in OWUI's UI; source-of-truth in this repo to prevent drift). On change: edit the .py file, run tests, paste updated code into OWUI's Functions edit screen.

## Behavior summary

- Reads `*.md` files from `memory_dir` Valve (default `/data/memory`).
- Skips `MEMORY.md` (it's an index file).
- Sorts newest-first by mtime; caps at `max_entries` (default 30).
- Parses frontmatter (`name`, `description`, `type`).
- Builds a markdown memory section under a `# Homelab Memory` header.
- On `inlet()`:
  - Master `enabled` Valve toggle bypasses if false.
  - Idempotency: checks any existing system message for the header; skips if present.
  - Otherwise: prepends the section to the existing system message, or creates a new system message if there isn't one.

## Edge cases the filter handles

- **No memory_dir / unreadable dir**: filter is a no-op.
- **Malformed file (no frontmatter)**: silently skipped via the `_parse_entry` early return.
- **Multi-turn conversations**: only injects once per conversation thanks to the sentinel-string check.
- **Empty memory dir**: no section built, request passes through unchanged.

## Pod-side memory access (deployment dependency)

The filter assumes `memory_dir` points at a real path inside the OWUI pod. The canonical memory store lives at `~/.claude/.../memory/` on the user's workstation. Bridging is a deployment concern, not a filter concern. Options:

- NFS mount of the memory dir into OWUI's deployment.
- Periodic git sync via sidecar.
- Rsync from workstation cron.
- HTTP service in front of `homelab-memory.sh`, with the filter rewritten to fetch over HTTP.

Until that's wired, the filter installed in OWUI is a no-op (memory_dir is empty). That's fine; it ships behavior + tests in advance of deployment plumbing.

## See also

- Filter source: `/home/dan/Code/homelab/prompts/owui/filters/memory_loader.py`.
- Tests: same dir, `tests/test_memory_loader.py`. 15 cases, run with `tests/run.sh`.
- README with install steps + Valve table: `homelab/prompts/owui/filters/README.md`.
- Storage primitive this reads from: see the `homelab-memory` skill.
- Architecture: `homelab/architecture/local-ai-stack.md` Tier 1.
- Tracking issue: [homelab#21](https://github.com/dvystrcil/homelab/issues/21).
