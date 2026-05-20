#!/bin/bash
# homelab-memory.sh
#
# CLI for the homelab's shared memory store. The store is currently
# file-backed (markdown-with-frontmatter, the same shape Claude Code's
# auto-memory uses); this CLI provides a single interface so opencode,
# OWUI filter functions, n8n workflows, and humans can all read/write
# without coupling to the storage implementation.
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Single canonical interface to the homelab memory
#                   store. Same store Claude Code's auto-memory uses,
#                   exposed via a stable CLI so other tooling can read
#                   and write without re-implementing the schema.
#
#   when_to_use   : - Need to recall something the homelab "knows" (use
#                     `list`, `show`, or `search`).
#                   - Want to record a new piece of long-lived context
#                     so future agents/sessions can read it (use `add`).
#                   - Want to retire stale memory (use `remove`).
#                   - From opencode / n8n / OWUI filter functions: shell
#                     out to this CLI rather than hand-rolling markdown
#                     parsing.
#
#   when_not_to_use:
#                 : - Ephemeral, conversation-scoped notes — those live
#                     in the conversation, not in memory.
#                   - High-cardinality logs (use Loki) or metrics (use
#                     Prometheus). Memory is for facts, decisions, and
#                     pointers — not telemetry.
#                   - Secrets — they belong in Infisical, not in plain-
#                     text markdown.
#                   - Code patterns, architecture details, file paths —
#                     those are derivable from the project state. See
#                     auto-memory rules.
#
#   input         : Subcommand-driven:
#                     list                          List name + type + description for all entries
#                     show <name>                   Print full body (frontmatter stripped) of one entry
#                     search <query>                Substring match across name + description + body
#                     add <type> <name>             Read body from stdin, write a new entry
#                     remove <name>                 Delete an entry
#                   Where:
#                     <type>   one of: user, feedback, project, reference
#                     <name>   short-ish slug; becomes the filename
#                     <query>  case-insensitive substring
#
#   output        : list / search: one line per entry,
#                     <type>  <name>  <description>
#                   show: the markdown body, frontmatter stripped, to stdout
#                   add / remove: a one-line confirmation to stdout.
#                   Stderr: errors only (set -e behavior).
#
#   exit_codes    : 0 on success. Non-zero on missing args, unknown
#                   subcommand, file-not-found (show/remove), or
#                   already-exists (add without --force).
#
#   side_effects  : - add: writes a new file under $HOMELAB_MEMORY_DIR
#                     and updates MEMORY.md (the index file Claude Code
#                     reads at session start).
#                   - remove: deletes the file and the MEMORY.md line.
#                   - list / show / search: read-only.
#
#   requires      : - $HOMELAB_MEMORY_DIR (defaults to
#                     ~/.claude/projects/-home-dan-Code/memory/) must
#                     exist and be writable for add/remove.
#                   - awk, grep, find. No external deps.
#
#   safe_in_dry_run:
#                 : list / show / search are inherently dry-run.
#                   add / remove have no --dry-run flag yet; if you
#                   want one, use the file-system directly (it's just
#                   markdown).
#
#   composable_with:
#                 : - Auto-memory in Claude Code reads the same files;
#                     anything written here shows up in subsequent
#                     Claude Code sessions automatically.
#                   - opencode integration (n8n-workflow#21) calls this
#                     CLI as its memory layer.
#                   - OWUI filter function (Tier 1, homelab#21) will
#                     call this CLI from Python at chat-start.
#
#   skill_pointer : See ~/.claude/skills/homelab-memory/SKILL.md.
#
# === END METADATA ===

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

MEM_DIR=${HOMELAB_MEMORY_DIR:-$HOME/.claude/projects/-home-dan-Code/memory}
INDEX="$MEM_DIR/MEMORY.md"

print_usage() {
    cat <<EOF
Usage: homelab-memory.sh <subcommand> [args]

Subcommands:
  list                          List all memory entries
  show <name>                   Print body of one entry (frontmatter stripped)
  search <query>                Case-insensitive substring across name+desc+body
  add <type> <name>             Read body from stdin; write a new entry
                                <type> in: user, feedback, project, reference
  remove <name>                 Delete an entry (and remove from MEMORY.md)

Env vars:
  HOMELAB_MEMORY_DIR            Path to the memory store
                                (default: ~/.claude/projects/-home-dan-Code/memory)

Options:
  -h, --help                    Show this help

Examples:
  homelab-memory.sh list
  homelab-memory.sh show feedback_tdd_on_baseline
  homelab-memory.sh search "discord"
  echo "Body content here" | homelab-memory.sh add reference my_new_note
  homelab-memory.sh remove obsolete_entry
EOF
}

# ---- helpers ----

# read_frontmatter_field <field> <file>
# Pull a single field from YAML frontmatter (between --- delimiters).
read_frontmatter_field() {
    local field=$1 file=$2
    awk -v f="$field" '
        /^---$/ { delim++; next }
        delim == 1 && $1 == f":" { sub("^[^:]*: *", ""); print; exit }
    ' "$file"
}

# emit_body <file>
# Print the body of a memory file (everything after the second ---).
emit_body() {
    awk '
        /^---$/ { delim++; next }
        delim >= 2 { print }
    ' "$1"
}

# refresh_index
# Rebuild MEMORY.md from the .md files in the dir. Idempotent.
# Format: `- [Title](file.md) — one-line hook`
refresh_index() {
    [ -d "$MEM_DIR" ] || return 0
    {
        echo "# Memory Index"
        echo
        for f in "$MEM_DIR"/*.md; do
            [ -f "$f" ] || continue
            local base name desc
            base=$(basename "$f")
            [ "$base" = "MEMORY.md" ] && continue
            name=$(read_frontmatter_field "name" "$f")
            desc=$(read_frontmatter_field "description" "$f")
            [ -z "$name" ] && name="${base%.md}"
            echo "- [${name}](${base}) — ${desc:-}"
        done
    } > "$INDEX.tmp"
    mv "$INDEX.tmp" "$INDEX"
}

# ---- argument parsing ----

set +e
sub=""
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) print_usage; exit 0 ;;
        list|show|search|add|remove) sub=$1; shift; break ;;
        *) err "unknown subcommand or flag: $1. Run with --help for usage." ;;
    esac
done
set -e

[ -n "$sub" ] || { print_usage; exit 1; }
[ -d "$MEM_DIR" ] || err "memory dir does not exist: $MEM_DIR"

# ---- subcommands ----

case "$sub" in
    list)
        for f in "$MEM_DIR"/*.md; do
            [ -f "$f" ] || continue
            base=$(basename "$f")
            [ "$base" = "MEMORY.md" ] && continue
            type=$(read_frontmatter_field "type" "$f")
            name=$(read_frontmatter_field "name" "$f")
            desc=$(read_frontmatter_field "description" "$f")
            printf '%-12s  %-40s  %s\n' "${type:-?}" "${name:-${base%.md}}" "${desc:-}"
        done
        ;;

    show)
        [ $# -ge 1 ] || err "show: missing <name> argument"
        target="$1"
        # Match by exact filename (with or without .md), or by frontmatter name.
        f=""
        if [ -f "$MEM_DIR/$target.md" ]; then
            f="$MEM_DIR/$target.md"
        elif [ -f "$MEM_DIR/$target" ]; then
            f="$MEM_DIR/$target"
        else
            for cand in "$MEM_DIR"/*.md; do
                [ -f "$cand" ] || continue
                fn=$(read_frontmatter_field "name" "$cand")
                if [ "$fn" = "$target" ]; then f="$cand"; break; fi
            done
        fi
        [ -n "$f" ] || err "show: no entry matching '$target'"
        emit_body "$f"
        ;;

    search)
        [ $# -ge 1 ] || err "search: missing <query> argument"
        query="$1"
        any=0
        for f in "$MEM_DIR"/*.md; do
            [ -f "$f" ] || continue
            base=$(basename "$f")
            [ "$base" = "MEMORY.md" ] && continue
            type=$(read_frontmatter_field "type" "$f")
            name=$(read_frontmatter_field "name" "$f")
            desc=$(read_frontmatter_field "description" "$f")
            if echo "$name $desc" | grep -qiF "$query" || grep -qiF "$query" "$f"; then
                printf '%-12s  %-40s  %s\n' "${type:-?}" "${name:-${base%.md}}" "${desc:-}"
                any=1
            fi
        done
        [ $any -eq 1 ] || err "search: no matches for '$query'"
        ;;

    add)
        [ $# -ge 2 ] || err "add: usage: add <type> <name>"
        type=$1; name=$2
        case "$type" in
            user|feedback|project|reference) ;;
            *) err "add: <type> must be one of: user, feedback, project, reference" ;;
        esac
        # Sanitize name into a filename — letters, digits, underscores, dashes only.
        slug=$(echo "$name" | tr ' ' '_' | tr -cd 'A-Za-z0-9_-')
        [ -n "$slug" ] || err "add: name produced empty slug after sanitization: '$name'"
        target="$MEM_DIR/$slug.md"
        [ ! -e "$target" ] || err "add: entry already exists at $target. Remove first or pick a different name."

        # Read body from stdin
        body=$(cat)
        [ -n "$body" ] || err "add: stdin was empty; refusing to write an empty body"

        # First non-blank line of body becomes the description if frontmatter doesn't
        # supply one. Take it as the literal first line for now.
        desc=$(echo "$body" | sed -n '1p')

        cat > "$target" <<EOF
---
name: $name
description: $desc
type: $type
---

$body
EOF
        refresh_index
        echo "added: $target"
        ;;

    remove)
        [ $# -ge 1 ] || err "remove: missing <name> argument"
        target="$1"
        f=""
        if [ -f "$MEM_DIR/$target.md" ]; then
            f="$MEM_DIR/$target.md"
        elif [ -f "$MEM_DIR/$target" ]; then
            f="$MEM_DIR/$target"
        else
            for cand in "$MEM_DIR"/*.md; do
                [ -f "$cand" ] || continue
                fn=$(read_frontmatter_field "name" "$cand")
                if [ "$fn" = "$target" ]; then f="$cand"; break; fi
            done
        fi
        [ -n "$f" ] || err "remove: no entry matching '$target'"
        rm -f "$f"
        refresh_index
        echo "removed: $f"
        ;;
esac
