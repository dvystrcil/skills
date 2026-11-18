#!/usr/bin/env bash
# wait-pr-checks.sh OWNER/REPO#N [OWNER/REPO#N ...]
#
# Wait for each PR's CI to finish, then print EVERY check row and a verdict
# line, and exit 0 only if every PR passed. One command, no pipe after
# `gh pr checks`: the pr-checks-pipe-guard hook stays quiet, and no failing
# row can be cut off (vt350#156).
#
# For each PR:
#   1. wait until its checks have registered (a fresh push shows none for a
#      while, and `gh pr checks --watch` gives up at once when there are none)
#   2. block on `gh pr checks --watch` (no output, no polling turns)
#   3. print `gh pr checks` in full, then `== OWNER/REPO#N rc=<code>`
#
# Exit: 0 all passed, 1 any failed / pending / never registered, 2 bad usage.
# Env: WAIT_PR_CHECKS_REGISTER  seconds to wait for checks to appear (300)
#      WAIT_PR_CHECKS_POLL      seconds between those looks (10)
#
# Run it in a background shell; you are notified when it exits.
set -uo pipefail

if [ $# -eq 0 ]; then
  echo "usage: $(basename "$0") OWNER/REPO#N [OWNER/REPO#N ...]" >&2
  exit 2
fi
for a in "$@"; do
  [[ "$a" =~ ^[^/#[:space:]]+/[^/#[:space:]]+#[0-9]+$ ]] || { echo "bad PR '$a': want OWNER/REPO#N" >&2; exit 2; }
done

register=${WAIT_PR_CHECKS_REGISTER:-300}
poll=${WAIT_PR_CHECKS_POLL:-10}
overall=0

for a in "$@"; do
  repo="${a%#*}"; n="${a##*#}"
  waited=0
  while :; do
    count="$(gh pr view "$n" -R "$repo" --json statusCheckRollup -q '.statusCheckRollup | length' 2>/dev/null)"
    [ "${count:-0}" -gt 0 ] 2>/dev/null && break
    if [ "$waited" -ge "$register" ]; then
      echo "== $a: no checks registered after ${register}s"
      overall=1
      continue 2
    fi
    sleep "$poll"; waited=$((waited + poll))
  done
  gh pr checks "$n" -R "$repo" --watch >/dev/null 2>&1
  echo "== $a"
  gh pr checks "$n" -R "$repo"
  rc=$?
  echo "== $a rc=$rc (0 passed, 1 failed, 8 pending)"
  [ "$rc" -eq 0 ] || overall=1
done
exit "$overall"
