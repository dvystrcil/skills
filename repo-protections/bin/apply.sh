#!/usr/bin/env bash
# Apply the canonical repo protections to a GitHub repo.
#
# Usage:
#   apply.sh <owner/repo>                         # apply settings + branch protection
#   apply.sh <owner/repo> --create-codeowners     # ALSO open a PR adding .github/CODEOWNERS
#                                                 # if the repo doesn't have one
#
# This script is idempotent — re-running it is safe.
# Branch protection's `require_code_owner_reviews: true` has no teeth without a
# CODEOWNERS file; --create-codeowners closes that gap by opening a PR
# (not pushing direct to main, so we don't bypass the protection we just set up).
# LICENSE creation still belongs to the operator.

set -euo pipefail

create_codeowners=0
REPO=""

while [ "${1:-}" != "" ]; do
  case "$1" in
    --create-codeowners) create_codeowners=1 ;;
    --help|-h) echo "usage: $0 <owner/repo> [--create-codeowners]"; exit 0 ;;
    *) [ -z "$REPO" ] && REPO="$1" || { echo "unexpected arg: $1" >&2; exit 2; } ;;
  esac
  shift
done

if [ -z "$REPO" ]; then
  echo "usage: $0 <owner/repo> [--create-codeowners]" >&2
  exit 2
fi

echo "==> Applying canonical settings to $REPO"

# Confirm repo exists + grab default branch
meta=$(gh api "repos/$REPO")
default_branch=$(echo "$meta" | jq -r '.default_branch')
visibility=$(echo "$meta" | jq -r '.visibility')
owner=${REPO%%/*}

echo "    default branch: $default_branch  (visibility: $visibility)"

# Detect CD repos (image-updater writeback targets). Branch protection on
# these blocks the IU controller's `git push origin main` with GH006. We
# instead apply a Branch Ruleset that bypasses the IU GitHub App but still
# enforces PR review for humans. See feedback_cd_repos_must_not_be_branch_protected.
#
# IU_APP_ID env var overrides the default homelab IU app id (the argocd
# repo-creds secret labeled argocd.argoproj.io/secret-type=repo-creds).
IU_APP_ID="${IU_APP_ID:-378815}"
is_cd_repo=0
if gh api "repos/$REPO/contents/image-updater" >/dev/null 2>&1; then
  is_cd_repo=1
  echo "    DETECTED: image-updater/ directory — treating as CD repo (will use Ruleset, not Branch Protection)"
fi

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
# For CD repos: apply a Ruleset with IU app bypass (humans go through PRs,
# IU pushes directly). For non-CD repos: apply classic Branch Protection.
echo "==> Applying branch protection on '$default_branch'"
if [ "$is_cd_repo" = "1" ]; then
  # Conversion case: if this repo previously ran through apply.sh as a
  # non-CD repo (before the image-updater/ directory existed), classic
  # Branch Protection is still in place. Classic and Ruleset enforce in
  # parallel — classic has no per-actor bypass list, so IU's push still
  # gets rejected with GH006 even though the Ruleset bypass is correct.
  # Strip classic protection first so only the Ruleset (with IU bypass)
  # remains. Idempotent: 404 if already absent, swallow it.
  if gh api "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1; then
    echo "    STRIPPING stale classic Branch Protection (conflicts with Ruleset bypass)"
    gh api -X DELETE "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1 \
      || { echo "    FAILED to delete classic protection" >&2; exit 1; }
  fi

  # Rulesets are unavailable on private repos without GitHub Pro. Detect
  # via a probing list call — if it 403s, skip protection gracefully (same
  # as the classic Branch Protection skip below).
  if ! gh api "repos/$REPO/rulesets" >/dev/null 2>&1; then
    if [ "$visibility" = "private" ]; then
      echo "    SKIPPED — private repo without GitHub Pro can't use Rulesets (or Branch Protection)"
      echo
      echo "Done. Run audit.sh $REPO to confirm."
      exit 0
    else
      echo "    FAILED — could not list rulesets on a public repo (auth or network issue):" >&2
      gh api "repos/$REPO/rulesets" >&2 || true
      exit 1
    fi
  fi

  # Check if a ruleset already exists with the canonical name (idempotent).
  ruleset_name="main-protection-with-iu-bypass"
  existing_id=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$ruleset_name\") | .id" 2>/dev/null || echo "")

  ruleset_payload=$(jq -nc \
    --arg name "$ruleset_name" \
    --arg branch "$default_branch" \
    --argjson app_id "$IU_APP_ID" \
    '{
      name: $name,
      target: "branch",
      enforcement: "active",
      bypass_actors: [{actor_id: $app_id, actor_type: "Integration", bypass_mode: "always"}],
      conditions: {ref_name: {include: ["~DEFAULT_BRANCH"], exclude: []}},
      rules: [
        {type: "deletion"},
        {type: "non_fast_forward"},
        {type: "pull_request", parameters: {
          required_approving_review_count: 1,
          dismiss_stale_reviews_on_push: true,
          require_code_owner_review: true,
          require_last_push_approval: false,
          required_review_thread_resolution: false
        }}
      ]
    }')

  if [ -n "$existing_id" ]; then
    echo "    Ruleset '$ruleset_name' already exists (id=$existing_id); updating to match canonical shape"
    if echo "$ruleset_payload" | gh api -X PUT \
         -H "Accept: application/vnd.github+json" \
         "repos/$REPO/rulesets/$existing_id" \
         --input - >/dev/null 2>&1; then
      echo "    Ruleset updated (IU app id=$IU_APP_ID bypasses)"
    else
      echo "    FAILED to update ruleset" >&2
      exit 1
    fi
  else
    if echo "$ruleset_payload" | gh api -X POST \
         -H "Accept: application/vnd.github+json" \
         "repos/$REPO/rulesets" \
         --input - >/dev/null 2>&1; then
      echo "    Ruleset created (IU app id=$IU_APP_ID bypasses)"
    else
      echo "    FAILED to create ruleset:" >&2
      echo "$ruleset_payload" | gh api -X POST \
        -H "Accept: application/vnd.github+json" \
        "repos/$REPO/rulesets" \
        --input - >&2 || true
      exit 1
    fi
  fi

  echo
  echo "Done. Run audit.sh $REPO to confirm."
  exit 0
fi
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

# --- Optional: open a PR to add .github/CODEOWNERS ---
if [ "$create_codeowners" = "1" ]; then
  echo "==> CODEOWNERS check"
  if gh api "repos/$REPO/contents/.github/CODEOWNERS" >/dev/null 2>&1 \
       || gh api "repos/$REPO/contents/CODEOWNERS" >/dev/null 2>&1; then
    echo "    already present — skipping"
  else
    branch="chore/add-codeowners"
    msg="chore: add canonical CODEOWNERS (repo-protections)"
    # Content: comment header + one line. Standard shape across the homelab.
    content=$(printf '# Default code owner for this repository.\n# Required because branch protection requires code-owner review.\n* @%s\n' "$owner" | base64 -w0)

    # Contents API's `branch:` field requires the branch to ALREADY exist.
    # Create it via the Git Refs API, pointed at the default branch head.
    # If the branch already exists (prior partial run), the create returns
    # 422 — fine, swallow it and proceed to the PUT.
    head_sha=$(gh api "repos/$REPO/git/refs/heads/$default_branch" --jq '.object.sha')
    gh api -X POST "repos/$REPO/git/refs" \
      -f ref="refs/heads/$branch" \
      -f sha="$head_sha" >/dev/null 2>&1 || true

    body=$(jq -nc \
      --arg msg "$msg" \
      --arg content "$content" \
      --arg branch "$branch" \
      '{message: $msg, content: $content, branch: $branch}')
    echo "    creating .github/CODEOWNERS on branch '$branch'..."
    if echo "$body" | gh api -X PUT \
         -H "Accept: application/vnd.github+json" \
         "repos/$REPO/contents/.github/CODEOWNERS" \
         --input - >/dev/null 2>&1; then
      # Open PR if not already open from a prior partial run.
      existing=$(gh pr list --repo "$REPO" --head "$branch" --json number --jq '.[0].number' 2>/dev/null || echo "")
      if [ -z "$existing" ]; then
        gh pr create --repo "$REPO" --base "$default_branch" --head "$branch" \
          --title "$msg" \
          --body "Adds the canonical CODEOWNERS the homelab repo-protections skill expects. Required because branch protection's \`require_code_owner_reviews: true\` has no teeth without it.

Convention: \`* @${owner}\` — sole maintainer is the owner. Replace if/when the repo has multiple maintainers." >/dev/null
        echo "    PR opened"
      else
        echo "    PR #$existing already open for branch $branch"
      fi
    else
      echo "    ERROR — could not create file via Contents API"
    fi
  fi
fi

echo
echo "Done. Run audit.sh $REPO to confirm."
