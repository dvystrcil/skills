#!/bin/bash
# n8n-import-workflow.sh
#
# Import (or re-import) one or many n8n workflow JSONs into the running
# n8n instance via the in-pod CLI. Replaces the manual "Import from
# File" UI flow. Re-importing the same JSON updates in place (matched
# by the workflow's internal id field).
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Deploy n8n workflow JSONs from a git repo to the cluster's
#                   running n8n instance. The canonical "load these workflows"
#                   action for any tooling that produces or edits workflow
#                   JSONs (Claude Code, opencode, CI jobs, etc.).
#
#   when_to_use   : After editing or creating one or more workflow JSON files
#                   under n8n-workflow/workflows/. Idempotent — running it
#                   twice with the same input is safe and updates in place.
#
#   when_not_to_use:
#                 : - Credential management (httpHeaderAuth, SMTP, OAuth2):
#                     use the n8n UI. The CLI doesn't manage credentials and
#                     no API supports it cleanly.
#                   - One-off workflow execution: hit the workflow's webhook
#                     URL or use the n8n UI's Execute Workflow button.
#                   - Modifying workflows that are already active: deactivate
#                     first, then re-import. Active-workflow edits while running
#                     are racy.
#
#   input         : A single .json file OR a directory containing *.json
#                   files (non-recursive — only top level).
#                   Each file must be a valid n8n workflow export with a
#                   .name field at the top level (this script reads the name
#                   via jq for verification).
#
#   output        : Stdout — three-step progress lines + a trailing 'OK' on
#                   success. Format:
#                     [1/3] resolving n8n pod ........... <pod>
#                     [2/3] importing N workflow(s) ..... <names>
#                     [3/3] verifying via list:workflow . <id>|<name>   (one row per workflow)
#                     OK
#                   Stderr — used for diagnostic messages (log_info) and
#                   error messages (err) only. Stdout is the contract.
#
#   exit_codes    : 0 on success; non-zero on any failure with a single-line
#                   error to stderr. Failures are non-resumable — fix the
#                   reported issue and re-run.
#
#   side_effects  : - kubectl cp into pod's /tmp/ (cleaned up on success).
#                   - Mutates the n8n internal database (sqlite/postgres
#                     depending on n8n config) to add or update workflow rows.
#                   - With --activate: also flips the workflow's active flag
#                     (n8n will start cron triggers, webhook listeners, etc.).
#
#   requires      : - kubectl (with read/exec on namespace n8n-workflow).
#                   - jq (local). Used to read workflow .name from JSON.
#                   - The n8n pod must be Running.
#
#   safe_in_dry_run:
#                 : No --dry-run flag. The closest equivalent is `n8n list:workflow`
#                   from inside the pod to confirm the workflow already exists
#                   (i.e. an import would be a no-op update).
#
#   composable_with:
#                 : - homelab/bin/upgrade-validate.sh (validate cluster state
#                     after a workflow goes live).
#                   - n8n_workflow#19-style scheduled triggers (the workflows
#                     this imports often have cron triggers that take effect
#                     when --activate is passed).
#
#   skill_pointer : See .claude/skills/n8n-import-workflow.md for the
#                   canonical skill description (Claude Code / opencode-readable).
#
# === END METADATA ===
#
# Usage:
#   n8n-import-workflow.sh <file-or-dir> [--activate]
#
# Output (machine-parseable contract):
#   [1/3] resolving n8n pod ............... <pod-name>
#   [2/3] importing N workflow(s) ......... <comma-separated names>
#   [3/3] verifying via list:workflow ..... <id> <name>
#   OK
#
# Exit 0 on success; non-zero with a clear message on any failure.

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

NS="n8n-workflow"
DEPLOY="n8n"
CONTAINER="n8n"
N8N_BIN="/usr/local/bin/n8n"

print_usage() {
    cat <<EOF
Usage: n8n-import-workflow.sh <file-or-dir> [options]

Import one or many n8n workflow JSON files into the running n8n
instance. Re-importing the same JSON updates in place (matched by
the workflow's internal id field).

Args:
  <file-or-dir>     A .json file, OR a directory containing *.json files

Options:
  --activate        After successful import, set the workflow active
  -h, --help        Show this help

Examples:
  n8n-import-workflow.sh workflows/cluster_service_health_watcher.json
  n8n-import-workflow.sh workflows/
  n8n-import-workflow.sh workflows/foo.json --activate
EOF
}

set +e
input=""
activate=0
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)  print_usage; exit 0 ;;
        --activate) activate=1; shift ;;
        --*)        err "unknown flag: $1" ;;
        *)          input="$1"; shift ;;
    esac
done
set -e

[ -n "$input" ] || err "missing required argument: <file-or-dir>. Run with --help for usage."
[ -e "$input" ] || err "no such file or directory: $input"

require kubectl

# ---- step 1: resolve the running n8n pod ----

# Find the most-recently-created Running pod for the deployment. Mid-
# rollout, the new RS's pod will sort first; old pod (Terminating) is
# excluded by the field-selector.
POD=$(kubectl -n "$NS" get pods \
    -l "app=n8n" \
    --field-selector=status.phase=Running \
    --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{.items[-1:].metadata.name}' 2>&1) || true

[ -n "$POD" ] || err "no Running pod found for deploy/$DEPLOY in namespace $NS"
log_step 1 3 "resolving n8n pod" "$POD"

# ---- step 2: collect JSON files + import ----

declare -a FILES
if [ -d "$input" ]; then
    while IFS= read -r f; do
        FILES+=("$f")
    done < <(find "$input" -maxdepth 1 -type f -name '*.json' | sort)
    [ ${#FILES[@]} -gt 0 ] || err "no .json files in directory: $input"
else
    case "$input" in
        *.json) FILES=("$input") ;;
        *)      err "input must be a .json file or a directory of them: $input" ;;
    esac
fi

names=""
no_id_files=()
for f in "${FILES[@]}"; do
    base=$(basename "$f")
    [ -z "$names" ] && names="$base" || names="$names, $base"
    # Pre-import check: if the JSON has no top-level `id`, every n8n
    # import:workflow run creates a NEW row rather than updating in place.
    # This silently accumulates duplicates. Flag it loudly so the operator
    # can add a stable id before the next re-import.
    if [ "$(jq -r '.id // "null"' "$f")" = "null" ]; then
        no_id_files+=("$base")
    fi
done
log_step 2 3 "importing ${#FILES[@]} workflow(s)" "$names"

if [ ${#no_id_files[@]} -gt 0 ]; then
    log_info "WARNING: ${#no_id_files[@]} workflow(s) have no top-level 'id' field:"
    for b in "${no_id_files[@]}"; do
        log_info "  - $b"
    done
    log_info "Re-imports of these files create NEW workflow rows rather than"
    log_info "updating in place. After this import, copy the generated id from"
    log_info "the verify-step output and add it as a top-level \"id\" field in"
    log_info "the JSON. Future re-imports will then update-in-place."
fi

# Copy + import each.
for f in "${FILES[@]}"; do
    base=$(basename "$f")
    pod_path="/tmp/n8n-import-$$-$base"

    kubectl -n "$NS" cp "$f" "$POD:$pod_path" -c "$CONTAINER" >/dev/null 2>&1 || \
        err "kubectl cp into pod failed for $base"

    out=$(kubectl -n "$NS" exec "$POD" -c "$CONTAINER" -- "$N8N_BIN" import:workflow --input="$pod_path" 2>&1) || \
        { log_info "$out"; err "n8n import:workflow failed for $base"; }
    # The CLI emits "Successfully imported N workflow." — anything else is a yellow flag we'd want to see.
    echo "$out" | grep -qE 'Successfully imported [0-9]+ workflow' || \
        { log_info "$out"; err "n8n import did not report success for $base"; }

    # Best-effort cleanup of the in-pod copy.
    kubectl -n "$NS" exec "$POD" -c "$CONTAINER" -- rm -f "$pod_path" >/dev/null 2>&1 || true
done

# ---- step 3: verify via list:workflow ----

LIST=$(kubectl -n "$NS" exec "$POD" -c "$CONTAINER" -- "$N8N_BIN" list:workflow 2>&1) || \
    err "n8n list:workflow failed (workflows may have imported but verification couldn't run)"

# Extract just the rows that look like '<id>|<name>'. The CLI may emit
# deprecation warnings on stdout above the list — filter to what we want.
# Match any 8+-char alnum id followed by pipe. n8n's auto-generated ids
# are 16 chars, but operator-set stable ids (added per the warning above)
# may be different lengths. Filter is loose enough to accept those + tight
# enough to skip deprecation warnings and other CLI noise.
ids_lines=$(echo "$LIST" | grep -E '^[A-Za-z0-9]{8,}\|')

# For each imported file, find the matching name in the list. The
# workflow's name is in the JSON at .name; pull it via jq.
matches=""
for f in "${FILES[@]}"; do
    name=$(jq -r '.name' "$f")
    line=$(echo "$ids_lines" | grep -F "|$name" | head -1) || true
    if [ -z "$line" ]; then
        err "imported workflow '$name' did not appear in list:workflow output"
    fi
    matches+="$line"$'\n'
done

# Trim trailing newline; print one line per match
echo "$matches" | head -n -1 | while read -r line; do
    [ -n "$line" ] && log_step 3 3 "verifying via list:workflow" "$line"
done

# Duplicate-name detection — n8n's import:workflow creates a new row when
# the JSON has no top-level id, and the verify step above only finds the
# FIRST match by name. Duplicates would accumulate silently across re-imports.
# Caught a 4-row accumulation on homelab#44 phase 3b on 2026-05-11; this
# guard prevents the silent-recurrence pattern.
total_dups=0
for f in "${FILES[@]}"; do
    name=$(jq -r '.name' "$f")
    # Anchored match: pipe + name + end-of-line. grep -F's substring match
    # would over-count if one workflow name is a prefix of another.
    count=$(echo "$ids_lines" | awk -F'|' -v n="$name" '$2==n{c++}END{print c+0}')
    if [ "$count" -gt 1 ]; then
        total_dups=$((total_dups + count - 1))
        log_info ""
        log_info "WARNING: $count workflow rows match the name '$name':"
        echo "$ids_lines" | awk -F'|' -v n="$name" '$2==n{print "    " $1 " | " $2}' >&2
        log_info "    Likely-canonical id (from this import): $(echo "$matches" | grep -F "|$name" | head -1 | cut -d'|' -f1)"
        log_info "    To deduplicate: connect to n8n's postgres and"
        log_info "      DELETE FROM workflow_entity WHERE name = '$name' AND id != '<canonical-id>';"
    fi
done
if [ "$total_dups" -gt 0 ]; then
    log_info ""
    log_info "Total duplicate rows: $total_dups. Import succeeded, but the workflows have"
    log_info "siblings — see warnings above. Re-imports keep accumulating until the JSON"
    log_info "carries a stable top-level 'id'."
fi

# ---- optional --activate ----

if [ "$activate" = "1" ]; then
    for f in "${FILES[@]}"; do
        name=$(jq -r '.name' "$f")
        wf_id=$(echo "$ids_lines" | grep -F "|$name" | head -1 | cut -d'|' -f1)
        [ -n "$wf_id" ] || err "could not resolve workflow id for '$name'"
        kubectl -n "$NS" exec "$POD" -c "$CONTAINER" -- \
            "$N8N_BIN" update:workflow --id="$wf_id" --active=true >/dev/null 2>&1 || \
            err "activation failed for '$name' (id=$wf_id)"
        log_info "activated: $name (id=$wf_id)"
    done

    # n8n's runtime caches active workflows at startup and does NOT refresh
    # on import:workflow OR update:workflow --active=true (the CLI says so:
    # "Activation or deactivation will not take effect if n8n is running.").
    # Without a pod restart, the new JSON sits in the DB while the scheduler
    # keeps running the OLD cached version. This caused 90+ false error
    # rows on cluster_service_health_watcher in 1.5 hours (homelab#48).
    #
    # Restart the deployment so the scheduler reloads from DB. Brief
    # service-affecting downtime (~30s); in-flight executions get cut.
    log_info "restarting n8n deployment to invalidate scheduler cache (homelab#48)"
    kubectl -n "$NS" rollout restart deploy/n8n >/dev/null 2>&1 || \
        err "rollout restart failed; activation may not take effect until manual restart"
    kubectl -n "$NS" rollout status deploy/n8n --timeout=120s >/dev/null 2>&1 || \
        err "rollout did not complete within 120s"
    log_info "n8n restarted; cache invalidated"
fi

echo "OK"
