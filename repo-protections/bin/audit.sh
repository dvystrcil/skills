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

  # A fork of SOMEONE ELSE'S repo is exempt from license, default-branch
  # and CODEOWNERS; a fork of one of our own repos is not. Compare the
  # parent's owner against this repo's owner rather than hardcoding a
  # username, so the script stays portable.
  local parent_owner our_owner third_party_fork=0
  parent_owner=$(echo "$meta" | jq -r '.parent.owner.login // ""')
  our_owner="${repo%%/*}"
  if [ "$fork" = "true" ] && [ -n "$parent_owner" ] && [ "$parent_owner" != "$our_owner" ]; then
    third_party_fork=1
  fi

  # A MACHINE-MANAGED repo cannot be made to comply by opening a PR, because
  # its contents are written by something that is not a person. Adding LICENSE,
  # README.md or .github/CODEOWNERS through GitHub is undone the next time the
  # machine pushes; the file has to be placed on the machine itself, in the
  # directory the tool backs up.
  #
  # Marked by the `machine-managed` TOPIC rather than a file in the repo, for
  # the obvious reason: a marker file would be overwritten by the very process
  # it describes. Topics are repo metadata and survive any push.
  #
  # The live case is a Klipper printer config backup: every commit reads
  # "New Backup on boot - ...", and the only human-authored thing about it is
  # the decision to have it. Flagging it forever produces a permanent failure
  # nobody can act on, and a check that can only fail is a check nobody reads.
  local machine_managed=0
  if echo "$meta" | jq -e '.topics // [] | index("machine-managed")' >/dev/null 2>&1; then
    machine_managed=1
  fi

  check "visibility (informational)" "$vis"     "$vis"

  if [ "$machine_managed" = "1" ]; then
    printf "  \033[33m·\033[0m %-32s contents written by a machine — license/README/CODEOWNERS\n" "machine-managed"
    printf "  %-34s must be placed on the device, not via PR\n" ""
  elif [ "$fork" = "true" ]; then
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
  if [ "$machine_managed" = "1" ]; then
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "license file"
  elif gh api "repos/$repo/license" >/dev/null 2>&1; then
    check "license file"             "present"  "present"
  else
    check "license file"             "missing"  "present"
  fi

  # Required files. CD repos still need CODEOWNERS — the Ruleset's
  # require_code_owner_review rule depends on it.
  #
  # Third-party forks are the exception: we don't write our review
  # governance into a vendor's tree, and a file upstream doesn't have is
  # friction on every merge from upstream. Without CODEOWNERS the
  # require_code_owner_reviews rule is vacuous (no path has an owner), so
  # the 1-approval requirement still holds.
  local required_files="README.md .github/CODEOWNERS"
  if [ "$machine_managed" = "1" ]; then
    required_files=""
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "file: README.md"
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "file: .github/CODEOWNERS"
  elif [ "$third_party_fork" = "1" ]; then
    required_files="README.md"
    printf "  \033[33m·\033[0m %-32s exempt (third-party fork)\n" "file: .github/CODEOWNERS"
  fi
  for path in $required_files; do
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
      local admin_bypass
      admin_bypass=$(echo "$ruleset" | jq -r '.bypass_actors[] | select(.actor_type=="RepositoryRole" and .actor_id==5) | .actor_id' | head -1)
      check "Ruleset enforcement"   "$enforcement" "active"
      if [ -n "$bypass" ]; then
        printf "  \033[32m✓\033[0m %-32s app id=%s\n" "Ruleset IU bypass" "$bypass"
      else
        check "Ruleset IU bypass" "missing" "present"
      fi
      # Solo operator can't merge own PRs without an admin bypass (the
      # review requirement is otherwise unsatisfiable). See apply.sh.
      if [ -n "$admin_bypass" ]; then
        printf "  \033[32m✓\033[0m %-32s role id=5\n" "Ruleset admin bypass"
      else
        check "Ruleset admin bypass" "missing" "present"
      fi
    fi
  elif [ -z "$prot" ] || echo "$prot" | grep -q '"message"'; then
    # No classic protection — but a Ruleset is equally valid protection,
    # and for any repo written to by automation it is the ONLY valid one,
    # since only Rulesets can bypass a specific actor. Counting solely
    # classic protection here reports correctly-protected repos as
    # unprotected, which is how a real Ruleset gets "fixed" by stacking
    # classic on top of it — see the apply.sh guard added alongside this.
    # Read the STATUS, not the body. `gh api` prints an error payload to
    # stdout and exits non-zero, and `--jq` then fails and passes the raw JSON
    # through -- so on a 403 this variable held
    #   {"message":"Upgrade to GitHub Pro ...","status":"403"}
    # which is non-empty, so the branch below reported
    #   ✓ branch protection  via Ruleset: {"message":"Upgrade to GitHub Pro...
    # Every private repo in the fleet read as PROTECTED while GitHub was
    # saying the feature is unavailable on this plan. A protection audit that
    # fails OPEN is worse than no audit: it answers the one question it exists
    # to answer, wrongly, and confidently.
    #
    # `|| echo ""` did not save it, because gh had already written the body.
    # The guard has to be an explicit success check plus a type check -- a
    # successful response is a JSON ARRAY; an error is an object.
    local active_rulesets rulesets_json
    active_rulesets=""
    if rulesets_json=$(gh api "repos/$repo/rulesets" 2>/dev/null) \
       && echo "$rulesets_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
      active_rulesets=$(echo "$rulesets_json" \
        | jq -r '[.[] | select(.enforcement=="active") | .name] | join(", ")')
    fi
    if [ -n "$active_rulesets" ]; then
      printf "  \033[32m✓\033[0m %-32s via Ruleset: %s\n" "branch protection" "$active_rulesets"
    elif [ "$vis" = "private" ]; then
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
