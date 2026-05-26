---
name: homelab-memory
description: File-backed memory CLI (workstation-only). For cluster MCP contexts, use [[homelab-memory-pg]] instead — the file-backed store doesn't exist on cluster pods. This skill is sentinel-mode for the cluster MCP dispatcher; the bash script still works for direct laptop-side invocation.
script: null
args: []
---

# Homelab Memory (file-backed, workstation-only)

> **Status note (2026-05-26, homelab#233):** This skill is **sentinel mode** for the cluster-resident MCP server — the dispatcher will not register it as a tool. The underlying bash script at `bin/homelab-memory.sh` still works when invoked directly from a workstation shell (Claude Code, opencode local bash tool, manual CLI). For cluster MCP dispatch — i.e. when called from OWUI, in-cluster opencode, or laptop-via-Tailscale — use [[homelab-memory-pg]] which is Postgres-backed and works in cluster context.

You are reading from or writing to the homelab's shared memory store via the file-backed CLI. The store is `~/.claude/projects/-home-dan-Code/memory/` — same directory Claude Code's auto-memory writes to.

This is a **storage primitive**, not a curatorial pattern. It does CRUD; it does not synthesize.

## When to use this skill

- **Read** memory before answering an operational question — `list` to scan, `show` for detail, `search` to find by substring.
- **Add** a memory entry when you learn something durable: a user preference, a feedback note, a pointer to an external system, a project fact that future sessions should know.
- **Remove** an entry when it's wrong, outdated, or duplicates a better one.
- **Invoke from a workstation shell context** — Claude Code, opencode (laptop), or a direct CLI session. NOT from cluster MCP.

The auto-memory rules from the system prompt still apply. Don't save things derivable from project state, code patterns, or git history. Memory is for non-obvious facts.

## When NOT to use it

- **From cluster MCP dispatch context.** The file-backed store doesn't exist on cluster pods. Use `homelab-memory-pg` instead.
- **Ephemeral, conversation-scoped notes** — they live in the conversation, not in memory.
- **High-cardinality logs / metrics** — Loki and Prometheus, not memory.
- **Secrets** — Infisical, not memory. The files are plaintext markdown.
- **Synthesized knowledge** ("the homelab's networking model", "how PGO is installed", "the upgrade playbook") — those belong in `homelab/architecture/*.md` and equivalents. Memory is for atomic facts; the architecture docs are for synthesized concepts.

## How to invoke

```bash
# Read
homelab/bin/homelab-memory.sh list
homelab/bin/homelab-memory.sh show feedback_tdd_on_baseline
homelab/bin/homelab-memory.sh search "discord"

# Write
echo "Body content here" | homelab/bin/homelab-memory.sh add reference my_new_note
homelab/bin/homelab-memory.sh remove obsolete_entry
```

The `add` subcommand reads the body from stdin. Pipe in a heredoc or echo for short content; for longer entries, write to a file first and `cat file.md | homelab-memory.sh add ...`.

`<type>` is one of `user, feedback, project, reference` — same vocabulary Claude Code's auto-memory uses.

## Subcommand reference (preserved from previous dispatcher metadata)

The cluster MCP dispatcher no longer reads structured args from frontmatter for this skill (sentinel mode), but the CLI's behavior is documented here for direct callers:

| Subcommand | Args (positional) | stdin | Notes |
|---|---|---|---|
| `list` | none | none | Lists every entry (type/name/description) |
| `show` | `name` | none | Prints body, frontmatter stripped |
| `search` | `query` | none | Case-insensitive substring across name + desc + body |
| `add` | `type name` | body | Creates a new entry; `type` must be one of `user, feedback, project, reference` |
| `remove` | `name` | none | Deletes the entry |

## Output contract

- `list` and `search` print one row per entry: `<type>  <name>  <description>` aligned in fixed columns. Trivially parseable.
- `show` prints the body markdown (frontmatter stripped).
- `add` and `remove` print a one-line confirmation: `added: <path>` or `removed: <path>`.
- Errors go to stderr; non-zero exit on any failure.

## Things that go wrong (and what to do)

- **`ERROR: neither HOMELAB_MEMORY_DIR nor HOME is set`** — set one. Default `$HOME/.claude/projects/-home-dan-Code/memory/` resolves only when `$HOME` exists. Cluster contexts (which shouldn't be using this skill anyway — see status note) have no `$HOME` and hit this. Per skills#18.
- **`memory dir does not exist`** — `$HOMELAB_MEMORY_DIR` points at a path that isn't there. Override the env var to point at a real dir, or create the default.
- **`add: entry already exists`** — pick a different name or `remove` the existing one first. The CLI refuses to silently overwrite to prevent collisions across tools.
- **`add: name produced empty slug`** — the name had only special chars. Use letters/digits/underscores/dashes.
- **`add: stdin was empty`** — body is required. The CLI refuses to write empty entries.

## Composability

```bash
# Pre-flight: check if a known fact is already recorded before deciding what to do
if homelab/bin/homelab-memory.sh search "PGO install state" >/dev/null 2>&1; then
  echo "we already know about this"
fi

# After establishing a new fact, persist it
cat <<'EOF' | homelab/bin/homelab-memory.sh add project new_finding
Body of the finding goes here.

Why: explanation of why this matters.
How to apply: when this knowledge is relevant.
EOF
```

For OWUI filter functions calling this CLI: shell out from Python with `subprocess.run([..., "homelab-memory.sh", "list"], capture_output=True, text=True, check=True)`. **But prefer `homelab-memory-pg` if the call is from an in-cluster Python context** — file-backed won't work.

## See also

- Postgres-backed sibling: [[homelab-memory-pg]] — the cluster-MCP-dispatchable version.
- Script source: `bin/homelab-memory.sh` — full AI metadata header at top.
- Tests: `/home/dan/Code/homelab/bin/tests/test_homelab_memory.sh` (16 cases, all green).
- Architecture: `/home/dan/Code/homelab/architecture/local-ai-stack.md` — Tier 1's "memory injection" piece.
- Related: `homelab/architecture/` — the wiki layer Karpathy-style; complements memory.
- Auto-memory rules from Claude Code's system prompt apply; the schema is shared.
