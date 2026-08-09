#!/usr/bin/env bash
# Hermetic tests for bootstrap-infisical-ci.sh's pure detection logic
# (needs_infisical_text) -- homelab#345. No gh, no network, no filesystem:
# sources the script (which guards its CLI behind a
# BASH_SOURCE-vs-0 check) and calls the pure function directly with
# literal fixture strings.
#
# Run: bash tests/test_bootstrap_infisical_ci.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/../repo-protections/bin/bootstrap-infisical-ci.sh"

fail=0
assert_true() {
  local desc="$1"; shift
  if "$@"; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc"
    fail=1
  fi
}
assert_false() {
  local desc="$1"; shift
  if "$@"; then
    echo "FAIL - $desc (expected false, got true)"
    fail=1
  else
    echo "ok - $desc"
  fi
}

assert_true "detects Infisical/secrets-action step" \
  needs_infisical_text '
jobs:
  build:
    steps:
      - uses: Infisical/secrets-action@v1.0.16
        with:
          client-id: ${{ secrets.INFISICAL_CLIENT_ID }}
'

assert_true "detects a bare secrets.INFISICAL_CLIENT_ID reference" \
  needs_infisical_text '
env:
  ID: ${{ secrets.INFISICAL_CLIENT_ID }}
'

assert_false "unrelated workflow content is not a match" \
  needs_infisical_text '
jobs:
  build:
    steps:
      - uses: actions/checkout@v7
      - run: npm test
'

assert_false "empty content is not a match" \
  needs_infisical_text ''

assert_true "matches across multiple concatenated files (one references, one does not)" \
  needs_infisical_text '
name: lint
on: [pull_request]
---
name: deploy
env:
  X: ${{ secrets.INFISICAL_CLIENT_ID }}
'

if [ "$fail" = "1" ]; then
  echo "FAILED"
  exit 1
fi
echo "ALL PASS"
