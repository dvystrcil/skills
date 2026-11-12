#!/usr/bin/env bash
# Apply the canonical repo protections to a GitHub repo.
#
# Usage:
#   apply.sh <owner/repo>                         # apply settings + branch protection
#   apply.sh <owner/repo> --create-codeowners     # ALSO open a PR adding .github/CODEOWNERS
#                                                 # if the repo doesn't have one
#   apply.sh <owner/repo> --dry-run               # print the planned Ruleset, write nothing
#   apply.sh <owner/repo> --replace-hand-made     # fold a hand-made Ruleset into main-protection:
#                                                 # create main-protection, THEN delete the hand-made one
#
# This script is idempotent — re-running it is safe.
# Branch protection's `require_code_owner_reviews: true` has no teeth without a
# CODEOWNERS file; --create-codeowners closes that gap by opening a PR
# (not pushing direct to main, so we don't bypass the protection we just set up).
# LICENSE creation still belongs to the operator.

set -euo pipefail

create_codeowners=0
dry_run=0
replace_hand_made=0
REPO=""

while [ "${1:-}" != "" ]; do
  case "$1" in
    --create-codeowners) create_codeowners=1 ;;
    --dry-run) dry_run=1 ;;
    --replace-hand-made) replace_hand_made=1 ;;
    --help|-h) echo "usage: $0 <owner/repo> [--create-codeowners] [--dry-run] [--replace-hand-made]"; exit 0 ;;
    *) [ -z "$REPO" ] && REPO="$1" || { echo "unexpected arg: $1" >&2; exit 2; } ;;
  esac
  shift
done

if [ -z "$REPO" ]; then
  echo "usage: $0 <owner/repo> [--create-codeowners] [--dry-run] [--replace-hand-made]" >&2
  exit 2
fi

# shellcheck source=solo-ruleset.sh
. "$(dirname "${BASH_SOURCE[0]}")/solo-ruleset.sh"

# The account has been on GitHub Pro since 2026-11-10, so protection is
# available on private repos too. A 403 "Upgrade to GitHub Pro" is no longer
# an expected "n/a" -- it means the plan lapsed, and that is a failure.
pro_lapsed_hint() {
  echo "    (a 403 'Upgrade to GitHub Pro' on a private repo means the account's"
  echo "     GitHub Pro plan lapsed -- private-repo protection depends on it)"
}

echo "==> Applying canonical settings to $REPO"

# Confirm repo exists + grab default branch
meta=$(gh api "repos/$REPO")
default_branch=$(echo "$meta" | jq -r '.default_branch')
visibility=$(echo "$meta" | jq -r '.visibility')
is_fork=$(echo "$meta" | jq -r '.fork')
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
#
# CD-ness comes from IU_WRITEBACK_REPOS (solo-ruleset.sh), not from an
# image-updater/ directory -- see the comment there.
is_cd_repo=0
if is_iu_writeback_repo "$REPO"; then
  is_cd_repo=1
  echo "    CD repo (in IU_WRITEBACK_REPOS): IU-bypass Ruleset"
fi

# --- Repo-level settings ---
if [ "$dry_run" = "1" ]; then
  echo "==> DRY RUN: repo settings not touched"
else
echo "==> Updating repo settings"
gh api -X PATCH "repos/$REPO" \
  -F allow_merge_commit=false \
  -F allow_squash_merge=true \
  -F allow_rebase_merge=true \
  -F allow_auto_merge=false \
  -F delete_branch_on_merge=true \
  -F has_issues=true >/dev/null
fi

# --- Branch protection on default branch ---
# For CD repos: apply a Ruleset with IU app bypass (humans go through PRs,
# IU pushes directly). For non-CD repos: apply classic Branch Protection.
echo "==> Applying branch protection on '$default_branch'"
if [ "$is_cd_repo" = "1" ]; then
  if [ "$dry_run" = "1" ]; then
    echo "    DRY RUN: CD repo -- would apply the IU-bypass Ruleset (see the CD path); nothing written"
    exit 0
  fi
  # Any failure to list Rulesets is a failure, private or not. The account
  # has been on GitHub Pro since 2026-11-10; before that a private repo's 403
  # was "SKIPPED" with exit 0, and every private CD repo stayed unprotected
  # while this script reported success. A 403 now means the plan lapsed.
  if ! gh api "repos/$REPO/rulesets" >/dev/null 2>&1; then
    echo "    FAILED — could not list rulesets ($visibility repo):" >&2
    gh api "repos/$REPO/rulesets" >&2 || true
    pro_lapsed_hint >&2
    exit 1
  fi

  # Find the IU Ruleset to update (idempotent): the canonical name, or else
  # any Ruleset that already lists the IU App as a bypass actor -- one made by
  # hand under another name (open-webui and n8n-workflow use "main") must be
  # updated in place, not shadowed by a second Ruleset.
  ruleset_name="main-protection-with-iu-bypass"
  existing_id=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$ruleset_name\") | .id" 2>/dev/null || echo "")
  if [ -z "$existing_id" ]; then
    for rid in $(gh api "repos/$REPO/rulesets" --jq '.[].id' 2>/dev/null); do
      if gh api "repos/$REPO/rulesets/$rid" 2>/dev/null \
           | jq -e --argjson app "$IU_APP_ID" \
               'any(.bypass_actors[]?; .actor_type=="Integration" and .actor_id==$app)' >/dev/null; then
        existing_id="$rid"; break
      fi
    done
  fi

  # The solo CD Ruleset (owner decision 2026-11-10, after GitHub Pro): the IU
  # App is the ONLY bypass actor, and 0 approvals. The old shape required 1
  # approval with Repository admin (`always`) and the CICD App as bypass
  # actors; on a solo account every merge went through the admin bypass, and
  # `always` let the owner's credential -- every agent session -- push
  # straight to main. With 0 approvals the owner merges normally and the
  # auto-merge gate's plain merge succeeds (homelab D-037 tries it first), so
  # neither bypass is needed.
  ruleset_payload=$(jq -nc \
    --arg name "$ruleset_name" \
    --argjson app_id "$IU_APP_ID" \
    '{
      name: $name,
      target: "branch",
      enforcement: "active",
      bypass_actors: [
        {actor_id: $app_id, actor_type: "Integration", bypass_mode: "always"}
      ],
      conditions: {ref_name: {include: ["~DEFAULT_BRANCH"], exclude: []}},
      rules: [
        {type: "deletion"},
        {type: "non_fast_forward"},
        {type: "pull_request", parameters: {
          required_approving_review_count: 0,
          dismiss_stale_reviews_on_push: false,
          require_code_owner_review: false,
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

  # Conversion case: if this repo previously ran through apply.sh as a
  # non-CD repo (before the image-updater/ directory existed), classic
  # Branch Protection is still in place. Classic and Ruleset enforce in
  # parallel — classic has no per-actor bypass list, so IU's push still
  # gets rejected with GH006 even though the Ruleset bypass is correct.
  # Strip it so only the Ruleset (with IU bypass) remains -- AFTER the
  # Ruleset exists: stripped first, a failed create left main unprotected.
  if gh api "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1; then
    echo "    STRIPPING stale classic Branch Protection (conflicts with Ruleset bypass)"
    gh api -X DELETE "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1 \
      || { echo "    FAILED to delete classic protection" >&2; exit 1; }
  fi

  echo
  echo "Done. Run audit.sh $REPO to confirm."
  exit 0
fi
# A repo may already be protected by a Ruleset even though it isn't a CD
# repo by the image-updater/ heuristic — anything written to by automation
# (an hourly canary, a backup agent, a post-merge codegen job) is set up
# that way, because only Rulesets can bypass a specific actor. Layering
# classic Branch Protection on top does NOT add safety: the two enforce in
# parallel, classic has no bypass list, and the bypassed actor starts
# failing with GH006.
#
# Burned 2026-08-10: a fleet-wide apply run put classic protection on
# dvystrcil/homelab-heartbeat (Ruleset bypassing the n8n App), skills
# (Ruleset bypassing the Actions App that regenerates a ConfigMap) and
# neptune-4pro-klipper-backup (printer pushing config backups). The
# heartbeat canary stopped at the next hourly tick.
#
# Read the STATUS, not the body (skills#77, same bug audit.sh had): on error
# `gh api` still prints the error JSON to stdout, so a 403 "Upgrade to GitHub
# Pro" body used to be reported as a Ruleset name. A success is a JSON array;
# anything else is a failure. Every failure fails CLOSED -- including the
# private-repo "Upgrade to GitHub Pro" 403, which used to be reported as
# "n/a" with exit 0 (the account is on Pro since 2026-11-10; see
# pro_lapsed_hint).
existing_ruleset=""
if rulesets_json=$(gh api "repos/$REPO/rulesets" 2>/dev/null) \
   && echo "$rulesets_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
  existing_ruleset=$(echo "$rulesets_json" \
    | jq -r '[.[] | select(.enforcement=="active") | .name] | join(", ")')
else
  echo "    FAILED to list rulesets for $REPO — refusing to guess protection state:" >&2
  echo "    ${rulesets_json:-<no output>}" >&2
  pro_lapsed_hint >&2
  exit 1
fi

# --- Non-CD, non-fork (private AND public): the solo Ruleset (solo-ruleset.sh) ---
# Public repos moved too (owner decision 2026-11-11). Forks keep classic: a
# PR-required Ruleset with no bypass blocks GitHub's "Sync fork", which
# fast-forwards the default branch directly.
if [ "$is_fork" != "true" ]; then
  bad_apps=$(unexemptable_apps "$REPO")
  if [ -n "$bad_apps" ]; then
    echo "    FAILED -- DIRECT_PUSH_APPS lists App $bad_apps (GitHub Actions), which GitHub" >&2
    echo "    rejects as a bypass actor on a user-owned repo. Make that bot push as an App." >&2
    exit 1
  fi
  solo_id=$(echo "$rulesets_json" | jq -r --arg n "$SOLO_RULESET_NAME" '[.[] | select(.name==$n) | .id][0] // empty')
  others=$(echo "$rulesets_json" \
    | jq -r --arg n "$SOLO_RULESET_NAME" '[.[] | select(.enforcement=="active" and .name!=$n) | .name] | join(", ")')
  replace_ids=""
  if [ -z "$solo_id" ] && [ -n "$others" ]; then
    # Don't stack a second, bypass-less Ruleset on top of a hand-made one: an
    # actor bypassing Ruleset A is still blocked by Ruleset B. Replace it, and
    # only on request -- its bypass actors must be in DIRECT_PUSH_APPS first.
    if [ -n "${HAND_MADE_RULESETS[$REPO]:-}" ]; then
      [ "$replace_hand_made" = 1 ] && {
        echo "    FAILED -- $REPO keeps its hand-made Ruleset ($others): ${HAND_MADE_RULESETS[$REPO]}" >&2
        exit 1
      }
      echo "    SKIPPED -- hand-made Ruleset(s) $others kept: ${HAND_MADE_RULESETS[$REPO]}"
      echo
      echo "Done. Run audit.sh $REPO to confirm."
      exit 0
    fi
    if [ "$replace_hand_made" != 1 ]; then
      echo "    SKIPPED -- already protected by Ruleset(s): $others (hand-made)"
      echo "    Put its bot bypass actors in DIRECT_PUSH_APPS, then re-run with --replace-hand-made."
      echo
      echo "Done. Run audit.sh $REPO to confirm."
      exit 0
    fi
    # Only a Ruleset covering exactly the default branch may go: one that also
    # covers other branches or tags protects more than main-protection will.
    for rid in $(echo "$rulesets_json" | jq -r --arg n "$SOLO_RULESET_NAME" '.[] | select(.enforcement=="active" and .name!=$n) | .id'); do
      rs=$(gh api "repos/$REPO/rulesets/$rid") \
        || { echo "    FAILED to read Ruleset $rid -- refusing to replace it" >&2; exit 1; }
      if ! echo "$rs" | jq -e --arg b "refs/heads/$default_branch" '
           .target == "branch"
           and ((.conditions.ref_name.include // []) | length > 0)
           and all(.conditions.ref_name.include[]; . == "~DEFAULT_BRANCH" or . == $b)' >/dev/null; then
        echo "    FAILED -- Ruleset $rid ($(echo "$rs" | jq -r .name)) covers more than $default_branch" \
             "(target $(echo "$rs" | jq -r .target), include $(echo "$rs" | jq -c .conditions.ref_name.include));" \
             "fold it by hand" >&2
        exit 1
      fi
      replace_ids="$replace_ids $rid"
    done
  fi
  checks=$(derive_required_checks "$REPO") \
    || { echo "    FAILED to read merged PRs' check-runs -- refusing to guess required checks" >&2; exit 1; }
  apps=$(direct_push_apps "$REPO")
  payload=$(solo_ruleset_payload "$apps" "$checks")
  echo "    solo Ruleset '$SOLO_RULESET_NAME': required checks $checks, bypass Apps $apps"
  if [ "$dry_run" = "1" ]; then
    echo "$payload" | jq .
    for rid in $replace_ids; do echo "    would delete hand-made Ruleset $rid after creating '$SOLO_RULESET_NAME'"; done
    echo "    DRY RUN: nothing written"
    exit 0
  fi
  if [ -n "$solo_id" ]; then
    method=PUT; path="repos/$REPO/rulesets/$solo_id"; verb=updated
  else
    method=POST; path="repos/$REPO/rulesets"; verb=created
  fi
  if echo "$payload" | gh api -X "$method" -H "Accept: application/vnd.github+json" "$path" --input - >/dev/null 2>&1; then
    echo "    Ruleset $verb"
  else
    echo "    FAILED ($method $path):" >&2
    echo "$payload" | gh api -X "$method" -H "Accept: application/vnd.github+json" "$path" --input - >&2 || true
    exit 1
  fi
  # Classic protection enforces in parallel with the Ruleset and has no
  # bypass list (a listed App would still be rejected with GH006), and its
  # enforce_admins:false is the hole this Ruleset closes. Strip it -- only
  # AFTER the Ruleset exists: stripped first, a failed create left main
  # with no protection at all.
  if gh api "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1; then
    echo "    STRIPPING classic Branch Protection (replaced by the Ruleset)"
    gh api -X DELETE "repos/$REPO/branches/$default_branch/protection" >/dev/null 2>&1 \
      || { echo "    FAILED to delete classic protection" >&2; exit 1; }
  fi
  # The hand-made Ruleset goes last, once main-protection exists.
  for rid in $replace_ids; do
    gh api -X DELETE "repos/$REPO/rulesets/$rid" >/dev/null 2>&1 \
      || { echo "    FAILED to delete hand-made Ruleset $rid (main-protection is in place)" >&2; exit 1; }
    echo "    DELETED hand-made Ruleset $rid"
  done
  echo
  echo "Done. Run audit.sh $REPO to confirm."
  exit 0
fi

if [ -n "$existing_ruleset" ]; then
  echo "    SKIPPED classic protection — already protected by Ruleset(s): $existing_ruleset"
  echo "    (classic would enforce in parallel with no bypass list and break any bypassed actor)"
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
  echo "    FAILED — re-running with verbose output:" >&2
  echo "$protection_payload" | gh api -X PUT \
    -H "Accept: application/vnd.github+json" \
    "repos/$REPO/branches/$default_branch/protection" \
    --input - >&2 || true
  pro_lapsed_hint >&2
  exit 1
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
