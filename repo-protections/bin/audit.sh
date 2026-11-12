#!/usr/bin/env bash
# Audit a GitHub repo (or every non-archived repo owned by $OWNER) against the
# canonical convention defined in this skill.
#
# Usage:
#   audit.sh <owner/repo>           # audit one repo
#   audit.sh --all                  # audit every non-archived repo (public + private)
#
# Exit code: 0 if everything matches the convention, 1 if any drift.

set -euo pipefail

OWNER="${OWNER:-dvystrcil}"

# shellcheck source=solo-ruleset.sh
. "$(dirname "${BASH_SOURCE[0]}")/solo-ruleset.sh"

fail=0

# need <label> <got> <want>: check() on public repos. On private ones a miss
# is printed as a note and does NOT fail the audit. Owner decision
# 2026-11-11: LICENSE and README are for people who can read the repo; on 50
# private deploy repos they kept `--all` red for a reason nobody meant to fix.
# Uses audit_one's $vis (bash dynamic scope).
need() {
  if [ "${vis:-}" = public ] || [ "$2" = "$3" ]; then check "$@"; return; fi
  printf "  \033[33m·\033[0m %-32s %s (want=%s on public repos only)\n" "$1" "$2" "$3"
}

check() {
  local label="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then
    printf "  \033[32m✓\033[0m %-32s %s\n" "$label" "$got"
  else
    printf "  \033[31m✗\033[0m %-32s got=%s want=%s\n" "$label" "$got" "$want"
    fail=1
  fi
}

# homelab D-037 (#1225): the auto-merge gate merges bot PRs through the CICD
# App's Ruleset bypass. In `pull_request` mode it can merge past review and
# nothing else. Wider (`always`, `exempt`) would also hand it force-push and
# branch deletion.
IU_APP_ID="${IU_APP_ID:-378815}"
CICD_APP_ID="${CICD_APP_ID:-3693085}"

# iu_bypass_id <ruleset-json>: the IU App's actor id if it is a bypass actor.
# Matched BY ID: "the first Integration" was satisfied by any App at all.
iu_bypass_id() {
  echo "$1" | jq -r --argjson id "$IU_APP_ID" \
    '[.bypass_actors[]? | select(.actor_type=="Integration" and .actor_id==$id) | .actor_id][0] // empty'
}

# Repos where the CICD App pushes to main DIRECTLY, by design, and so needs
# `always` (pull_request mode can't push). Each entry names its reason.
#   dvystrcil/skills  rebuild-configmap.yml commits the regenerated ConfigMap
declare -A CICD_DIRECT_PUSH_REPOS=(
  [dvystrcil/skills]="rebuild-configmap.yml pushes the regenerated ConfigMap to main"
)

# cicd_bypass_verdict <ruleset-json> <required 1|0> [owner/repo]: ok | missing | too-wide.
# CD repos' canonical Ruleset requires it; elsewhere it is opt-in, and never
# wider than pull_request unless the repo is in CICD_DIRECT_PUSH_REPOS.
cicd_bypass_verdict() {
  local mode
  mode=$(echo "$1" | jq -r --argjson id "$CICD_APP_ID" \
    '[.bypass_actors[]? | select(.actor_type=="Integration" and .actor_id==$id) | .bypass_mode][0] // "none"')
  case "$mode" in
    pull_request) echo ok ;;
    none) if [ "$2" = 1 ]; then echo missing; else echo ok; fi ;;
    *) if [ -n "${3:-}" ] && [ -n "${CICD_DIRECT_PUSH_REPOS[$3]:-}" ]; then echo ok; else echo too-wide; fi ;;
  esac
}

# codeowners_required <owner/repo> <branch>: 1 if classic protection or an
# active Ruleset on <branch> requires code-owner review, else 0.
codeowners_required() {
  local prot rid
  if prot=$(gh api "repos/$1/branches/$2/protection" 2>/dev/null) \
     && [ "$(echo "$prot" | jq -r '.required_pull_request_reviews.require_code_owner_reviews // false')" = true ]; then
    echo 1; return
  fi
  for rid in $(gh api "repos/$1/rulesets" --jq '.[] | select(.enforcement=="active") | .id' 2>/dev/null); do
    if gh api "repos/$1/rulesets/$rid" 2>/dev/null \
         | jq -e 'any(.rules[]?; .type=="pull_request" and (.parameters.require_code_owner_review // false))' >/dev/null; then
      echo 1; return
    fi
  done
  echo 0
}

# Repos whose license is deliberately NOT MIT. The audit wants exactly the
# listed SPDX id there -- a drift away from it is still a ✗. Each entry names
# the decision that made it.
declare -A LICENSE_EXCEPTIONS=(
  # GPL-3.0-or-later for our own work; vendored/remixed third-party parts are
  # GPL-3.0 or CC BY-NC-SA. Owner decision, vt350#122 phase 1 (vt350#130),
  # kept on 2026-11-11.
  [dvystrcil/vt350]="GPL-3.0"
  # NONE = deliberately no license yet. An OrcaSlicer derivative: its own
  # docs/licensing-and-provenance.md blocks a top-level LICENSE until the
  # third-party inventory is done (AGPL-3.0-only is only the provisional
  # candidate). When a LICENSE lands this goes ✗ -- update it here.
  [dvystrcil/quality-first-slicer]="NONE"
)
# Tests: LICENSE_EXCEPTIONS_OVERRIDE='owner/repo=SPDX'
if [ -n "${LICENSE_EXCEPTIONS_OVERRIDE:-}" ]; then
  LICENSE_EXCEPTIONS[${LICENSE_EXCEPTIONS_OVERRIDE%%=*}]="${LICENSE_EXCEPTIONS_OVERRIDE#*=}"
fi

# writers_verdict <owner/repo>: "owner only", or the other logins that can
# merge -- collaborators with push, plus pending invites for write and above
# (one click from being a writer). "error" if either API call fails: an audit
# that reads a failed call as "nobody else" fails OPEN.
#
# Owner decision 2026-11-11: every Ruleset here requires 0 approvals, so ANY
# writer can merge their own PR -- on homelab or argocd-projects, straight to
# production. Removing the collaborators closed that; this keeps it closed.
writers_verdict() {
  local repo="$1" owner="${1%%/*}" c i
  c=$(gh api "repos/$repo/collaborators?per_page=100" \
        --jq "[.[] | select(.login != \"$owner\" and .permissions.push) | .login]" 2>/dev/null) \
    || { echo "error"; return; }
  i=$(gh api "repos/$repo/invitations?per_page=100" \
        --jq '[.[] | select(.permissions != "read" and .permissions != "triage") | .invitee.login + " (invited)"]' 2>/dev/null) \
    || { echo "error"; return; }
  jq -nr --argjson c "$c" --argjson i "$i" \
    '($c + $i) | if length == 0 then "owner only" else join(", ") end' 2>/dev/null || echo "error"
}

# audit_solo <owner/repo> <classic-protection-json-or-empty>: non-CD repos
# carry the solo Ruleset (solo-ruleset.sh). A hand-made Ruleset under another
# name passes only when HAND_MADE_RULESETS records why; anywhere else it is ✗
# (`apply.sh --replace-hand-made` folds it in).
# no_classic <classic-protection-json-or-empty>: ✗ when classic protection
# is present -- beside any Ruleset it enforces in parallel.
no_classic() {
  if [ -n "$1" ] && ! echo "$1" | grep -q '"message"'; then
    check "no classic protection" "present" "absent"
  fi
}

audit_solo() {
  local repo="$1" prot="$2" rulesets_json solo_id others ruleset
  if ! rulesets_json=$(gh api "repos/$repo/rulesets" 2>/dev/null) \
     || ! echo "$rulesets_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
    check "Ruleset $SOLO_RULESET_NAME — fetch error" "error" "ok"
    return
  fi
  solo_id=$(echo "$rulesets_json" | jq -r --arg n "$SOLO_RULESET_NAME" '[.[] | select(.name==$n) | .id][0] // empty')
  others=$(echo "$rulesets_json" | jq -r --arg n "$SOLO_RULESET_NAME" \
    '[.[] | select(.enforcement=="active" and .name!=$n) | .name] | join(", ")')
  if [ -z "$solo_id" ] && [ -n "$others" ] && [ -z "${HAND_MADE_RULESETS[$repo]:-}" ]; then
    check "Ruleset $SOLO_RULESET_NAME" "absent (hand-made: $others)" "present"
    no_classic "$prot"
    return
  fi
  if [ -z "$solo_id" ] && [ -n "$others" ]; then
    printf "  \033[33m·\033[0m %-32s hand-made Ruleset: %s (exception: %s)\n" "branch protection" "$others" "${HAND_MADE_RULESETS[$repo]}"
    local rid
    for rid in $(echo "$rulesets_json" | jq -r '.[] | select(.enforcement=="active") | .id'); do
      check "Ruleset $rid CICD bypass" \
        "$(cicd_bypass_verdict "$(gh api "repos/$repo/rulesets/$rid" 2>/dev/null || echo '{}')" 0 "$repo")" "ok"
    done
    # A hand-made Ruleset doesn't excuse classic protection beside it: classic
    # with enforce_admins:false lets the owner's credential push straight to
    # main (flatpak-repo, obico-docker, pihole-lists until 2026-11-11).
    no_classic "$prot"
    return
  fi
  if [ -z "$solo_id" ]; then
    check "Ruleset $SOLO_RULESET_NAME" "absent" "present"
    return
  fi
  ruleset=$(gh api "repos/$repo/rulesets/$solo_id" 2>/dev/null || echo '{}')
  check "Ruleset enforcement" "$(echo "$ruleset" | jq -r '.enforcement')" "active"
  check "Ruleset required approvals" \
    "$(echo "$ruleset" | jq -r '[.rules[]? | select(.type=="pull_request") | .parameters.required_approving_review_count][0] // "none"')" "0"
  # No role/admin bypass at all; App bypasses exactly the DIRECT_PUSH_APPS
  # list -- an extra one is a hole, a missing one breaks that bot's pushes.
  check "Ruleset admin/role bypass" \
    "$(echo "$ruleset" | jq -r '[.bypass_actors[]? | select(.actor_type!="Integration")] | if length>0 then "present" else "absent" end')" "absent"
  check "Ruleset bypass Apps" \
    "$(echo "$ruleset" | jq -c '[.bypass_actors[]? | select(.actor_type=="Integration") | .actor_id] | sort')" \
    "$(direct_push_apps "$repo")"
  no_classic "$prot"
  printf "  \033[33m·\033[0m %-32s %s\n" "required checks" \
    "$(echo "$ruleset" | jq -c '[.rules[]? | select(.type=="required_status_checks") | .parameters.required_status_checks[].context]')"
}

audit_one() {
  local repo="$1"
  echo
  echo "=== $repo ==="

  local meta
  meta=$(gh api "repos/$repo" 2>/dev/null) || { echo "  not accessible"; fail=1; return; }

  # Detect CD repos (image-updater writeback targets) — branch protection
  # there blocks the IU controller's git push. See feedback_cd_repos_must_not_be_branch_protected.
  # CD-ness comes from IU_WRITEBACK_REPOS (solo-ruleset.sh), not from an
  # image-updater/ directory -- see the comment there.
  local is_cd_repo=0
  if is_iu_writeback_repo "$repo"; then
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
        need "license"               "$lic"     "MIT"
      fi
    elif [ -n "${LICENSE_EXCEPTIONS[$repo]:-}" ]; then
      if [ "$lic" = "${LICENSE_EXCEPTIONS[$repo]}" ]; then
        printf "  \033[32m✓\033[0m %-32s %s (recorded exception)\n" "license" "$lic"
      else
        need "license"               "$lic"     "${LICENSE_EXCEPTIONS[$repo]}"
      fi
    else
      need "license"                 "$lic"     "MIT"
    fi
  fi
  check "allow_merge_commit"         "$merge"   "false"
  check "allow_squash_merge"         "$sq"      "true"
  check "allow_rebase_merge"         "$rb"      "true"
  check "delete_branch_on_merge"     "$del"     "true"
  check "allow_auto_merge"           "$autom"   "false"
  check "has_issues"                 "$issues"  "true"
  check "writers"                    "$(writers_verdict "$repo")" "owner only"

  # LICENSE: detect via license API (handles LICENSE / LICENSE.md / LICENSE.txt).
  if [ "$machine_managed" = "1" ]; then
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "license file"
  else
    local lf=missing want_lf=present
    gh api "repos/$repo/license" >/dev/null 2>&1 && lf=present
    [ "${LICENSE_EXCEPTIONS[$repo]:-}" = NONE ] && want_lf=missing
    if [ "$want_lf" = missing ] && [ "$lf" = missing ]; then
      printf "  \033[32m✓\033[0m %-32s %s\n" "license file" "absent (recorded exception: no license yet)"
    else
      need "license file"            "$lf"      "$want_lf"
    fi
  fi

  # Required files. CD repos still need CODEOWNERS — the Ruleset's
  # require_code_owner_review rule depends on it.
  #
  # Third-party forks are the exception: we don't write our review
  # governance into a vendor's tree, and a file upstream doesn't have is
  # friction on every merge from upstream. Without CODEOWNERS the
  # require_code_owner_reviews rule is vacuous (no path has an owner), so
  # the 1-approval requirement still holds.
  # CODEOWNERS is required only where a rule requires code-owner review
  # (classic protection or a Ruleset with require_code_owner_review).
  # Anywhere else it is DRIFT: since GitHub Pro (2026-11-10) code owners work
  # on private repos too, and `* @owner` auto-requests the owner's review on
  # every PR -- bot PRs included -- while gating nothing (the solo Rulesets
  # require 0 approvals). cluster-ops#1049 was the first such email.
  local required_files="README.md" codeowners_policy="absent"
  if [ "$machine_managed" = "1" ]; then
    required_files=""; codeowners_policy="exempt"
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "file: README.md"
    printf "  \033[33m·\033[0m %-32s exempt (machine-managed)\n" "file: .github/CODEOWNERS"
  elif [ "$third_party_fork" = "1" ]; then
    codeowners_policy="exempt"
    printf "  \033[33m·\033[0m %-32s exempt (third-party fork)\n" "file: .github/CODEOWNERS"
  elif [ "$(codeowners_required "$repo" "$def")" = 1 ]; then
    codeowners_policy="present"
  fi
  for path in $required_files; do
    if gh api "repos/$repo/contents/$path" >/dev/null 2>&1; then
      check "file: $path"            "present"  "present"
    else
      need "file: $path"             "missing"  "present"
    fi
  done
  if [ "$codeowners_policy" != "exempt" ]; then
    local have_owners="missing"
    gh api "repos/$repo/contents/.github/CODEOWNERS" >/dev/null 2>&1 && have_owners="present"
    if [ "$codeowners_policy" = "absent" ] && [ "$have_owners" = "missing" ]; then
      printf "  \033[32m✓\033[0m %-32s %s\n" "file: .github/CODEOWNERS" "absent (no rule requires code-owner review)"
    else
      check "file: .github/CODEOWNERS" "$have_owners" "$codeowners_policy"
    fi
  fi

  # Branch protection / Ruleset.
  # Non-CD repos: classic Branch Protection on default branch.
  # CD repos: Ruleset with IU app bypass (humans go through PRs, IU pushes directly).
  local prot
  prot=$(gh api "repos/$repo/branches/$def/protection" 2>/dev/null || echo "")
  if [ "$is_cd_repo" = "1" ]; then
    # A failed Ruleset fetch is drift on any repo. Before the account moved
    # to GitHub Pro (2026-11-10) a private repo's 403 was printed as "n/a",
    # so private CD repos passed while unprotected. A 403 now = Pro lapsed.
    if ! gh api "repos/$repo/rulesets" >/dev/null 2>&1; then
      check "Ruleset (IU bypass) — fetch error ($vis)" "error" "ok"
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
    # The CD Ruleset: canonical name, or else any Ruleset listing the IU App
    # as a bypass actor (a hand-made one may be called "main").
    local ruleset_id rid
    ruleset_id=$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name=="main-protection-with-iu-bypass") | .id' 2>/dev/null || echo "")
    if [ -z "$ruleset_id" ]; then
      for rid in $(gh api "repos/$repo/rulesets" --jq '.[].id' 2>/dev/null); do
        if [ -n "$(iu_bypass_id "$(gh api "repos/$repo/rulesets/$rid" 2>/dev/null || echo '{}')")" ]; then
          ruleset_id="$rid"; break
        fi
      done
    fi
    if [ -z "$ruleset_id" ]; then
      check "Ruleset (IU bypass)" "absent" "present"
    else
      # The solo CD shape (owner decision 2026-11-10, see apply.sh): the IU
      # App is the ONLY bypass actor, 0 approvals. An admin bypass lets the
      # owner's credential (every agent session) push straight to main; a
      # CICD bypass has nothing left to bypass at 0 approvals.
      local ruleset enforcement bypass approvals admin_bypass cicd_bypass
      ruleset=$(gh api "repos/$repo/rulesets/$ruleset_id" 2>/dev/null)
      enforcement=$(echo "$ruleset" | jq -r '.enforcement')
      bypass=$(iu_bypass_id "$ruleset")
      approvals=$(echo "$ruleset" | jq -r '[.rules[]? | select(.type=="pull_request") | .parameters.required_approving_review_count][0] // "none"')
      admin_bypass=$(echo "$ruleset" | jq -r '[.bypass_actors[]? | select(.actor_type=="RepositoryRole" or .actor_type=="OrganizationAdmin")] | if length>0 then "present" else "absent" end')
      cicd_bypass=$(echo "$ruleset" | jq -r --argjson c "$CICD_APP_ID" '[.bypass_actors[]? | select(.actor_type=="Integration" and .actor_id==$c)] | if length>0 then "present" else "absent" end')
      check "Ruleset enforcement"   "$enforcement" "active"
      if [ -n "$bypass" ]; then
        printf "  \033[32m✓\033[0m %-32s app id=%s\n" "Ruleset IU bypass" "$bypass"
      else
        check "Ruleset IU bypass" "missing" "present"
      fi
      check "Ruleset required approvals" "$approvals"    "0"
      check "Ruleset admin bypass"       "$admin_bypass" "absent"
      check "Ruleset CICD bypass"        "$cicd_bypass"  "absent"
    fi
  elif [ "$fork" != "true" ]; then
    # Private and public alike (public since 2026-11-11). Forks keep classic.
    audit_solo "$repo" "$prot"
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
      # The CICD bypass is opt-in here, but never wider than pull_request.
      local rid
      for rid in $(echo "$rulesets_json" | jq -r '.[] | select(.enforcement=="active") | .id'); do
        check "Ruleset $rid CICD bypass" \
          "$(cicd_bypass_verdict "$(gh api "repos/$repo/rulesets/$rid" 2>/dev/null || echo '{}')" 0 "$repo")" "ok"
      done
    else
      # Private repos included: since GitHub Pro (2026-11-10) "private" is
      # no excuse, and a 403 here (Pro lapsed) is the same drift.
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

# Sourced (tests): define the functions above and stop.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi

if [ "${1:-}" = "--all" ]; then
  # Every non-archived repo, private included (GitHub Pro since 2026-11-10).
  # Archived repos are read-only: nothing on them can drift or be fixed.
  mapfile -t repos < <(gh repo list "$OWNER" --no-archived --limit 1000 --json nameWithOwner --jq '.[].nameWithOwner')
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
