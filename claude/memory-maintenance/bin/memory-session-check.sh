#!/usr/bin/env bash
# memory-session-check.sh — two lines for a SessionStart hook (homelab#1800).
# Report-only, always exits 0 (never blocks a session):
#   * index headroom per project; WARN under ${HEADROOM_WARN:-3000} chars, FAIL if truncated
#   * age of the last successful memory-backup.sh snapshot; WARN over 24h
#     (only when BACKUP_ENABLED=1 in the per-machine backup.env)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${CLAUDE_MEMORY_BACKUP_ENV:-$HOME/.config/claude-memory/backup.env}"
STAMP="${XDG_STATE_HOME:-$HOME/.local/state}/claude-memory/last-backup"
WARN="${HEADROOM_WARN:-3000}"

echo "## Memory index + backup"
python3 "$HERE/check-memory-index.py" 2>&1 | awk -v warn="$WARN" '
  /^\// { path=$1; sub(/:$/,"",path) }
  /loader drops/ { print "  FAIL  " path ": " $0; next }
  /headroom:/ { h=$2+0; printf "  %s  %s: %d chars headroom\n", (h<warn?"WARN":"ok  "), path, h }
  /^ERROR/ { print "  FAIL  " $0 }'

BACKUP_ENABLED=0
# shellcheck source=/dev/null
[[ -f "$ENV_FILE" ]] && { set -a; . "$ENV_FILE"; set +a; }
if [[ "$BACKUP_ENABLED" != 1 ]]; then
  echo "  ok    backup disabled on this machine (local git history only)"
elif [[ ! -s "$STAMP" ]]; then
  echo "  WARN  backup enabled but no successful snapshot recorded ($STAMP)"
else
  age_h=$(( ( $(date +%s) - $(date -d "$(cat "$STAMP")" +%s) ) / 3600 ))
  if (( age_h > 24 )); then echo "  WARN  last memory snapshot ${age_h}h ago ($(cat "$STAMP"))"
  else echo "  ok    last memory snapshot ${age_h}h ago"; fi
fi
exit 0
