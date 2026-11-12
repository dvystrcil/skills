#!/usr/bin/env bash
# iu-targets.sh -- diff IU_WRITEBACK_REPOS (solo-ruleset.sh) against the repos
# argocd-image-updater actually pushes to: every
# writeBackConfig.gitConfig.repository with method git, at the top of an
# ImageUpdater spec or on any of its applicationRefs. Needs kubectl on the
# cluster that runs IU.
#
# Exit 0 only when the two match exactly. A live target missing from the list
# gets the solo Ruleset (no IU bypass) from apply.sh and every image update to
# it fails with GH013; a listed repo that is no longer a target keeps an
# IU bypass it doesn't need. Either way: fix the list, then run apply.sh on
# the repos named.
#
# Usage: repo-protections/bin/iu-targets.sh
set -uo pipefail
# shellcheck source=solo-ruleset.sh
. "$(dirname "${BASH_SOURCE[0]}")/solo-ruleset.sh"

crs=$(kubectl get imageupdaters.argocd-image-updater.argoproj.io -A -o json) \
  || { echo "FAILED: could not list ImageUpdater CRs (kubectl context?)" >&2; exit 1; }
live=$(jq -r '.items[].spec | (.writeBackConfig, .applicationRefs[]?.writeBackConfig)
              | select(.method? == "git") | .gitConfig.repository // empty' <<<"$crs" \
       | sed -E 's#^https://github\.com/##; s#\.git$##' | LC_ALL=C sort -u) \
  || { echo "FAILED: could not parse the ImageUpdater CRs" >&2; exit 1; }
[ -n "$live" ] || { echo "FAILED: no git write-back targets found -- wrong cluster or context?" >&2; exit 1; }

listed=$(printf '%s\n' "${IU_WRITEBACK_REPOS[@]}" | grep . | LC_ALL=C sort -u)
missing=$(LC_ALL=C comm -23 <(echo "$live") <(echo "$listed"))
stale=$(LC_ALL=C comm -13 <(echo "$live") <(echo "$listed"))

if [ -z "$missing" ] && [ -z "$stale" ]; then
  echo "in sync: $(wc -l <<<"$live") IU write-back repos"
  exit 0
fi
[ -n "$missing" ] && { echo "live IU targets missing from IU_WRITEBACK_REPOS (apply.sh would drop their IU bypass):"; sed 's/^/  /' <<<"$missing"; }
[ -n "$stale" ] && { echo "listed in IU_WRITEBACK_REPOS but no longer an IU git target:"; sed 's/^/  /' <<<"$stale"; }
exit 1
