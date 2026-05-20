#!/bin/bash
# owui-import-pipeline.sh
#
# Install (or re-install) an OWUI Pipeline by copying it onto the
# owui-pipelines pod's PVC and triggering a runtime reload. Replaces
# the manual "Admin Panel → Settings → Pipelines → upload this file"
# UI flow.
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Deploy OWUI Pipeline .py files (filter / pipe /
#                   manifold types) from a git repo to the running
#                   owui-pipelines pod. Lets you treat pipelines as
#                   versioned artifacts and re-deploy on every edit
#                   without clicking through the admin UI.
#
#   when_to_use   : - After editing or creating a Pipeline source
#                     file under homelab/prompts/owui/filters/ or any
#                     other dir of OWUI Pipeline Python.
#                   - Re-running with the same input is safe and
#                     overwrites in place. The runtime reload
#                     re-registers the pipeline.
#
#   when_not_to_use:
#                 : - For OWUI Functions (the inside-OWUI extension
#                     surface, not Pipelines). Functions live in
#                     OWUI's own DB, not on the pipelines PVC. They
#                     install via OWUI's Functions REST API or the
#                     Workspace UI.
#                   - For pipeline credential setup. Credentials/Valves
#                     are configured in the OWUI UI under Pipelines
#                     after the file is installed; this script doesn't
#                     touch them.
#
#   input         : Single positional arg: a .py file or a directory
#                   containing *.py files. Filenames must be valid
#                   Python module names (no dashes; underscores OK).
#                   The base filename (sans .py) becomes the pipeline
#                   id in OWUI.
#
#   output        : Stdout — three contracted progress lines + 'OK'
#                     [1/3] resolving owui-pipelines pod ........ <pod>
#                     [2/3] copying N pipeline(s) ............... <names>
#                     [3/3] verifying via /v1/pipelines ......... <id> <name>
#                     OK
#                   Stderr — diagnostics + errors only.
#
#   exit_codes    : 0 on success. Non-zero on missing args, bad input,
#                   pod not running, kubectl cp failure, or the
#                   pipelines runtime not registering the new file.
#
#   side_effects  : - kubectl cp into pod's /app/pipelines/.
#                   - GET /v1/pipelines after, to confirm registration.
#                   - Does NOT restart the pod; relies on the runtime's
#                     hot-reload via the API. If the runtime can't
#                     hot-reload (older OWUI Pipelines), the pipeline
#                     will register on next pod restart.
#
#   requires      : kubectl (read + cp into open-webui namespace).
#                   curl image is used internally for the verification
#                   probe; access to the owui-pipelines Service.
#
#   safe_in_dry_run:
#                 : No --dry-run; closest equivalent is `kubectl exec
#                   <pod> -- ls /app/pipelines/` to see what's already
#                   there.
#
#   composable_with:
#                 : - homelab/bin/n8n-import-workflow.sh (sister script
#                     for n8n workflow JSON deploys).
#                   - homelab-memory.sh (storage primitive that the
#                     memory_loader pipeline reads from).
#
#   skill_pointer : See ~/.claude/skills/owui-import-pipeline/SKILL.md.
#
# === END METADATA ===

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

NS="open-webui"
APP_LABEL="app=owui-pipelines"
SVC="owui-pipelines"
PORT=9099
# OWUI Pipelines uses a static API key by default; PIPELINES_API_KEY env
# var on the pod overrides. The default value is documented widely; we
# read the live one from the pod env to stay correct.
PIPE_DIR="/app/pipelines"

print_usage() {
    cat <<EOF
Usage: owui-import-pipeline.sh <file-or-dir>

Install one or more OWUI Pipeline .py files into the running
owui-pipelines pod.

Args:
  <file-or-dir>     A .py file, OR a directory containing *.py files

Options:
  -h, --help        Show this help

Examples:
  owui-import-pipeline.sh prompts/owui/filters/memory_loader.py
  owui-import-pipeline.sh prompts/owui/filters/

NOTE: This installs Pipelines (the owui-pipelines pod surface), NOT
Functions (OWUI's inside-the-app surface). They're different extension
points; see ~/.claude/skills/owui-import-pipeline/SKILL.md for details.
EOF
}

set +e
input=""
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) print_usage; exit 0 ;;
        --*)       err "unknown flag: $1" ;;
        *)         input="$1"; shift ;;
    esac
done
set -e

[ -n "$input" ] || err "missing required argument: <file-or-dir>. Run with --help."
[ -e "$input" ] || err "no such file or directory: $input"

require kubectl

# ---- step 1: resolve owui-pipelines pod ----

POD=$(kubectl -n "$NS" get pods -l "$APP_LABEL" \
    --field-selector=status.phase=Running \
    --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{.items[-1:].metadata.name}' 2>&1) || true
[ -n "$POD" ] || err "no Running pod found with label $APP_LABEL in namespace $NS"
log_step 1 3 "resolving owui-pipelines pod" "$POD"

# Pull the API key from the pod env. Falls back to the documented default
# if the env var isn't set — but warn loudly because that means the pod
# is using insecure defaults.
API_KEY=$(kubectl -n "$NS" exec "$POD" -- printenv PIPELINES_API_KEY 2>/dev/null) || true
if [ -z "$API_KEY" ]; then
    log_info "PIPELINES_API_KEY not set on the pod; falling back to default '0p3n-w3bu!'"
    API_KEY='0p3n-w3bu!'
fi

# ---- step 2: collect .py files + pre-flight + copy ----

declare -a FILES
if [ -d "$input" ]; then
    while IFS= read -r f; do FILES+=("$f"); done < \
        <(find "$input" -maxdepth 1 -type f -name '*.py' | sort)
    [ ${#FILES[@]} -gt 0 ] || err "no .py files in directory: $input"
else
    case "$input" in
        *.py) FILES=("$input") ;;
        *)    err "input must be a .py file or a directory of them: $input" ;;
    esac
fi

# Pre-flight: every file must have BOTH `class Pipeline:` AND a Valves
# class with a `pipelines` attribute. Without the latter, OWUI's /models
# endpoint will throw an AttributeError that cascades and hides ALL
# pipelines from the admin UI ("Pipelines Not Detected"). Catch this
# before kubectl cp so we don't break a working runtime.
for f in "${FILES[@]}"; do
    base=$(basename "$f")
    if ! grep -q '^class Pipeline:' "$f"; then
        err "$base: missing 'class Pipeline:' — is this a Function rather than a Pipeline? See ~/.claude/skills/owui-import-pipeline/SKILL.md."
    fi
    if ! grep -qE '^\s*pipelines\s*:\s*list' "$f"; then
        err "$base: Valves class is missing the required 'pipelines: list[str]' field. Without it, OWUI's /models endpoint will throw AttributeError and zero out ALL pipelines from the admin UI. Add it (default ['*']) and re-run. See ~/.claude/skills/owui-import-pipeline/SKILL.md."
    fi
done

names=""
for f in "${FILES[@]}"; do
    base=$(basename "$f")
    [ -z "$names" ] && names="$base" || names="$names, $base"
done
log_step 2 3 "copying ${#FILES[@]} pipeline(s)" "$names"

for f in "${FILES[@]}"; do
    base=$(basename "$f")
    kubectl -n "$NS" cp "$f" "$POD:$PIPE_DIR/$base" >/dev/null 2>&1 || \
        err "kubectl cp failed for $base"
done

# ---- step 3: trigger reload + verify ----

# OWUI Pipelines exposes a reload endpoint. POST without body.
RELOAD_OUT=$(kubectl -n "$NS" run owui-import-probe-$$ --rm -i --restart=Never --quiet \
    --image=curlimages/curl:8.10.1 -- \
    curl -sS --max-time 30 -X POST \
    -H "Authorization: Bearer $API_KEY" \
    "http://${SVC}.${NS}.svc.cluster.local:${PORT}/v1/pipelines/reload" 2>&1) || true
# The reload endpoint may or may not exist depending on OWUI Pipelines
# version. If it doesn't, the next GET will tell us whether the new
# pipeline registered (most versions auto-discover files in the dir on
# any list call).

# Now GET /v1/pipelines and confirm each newly-installed pipeline is in
# the registered set.
LIST=$(kubectl -n "$NS" run owui-list-probe-$$ --rm -i --restart=Never --quiet \
    --image=curlimages/curl:8.10.1 -- \
    curl -sS --max-time 30 \
    -H "Authorization: Bearer $API_KEY" \
    "http://${SVC}.${NS}.svc.cluster.local:${PORT}/v1/pipelines" 2>&1)

# Parse the {"data":[{"id":"...","name":"...","type":"..."},...]} shape
# without requiring jq inside the pod (we have it locally though).
require jq
matches=""
for f in "${FILES[@]}"; do
    base=$(basename "$f" .py)
    line=$(echo "$LIST" | jq -r --arg id "$base" \
        '.data[]? | select(.id == $id) | "\(.id)|\(.name)|\(.type)"' 2>/dev/null | head -1)
    if [ -z "$line" ]; then
        log_info "WARNING: $base not yet visible in /v1/pipelines list. The pod may need a restart for the runtime to pick it up."
        log_info "  Run: kubectl -n $NS rollout restart deploy/owui-pipelines"
    else
        matches+="$line"$'\n'
    fi
done

if [ -z "$matches" ]; then
    err "none of the installed pipelines registered with the runtime. A pod restart is likely needed."
fi

echo "$matches" | sed '/^$/d' | while read -r row; do
    log_step 3 3 "verifying via /v1/pipelines" "$row"
done

echo "OK"
