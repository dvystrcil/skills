#!/usr/bin/env bash
# memory-backup.sh — hourly job for Claude Code auto-memory (homelab#1800).
#
#   1. local-only git: commit any change in each memory dir (init if needed).
#      A memory dir with a git REMOTE is refused — no remote is the whole
#      point (one writer, nothing to diverge from, nothing pushed in clear).
#   2. index gate: check-memory-index.py on each MEMORY.md. Reported, never
#      blocks the backup — durability first.
#   3. gitleaks (if installed): memory must never hold a credential.
#   4. restic snapshot of the dirs (.git included) + retention, ONLY when
#      BACKUP_ENABLED=1. Success stamp written only after restic succeeds.
#
# Per-machine config, never in a repo:
#   ${CLAUDE_MEMORY_BACKUP_ENV:-~/.config/claude-memory/backup.env}
#     BACKUP_ENABLED=0|1        # default 0 — the work-machine setting
#     MEMORY_DIR=...            # optional; default = every projects/*/memory
#     RESTIC_REPOSITORY=...     # e.g. sftp:host-alias:/path/repo
#     RESTIC_PASSWORD_FILE=...  # never the password itself, never argv
#
# Exit 0 only when every step that ran succeeded.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${CLAUDE_MEMORY_BACKUP_ENV:-$HOME/.config/claude-memory/backup.env}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-memory"
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

BACKUP_ENABLED=0
MEMORY_DIR=""
if [[ -f "$ENV_FILE" ]]; then
  set -a; # shellcheck source=/dev/null
  . "$ENV_FILE"; set +a
fi

rc=0
log() { echo "[memory-backup] $*"; }

if [[ -n "$MEMORY_DIR" ]]; then
  dirs=("$MEMORY_DIR")
else
  dirs=()
  for m in "$CLAUDE_HOME"/projects/*/memory/MEMORY.md; do
    [[ -f "$m" ]] && dirs+=("$(dirname "$m")")
  done
fi
if [[ ${#dirs[@]} -eq 0 ]]; then
  log "no memory dir found under $CLAUDE_HOME — nothing to back up"
  exit 2
fi

# --- 1. local-only git ---------------------------------------------------------
good_dirs=()
for d in "${dirs[@]}"; do
  if [[ ! -d "$d/.git" ]]; then
    git -C "$d" init -q -b main || { log "FAIL git init $d"; rc=1; continue; }
  fi
  if [[ -n "$(git -C "$d" remote)" ]]; then
    log "FAIL $d has a git remote ($(git -C "$d" remote | tr '\n' ' ')) — memory history is local-only; remove the remote"
    rc=1
    continue
  fi
  git -C "$d" add -A -- . >/dev/null 2>&1
  if ! git -C "$d" diff --cached --quiet; then
    n=$(git -C "$d" diff --cached --name-only | wc -l)
    git -C "$d" -c user.name="${GIT_AUTHOR_NAME:-claude-memory-backup}" \
        -c user.email="${GIT_AUTHOR_EMAIL:-claude-memory-backup@localhost}" \
        -c commit.gpgsign=false \
        commit -q --no-verify -m "auto: $n file(s) $(date -Is)" \
      || { log "FAIL commit in $d"; rc=1; }
    log "committed $n file(s) in $d"
  fi
  good_dirs+=("$d")
done

# --- 2. index gate (report only) -----------------------------------------------
for d in "${good_dirs[@]}"; do
  if ! python3 "$HERE/check-memory-index.py" "$d/MEMORY.md"; then
    log "index gate FAILED for $d — compact it (memory-maintenance skill); backing up anyway"
    rc=1
  fi
done

# --- 3. secrets ----------------------------------------------------------------
# Missing gitleaks is SAID, not skipped: under systemd, brew's bin is not on
# PATH and the scan vanished without a word (2026-11-02). Add the dir to PATH
# in backup.env.
if command -v gitleaks >/dev/null 2>&1; then
  for d in "${good_dirs[@]}"; do
    if ! gitleaks dir "$d" --no-banner --redact --log-level error >/dev/null 2>&1; then
      log "gitleaks found a possible credential in $d — remove it from memory"
      rc=1
    fi
  done
else
  log "WARN gitleaks not found on PATH — secrets scan did NOT run (PATH=$PATH)"
fi

# --- 4. restic -----------------------------------------------------------------
if [[ "$BACKUP_ENABLED" != 1 ]]; then
  log "BACKUP_ENABLED=$BACKUP_ENABLED — local history only, no snapshot"
  exit $rc
fi
if [[ ${#good_dirs[@]} -eq 0 ]]; then
  log "no dir passed the git step — nothing to snapshot"
  exit 1
fi
if ! command -v restic >/dev/null 2>&1; then
  log "FAIL restic not found on PATH — no snapshot (PATH=$PATH; extend PATH in $ENV_FILE)"
  exit 1
fi

if restic backup -q --tag claude-memory --host "$(hostname)" "${good_dirs[@]}" &&
   restic forget -q --tag claude-memory --host "$(hostname)" \
       --keep-hourly 48 --keep-daily 30 --keep-weekly 26 --keep-monthly 24 --prune; then
  mkdir -p "$STATE_DIR"
  date -Is > "$STATE_DIR/last-backup"
  log "snapshot ok -> $RESTIC_REPOSITORY"
else
  log "FAIL restic backup/forget — no new snapshot"
  rc=1
fi
exit $rc
