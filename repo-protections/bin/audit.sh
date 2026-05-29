#!/usr/bin/env bash
# Audit a GitHub repo (or all public repos in the dvystrcil org) against the
# canonical convention defined in this skill.
#
# Usage:
#   audit.sh <owner/repo>           # audit one repo
#   audit.sh --all                  # audit every public repo owned by $OWNER
#
# Exit code: 0 if everything matches the convention, 1 if any drift.

set -euo pipefail

OWNER="${OWNER:-dvystrcil}"

fail=0

check() {
  local label="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then
    printf "  \033[32m✓\033[0m %-32s %s\n" "$label" "$got"
  else
    printf "  \033[31m✗\033[0m %-32s got=%s want=%s\n" "$label" "$got" "$want"
    fail=1
  fi
}

audit_one() {
  local repo="$1"
  echo
  echo "=== $repo ==="

  local meta
  meta=$(gh api "repos/$repo" 2>/dev/null) || { echo "  not accessible"; fail=1; return; }

  # Detect CD repos (image-updater writeback targets) — branch protection
  # there blocks the IU controller's git push. See feedback_cd_repos_must_not_be_branch_protected.
  local is_cd_repo=0
  if gh api "repos/$repo/contents/image-updater" >/dev/null 2>&1; then
    is_cd_repo=1
  fi

  local vis lic merge sq rb del def autom issues fork parent
  vis=$(echo "$meta" | jq -r '.visibility')
  lic=$(echo "$meta" | jq -r '.license.spdx_id // "NONE"')
  merge=$(echo "$meta" | jq -r '.allow_merge_commit')
  sq=$(echo "$meta"   | jq -r '.allow_squash_merge')
  rb=$(echo "$meta"   | jq -r '.allow_rebase_merge')
  del=$(echo "$meta"  | jq -r '.delete_branch_on_merge')
  def=$(echo "$meta"  | jq -r '.default_branch')
  autom=$(echo "$meta" | jq -r '.allow_auto_merge')
  issues=$(echo "$meta" | jq -r '.has_issues')
  fork=$(echo "$meta" | jq -r '.fork')
  parent=$(echo "$meta" | jq -r '.parent.full_name // ""')

  check "visibility (informational)" "$vis"     "$vis"

  if [ "$fork" = "true" ]; then
    printf "  \033[33m·\033[0m %-32s fork of %s — license/default-branch tracked upstream\n" "fork status" "$parent"
  else
    check "default branch"           "$def"     "main"

    # License detection. NOASSERTION usually means the LICENSE file contains
    # canonical license text PLUS extra content (e.g., a multi-license
    # umbrella). Check for a sibling docs-license file before flagging.
    if [ "$lic" = "NOASSERTION" ]; then
      docs_lic=""
      for candidate in LICENSE-docs.md LICENSE-DOCS.md LICENSE-CODE.md LICENSE-prose.md; do
        if gh api "repos/$repo/contents/$candidate" >/dev/null 2>&1; then
          docs_lic="$candidate"; break
        fi
      done
      if [ -n "$docs_lic" ]; then
        printf "  \033[33m·\033[0m %-32s multi-license (umbrella + %s) — intentional\n" "license" "$docs_lic"
      else
        check "license"               "$lic"     "MIT"
      fi
    else
      check "license"                 "$lic"     "MIT"
    fi
  fi
  check "allow_merge_commit"         "$merge"   "false"
  check "allow_squash_merge"         "$sq"      "true"
  check "allow_rebase_merge"         "$rb"      "true"
  check "delete_branch_on_merge"     "$del"     "true"
  check "allow_auto_merge"           "$autom"   "false"
  check "has_issues"                 "$issues"  "true"

  # LICENSE: detect via license API (handles LICENSE / LICENSE.md / LICENSE.txt).
  if gh api "repos/$repo/license" >/dev/null 2>&1; then
    check "license file"             "present"  "present"
  else
    check "license file"             "missing"  "present"
  fi

  # Required files. CD repos still need CODEOWNERS — the Ruleset's
  # require_code_owner_review rule depends on it.
  for path in README.md .github/CODEOWNERS; do
    if gh api "repos/$repo/contents/$path" >/dev/null 2>&1; then
      check "file: $path"            "present"  "present"
    else
      check "file: $path"            "missing"  "present"
    fi
  done

  # Branch protection / Ruleset.
  # Non-CD repos: classic Branch Protection on default branch.
  # CD repos: Ruleset with IU app bypass (humans go through PRs, IU pushes directly).
  local prot
  prot=$(gh api "repos/$repo/branches/$def/protection" 2>/dev/null || echo "")
  if [ "$is_cd_repo" = "1" ]; then
    # Rulesets aren't available on private repos without GitHub Pro.
    # Probe the list endpoint; if 403, mark as n/a (informational, not drift).
    if ! gh api "repos/$repo/rulesets" >/dev/null 2>&1; then
      if [ "$vis" = "private" ]; then
        printf "  \033[33m·\033[0m %-32s n/a (private CD repo, no Pro)\n" "Ruleset (IU bypass)"
      else
        check "Ruleset (IU bypass) — fetch error" "error" "ok"
      fi
      echo
      return
    fi
    # CD repos must NOT have classic Branch Protection: it enforces
    # alongside the Ruleset and has no per-actor bypass list, so IU's
    # `git push` fails with GH006 even when the Ruleset bypass is correct.
    # See feedback_cd_repos_must_not_be_branch_protected (conversion gap).
    if [ -n "$prot" ] && ! echo "$prot" | grep -q '"message"'; then
      check "no classic protection (CD)" "present" "absent"
    else
      printf "  \033[32m✓\033[0m %-32s %s\n" "no classic protection (CD)" "absent"
    fi
    # Check for canonical Ruleset on CD repos
    local ruleset_id
    ruleset_id=$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name=="main-protection-with-iu-bypass") | .id' 2>/dev/null || echo "")
    if [ -z "$ruleset_id" ]; then
      check "Ruleset (IU bypass)" "absent" "present"
    else
      # Verify the bypass actor includes the IU app
      local ruleset
      ruleset=$(gh api "repos/$repo/rulesets/$ruleset_id" 2>/dev/null)
      local enforcement bypass
      enforcement=$(echo "$ruleset" | jq -r '.enforcement')
      bypass=$(echo "$ruleset" | jq -r '.bypass_actors[] | select(.actor_type=="Integration") | .actor_id' | head -1)
      check "Ruleset enforcement"   "$enforcement" "active"
      if [ -n "$bypass" ]; then
        printf "  \033[32m✓\033[0m %-32s app id=%s\n" "Ruleset IU bypass" "$bypass"
      else
        check "Ruleset IU bypass" "missing" "present"
      fi
    fi
  elif [ -z "$prot" ] || echo "$prot" | grep -q '"message"'; then
    if [ "$vis" = "private" ]; then
      printf "  \033[33m·\033[0m %-32s n/a (private repo, no Pro)\n" "branch protection"
    else
      check "branch protection" "absent" "present"
    fi
  else
    local rev fp del2 codeowner stale
    rev=$(echo       "$prot" | jq -r '.required_pull_request_reviews.required_approving_review_count // 0')
    fp=$(echo        "$prot" | jq -r '.allow_force_pushes.enabled')
    del2=$(echo      "$prot" | jq -r '.allow_deletions.enabled')
    codeowner=$(echo "$prot" | jq -r '.required_pull_request_reviews.require_code_owner_reviews // false')
    stale=$(echo     "$prot" | jq -r '.required_pull_request_reviews.dismiss_stale_reviews // false')

    check "required reviews"         "$rev"       "1"
    check "block force pushes"       "$fp"        "false"
    check "block deletions"          "$del2"      "false"
    check "require code-owner review" "$codeowner" "true"
    check "dismiss stale reviews"    "$stale"     "true"
  fi
}

if [ "${1:-}" = "--all" ]; then
  mapfile -t repos < <(gh repo list "$OWNER" --visibility public --limit 100 --json nameWithOwner --jq '.[].nameWithOwner')
  for r in "${repos[@]}"; do audit_one "$r"; done
elif [ -n "${1:-}" ]; then
  audit_one "$1"
else
  echo "usage: $0 <owner/repo> | --all" >&2
  exit 2
fi

echo
if [ $fail -eq 0 ]; then
  echo "Result: all checks passed."
else
  echo "Result: drift detected. Run apply.sh to fix."
fi
exit $fail
