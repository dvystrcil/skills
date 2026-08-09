#!/usr/bin/env bash
# Bootstrap Infisical CI secrets (INFISICAL_CLIENT_ID / INFISICAL_CLIENT_SECRET)
# for a new repo whose CI workflows need them.
#
# Usage:
#   bootstrap-infisical-ci.sh <owner/repo>
#   bootstrap-infisical-ci.sh <owner/repo> --check-only   # detect only, no
#                                                         # prompts, no writes
#
# Doesn't auto-create an Infisical machine identity and doesn't store
# credentials anywhere itself -- it's a thin wrapper around `gh secret set`
# plus the detection + idempotency checks that keep it from prompting when
# nothing needs to change.
#
# homelab#345 / feedback_new_repo_infisical_secrets: this is the tool that
# memory rule asked for -- the second time a repo's CI silently failed for
# days because nobody set these two secrets at creation time.
#
# Correction to homelab#345's original proposal: every homelab repo's CI
# uses the exact same Infisical project-slug (homelab-bz-gt), env-slug
# (prod), and in-cluster domain -- confirmed by grepping every workflow
# under ~/Code/*/.github/workflows/. There is ONE shared machine identity
# for CI across the whole fleet, not a new per-repo "<repo>-ci" identity
# as originally proposed. This script prompts for the two values directly
# (same ones used everywhere else) instead of asking whether a per-repo
# identity has been created -- that question doesn't apply.
#
# This file is designed to be `source`d for testing the pure detection
# logic (needs_infisical_text) without touching gh/network -- see
# tests/test_bootstrap_infisical_ci.sh. Guard below only runs the CLI
# when the script is executed directly.

set -euo pipefail

INFISICAL_IDENTITIES_URL="https://infisical.sirddail.net/org/identities"

# ---------------------------------------------------------------- pure core

# Does this text (one or more workflow files' content, concatenated) show
# a dependency on Infisical-sourced CI secrets? Pure function: no gh, no
# network, no filesystem -- just the two patterns every homelab workflow
# uses to pull secrets (Infisical/secrets-action step, or a bare
# secrets.INFISICAL_CLIENT_ID reference for repos wiring it by hand).
needs_infisical_text() {
  grep -qE 'secrets\.INFISICAL_CLIENT_ID|Infisical/secrets-action' <<<"$1"
}

# -------------------------------------------------------------- gh-backed IO

# Concatenated content of every file under .github/workflows/ in $1
# (owner/repo), fetched via the GitHub API -- works with no local clone,
# matching apply.sh/audit.sh's convention. Empty output (not an error) if
# the repo has no workflows dir at all.
fetch_workflow_content() {
  local repo="$1" f
  gh api "repos/$repo/contents/.github/workflows" --jq '.[].path' 2>/dev/null \
    | while IFS= read -r f; do
        gh api "repos/$repo/contents/$f" --jq '.content' 2>/dev/null \
          | base64 -d 2>/dev/null
        echo
      done
}

secret_names_set() {
  gh secret list --repo "$1" --json name --jq '.[].name' 2>/dev/null || true
}

# ------------------------------------------------------------------- CLI

run_cli() {
  local check_only=0
  local repo=""

  while [ "${1:-}" != "" ]; do
    case "$1" in
      --check-only) check_only=1 ;;
      --help|-h) echo "usage: $0 <owner/repo> [--check-only]"; return 0 ;;
      *) [ -z "$repo" ] && repo="$1" || { echo "unexpected arg: $1" >&2; return 2; } ;;
    esac
    shift
  done

  if [ -z "$repo" ]; then
    echo "usage: $0 <owner/repo> [--check-only]" >&2
    return 2
  fi

  echo "==> Checking $repo's workflows for an Infisical dependency"
  local content
  content=$(fetch_workflow_content "$repo")
  if ! needs_infisical_text "$content"; then
    echo "    no workflow references secrets.INFISICAL_CLIENT_ID or Infisical/secrets-action -- nothing to bootstrap"
    return 0
  fi
  echo "    FOUND: this repo's CI needs Infisical credentials"

  if [ "$check_only" = "1" ]; then
    echo "DETECTED"
    return 0
  fi

  local existing have_id=0 have_secret=0
  existing=$(secret_names_set "$repo")
  echo "$existing" | grep -qx "INFISICAL_CLIENT_ID" && have_id=1
  echo "$existing" | grep -qx "INFISICAL_CLIENT_SECRET" && have_secret=1

  if [ "$have_id" = "1" ] && [ "$have_secret" = "1" ]; then
    echo "    INFISICAL_CLIENT_ID and INFISICAL_CLIENT_SECRET already set -- nothing to do"
    return 0
  fi

  echo
  echo "$repo's CI needs the shared homelab CI machine identity's credentials"
  echo "(same INFISICAL_CLIENT_ID / INFISICAL_CLIENT_SECRET used by every other"
  echo "repo -- there is no per-repo identity to create). Have these values"
  echo "handy? (y/n)"
  read -r answer

  case "$answer" in
    n|N)
      echo "Opening the Infisical Identities page -- find the shared CI identity, copy its Client ID/Secret, then come back here."
      xdg-open "$INFISICAL_IDENTITIES_URL" >/dev/null 2>&1 \
        || echo "    (couldn't auto-open a browser -- go to $INFISICAL_IDENTITIES_URL manually)"
      echo "Press Enter once you have the values ready..."
      read -r _
      ;;
    y|Y) ;;
    *)
      echo "unrecognized answer '$answer' -- expected y/n" >&2
      return 2
      ;;
  esac

  if [ "$have_id" = "0" ]; then
    echo -n "INFISICAL_CLIENT_ID: "
    read -r client_id
    gh secret set INFISICAL_CLIENT_ID --repo "$repo" --body "$client_id"
  fi

  if [ "$have_secret" = "0" ]; then
    echo -n "INFISICAL_CLIENT_SECRET: "
    read -rs client_secret
    echo
    gh secret set INFISICAL_CLIENT_SECRET --repo "$repo" --body "$client_secret"
  fi

  echo "==> Verifying"
  secret_names_set "$repo" | grep -E "^INFISICAL_CLIENT_(ID|SECRET)$"
  echo "OK"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  run_cli "$@"
fi
