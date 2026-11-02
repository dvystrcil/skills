#!/usr/bin/env bash
# Hermetic tests for claude/memory-maintenance/bin/memory-backup.sh
# (homelab#1800 AC1/AC7). Scratch $HOME + CLAUDE_CONFIG_DIR, no network.
#
# What is pinned is the failure modes that would read as "backed up" when
# it was not, or that would break the hybrid's one guarantee (no remote):
#   * a memory dir with a git remote must be refused, not committed+pushed
#   * BACKUP_ENABLED=0 (the work-machine default) must never call restic
#   * the success stamp is written only after restic actually succeeded
#   * an over-budget index is reported (exit !=0) but still backed up —
#     durability first, the gate is a report
#
# The restic leg uses a LOCAL repo and runs only when restic is installed;
# it says SKIP explicitly otherwise, so a green run without restic is not
# mistaken for a tested backup.
#
# Run: bash tests/test_memory_backup.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../claude/memory-maintenance/bin/memory-backup.sh"

fail=0
ok()   { echo "ok - $1"; }
bad()  { echo "FAIL - $1"; fail=1; }

setup() {
  T=$(mktemp -d)
  export HOME="$T/home" CLAUDE_CONFIG_DIR="$T/home/.claude"
  export XDG_STATE_HOME="$T/state"
  mkdir -p "$CLAUDE_CONFIG_DIR/projects/-proj/memory" "$HOME/.config/claude-memory"
  MEM="$CLAUDE_CONFIG_DIR/projects/-proj/memory"
  printf -- '- [a](a.md) — hook\n' > "$MEM/MEMORY.md"
  printf -- '---\nname: a\n---\nbody\n' > "$MEM/a.md"
  export CLAUDE_MEMORY_BACKUP_ENV="$HOME/.config/claude-memory/backup.env"
  export GIT_CONFIG_GLOBAL="$T/gitconfig"; : > "$GIT_CONFIG_GLOBAL"
  STAMP="$XDG_STATE_HOME/claude-memory/last-backup"
}

# --- 1. disabled backup: commits locally, never touches restic --------------
setup
printf 'BACKUP_ENABLED=0\n' > "$CLAUDE_MEMORY_BACKUP_ENV"
fakebin="$T/bin"; mkdir -p "$fakebin"
printf '#!/bin/sh\necho called > "%s/restic-called"\nexit 0\n' "$T" > "$fakebin/restic"
chmod +x "$fakebin/restic"
PATH="$fakebin:$PATH" bash "$SCRIPT" >"$T/out" 2>&1; rc=$?
[ "$rc" = 0 ] && ok "disabled: exit 0" || { bad "disabled: exit $rc"; cat "$T/out"; }
[ -d "$MEM/.git" ] && ok "disabled: local git initialised" || bad "disabled: no .git"
[ "$(git -C "$MEM" rev-list --count HEAD 2>/dev/null)" = 1 ] && ok "disabled: one commit" || bad "disabled: commit count"
[ ! -e "$T/restic-called" ] && ok "disabled: restic never called" || bad "disabled: restic was called"
[ ! -e "$STAMP" ] && ok "disabled: no success stamp" || bad "disabled: stamp written without a backup"

# second run with no changes: no empty commit
PATH="$fakebin:$PATH" bash "$SCRIPT" >/dev/null 2>&1
[ "$(git -C "$MEM" rev-list --count HEAD)" = 1 ] && ok "no change: no new commit" || bad "no change: made an empty commit"
echo more >> "$MEM/a.md"
PATH="$fakebin:$PATH" bash "$SCRIPT" >/dev/null 2>&1
[ "$(git -C "$MEM" rev-list --count HEAD)" = 2 ] && ok "change: committed" || bad "change: not committed"

# --- 2. a remote is refused --------------------------------------------------
git -C "$MEM" remote add origin https://example.invalid/x.git
echo again >> "$MEM/a.md"
PATH="$fakebin:$PATH" bash "$SCRIPT" >"$T/out" 2>&1; rc=$?
[ "$rc" != 0 ] && ok "remote: non-zero exit" || bad "remote: exit 0"
grep -qi 'remote' "$T/out" && ok "remote: says why" || bad "remote: silent"
[ "$(git -C "$MEM" rev-list --count HEAD)" = 2 ] && ok "remote: did not commit" || bad "remote: committed anyway"

# --- 3. restic failure: no stamp ---------------------------------------------
setup
printf 'BACKUP_ENABLED=1\nRESTIC_REPOSITORY=/nonexistent\nRESTIC_PASSWORD_FILE=/nonexistent\n' > "$CLAUDE_MEMORY_BACKUP_ENV"
printf '#!/bin/sh\nexit 1\n' > "$T/restic-fail"; mkdir -p "$T/fb"; mv "$T/restic-fail" "$T/fb/restic"; chmod +x "$T/fb/restic"
PATH="$T/fb:$PATH" bash "$SCRIPT" >"$T/out" 2>&1; rc=$?
[ "$rc" != 0 ] && ok "restic fails: non-zero exit" || bad "restic fails: exit 0"
[ ! -e "$STAMP" ] && ok "restic fails: no success stamp" || bad "restic fails: stamp written"

# --- 4. real restic, local repo ----------------------------------------------
if command -v restic >/dev/null 2>&1; then
  setup
  printf 'pw-for-test\n' > "$T/pass"; chmod 600 "$T/pass"
  RESTIC_PASSWORD_FILE="$T/pass" restic init -q -r "$T/repo" >/dev/null 2>&1
  printf 'BACKUP_ENABLED=1\nRESTIC_REPOSITORY=%s\nRESTIC_PASSWORD_FILE=%s\n' "$T/repo" "$T/pass" > "$CLAUDE_MEMORY_BACKUP_ENV"
  bash "$SCRIPT" >"$T/out" 2>&1; rc=$?
  [ "$rc" = 0 ] && ok "restic: exit 0" || { bad "restic: exit $rc"; cat "$T/out"; }
  n=$(RESTIC_PASSWORD_FILE="$T/pass" restic -r "$T/repo" snapshots --json 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')
  [ "$n" = 1 ] && ok "restic: one snapshot" || bad "restic: $n snapshots"
  # capture first: `restic ls | grep -q` SIGPIPEs restic and pipefail reads it as a miss
  listing=$(RESTIC_PASSWORD_FILE="$T/pass" restic -r "$T/repo" ls latest 2>/dev/null)
  grep -q '/memory/\.git/HEAD$' <<< "$listing" \
    && ok "restic: .git included" || bad "restic: .git missing from snapshot"
  [ -s "$STAMP" ] && ok "restic: success stamp written" || bad "restic: no stamp"

  # over-budget index: reported, still backed up
  python3 -c "print('\n'.join('- [e%d](e%d.md) — '%(i,i)+'x'*150 for i in range(233)))" > "$MEM/MEMORY.md"
  bash "$SCRIPT" >"$T/out" 2>&1; rc=$?
  [ "$rc" != 0 ] && ok "over budget: non-zero exit" || bad "over budget: exit 0"
  grep -q 'loader drops' "$T/out" && ok "over budget: says where it cuts" || bad "over budget: no cut-off line"
  n=$(RESTIC_PASSWORD_FILE="$T/pass" restic -r "$T/repo" snapshots --json 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')
  [ "$n" = 2 ] && ok "over budget: still backed up" || bad "over budget: not backed up ($n)"
else
  echo "SKIP - restic not installed: the real-restic leg (4) did NOT run"
fi

# --- 5. session check: report-only, always exit 0 ---------------------------
CHECK="$HERE/../claude/memory-maintenance/bin/memory-session-check.sh"
setup
printf 'BACKUP_ENABLED=1\n' > "$CLAUDE_MEMORY_BACKUP_ENV"
out=$(bash "$CHECK" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "session: exit 0" || bad "session: exit $rc"
grep -q 'WARN  backup enabled but no successful snapshot' <<< "$out" && ok "session: no stamp warns" || bad "session: no stamp silent"
grep -q 'ok  .*chars headroom' <<< "$out" && ok "session: small index ok" || bad "session: headroom line missing"
mkdir -p "$(dirname "$STAMP")"; date -Is > "$STAMP"
grep -q 'ok    last memory snapshot 0h ago' <<< "$(bash "$CHECK")" && ok "session: fresh stamp ok" || bad "session: fresh stamp"
date -Is -d '-30 hours' > "$STAMP"
grep -q 'WARN  last memory snapshot 30h ago' <<< "$(bash "$CHECK")" && ok "session: stale stamp warns" || bad "session: stale stamp"
python3 -c "print('\n'.join('- [e%d](e%d.md) — '%(i,i)+'x'*150 for i in range(233)))" > "$MEM/MEMORY.md"
grep -q 'FAIL .*loader drops' <<< "$(bash "$CHECK")" && ok "session: truncation is FAIL" || bad "session: truncation not flagged"
printf 'BACKUP_ENABLED=0\n' > "$CLAUDE_MEMORY_BACKUP_ENV"
grep -q 'backup disabled on this machine' <<< "$(bash "$CHECK")" && ok "session: disabled says so" || bad "session: disabled"

exit $fail
