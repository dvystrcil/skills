#!/usr/bin/env bash
# Apply the canonical repo protections to a GitHub repo.
#
# Usage:  apply.sh <owner/repo>
#
# This script is idempotent — re-running it is safe.
# It does NOT create LICENSE / CODEOWNERS files (those require commits, which
# the user may want to control). Run audit.sh first to see what's missing.

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "usage: $0 <owner/repo>" >&2
  exit 2
fi
REPO="$1"

echo "==> Applying canonical settings to $REPO"

# Confirm repo exists + grab default branch
meta=$(gh api "repos/$REPO")
default_branch=$(echo "$meta" | jq -r '.default_branch')
visibility=$(echo "$meta" | jq -r '.visibility')

echo "    default branch: $default_branch  (visibility: $visibility)"

# --- Repo-level settings ---
echo "==> Updating repo settings"
gh api -X PATCH "repos/$REPO" \
  -F allow_merge_commit=false \
  -F allow_squash_merge=true \
  -F allow_rebase_merge=true \
  -F allow_auto_merge=false \
  -F delete_branch_on_merge=true \
  -F has_issues=true >/dev/null

# --- Branch protection on default branch ---
# Only works on public repos (or private + GitHub Pro). Detect and skip gracefully.
echo "==> Applying branch protection on '$default_branch'"
protection_payload=$(cat <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
)

if echo "$protection_payload" | gh api -X PUT \
     -H "Accept: application/vnd.github+json" \
     "repos/$REPO/branches/$default_branch/protection" \
     --input - >/dev/null 2>&1; then
  echo "    protection applied"
else
  if [ "$visibility" = "private" ]; then
    echo "    SKIPPED — private repo without GitHub Pro can't use branch protection"
  else
    echo "    FAILED — re-running with verbose output:" >&2
    echo "$protection_payload" | gh api -X PUT \
      -H "Accept: application/vnd.github+json" \
      "repos/$REPO/branches/$default_branch/protection" \
      --input - >&2 || true
    exit 1
  fi
fi

echo
echo "Done. Run audit.sh $REPO to confirm."
