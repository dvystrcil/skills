#!/usr/bin/env bash
# Shared by apply.sh and audit.sh: the solo Ruleset for plain (non-CD,
# non-fork) repos, private and public -- the homelab `main-protection` pattern. Source it; it only defines.
#
# Owner decision 2026-11-10, after GitHub Pro made private-repo protection
# real: classic Branch Protection with 1 approval and enforce_admins:false lets
# any admin credential -- every agent session -- push straight to main, and a
# solo owner can't approve their own PR anyway. The solo Ruleset requires a PR
# with 0 approvals, has NO bypass actors, and requires only the checks that
# run on every PR.

SOLO_RULESET_NAME="main-protection"
GHA_INTEGRATION_ID=15368          # GitHub Actions App: required checks come from it
SOLO_CHECKS_SAMPLE="${SOLO_CHECKS_SAMPLE:-30}"   # merged PRs looked at
SOLO_CHECKS_MIN_PRS="${SOLO_CHECKS_MIN_PRS:-5}"  # fewer -> no required checks

# Automation that pushes straight to main BY DESIGN. Each listed App becomes a
# bypass actor (`always`, the only mode that can push) in that repo's solo
# Ruleset; any other bypass is drift. A repo missing from this list whose bot
# pushes to main breaks the moment the Ruleset lands -- before adding a repo
# to the rollout, list its main commits that came from no PR.
#
# Every id here was read from an authoritative source (the App's credential or
# a rule-suite log), never copied from "a bypass that works elsewhere":
#   3693085 dvystrcil-ci-cd (CICD App)  skills rule-suites: dvystrcil-ci-cd[bot] => bypass via 16666429
#   5715971 dvystrcil-homelab-weather   owner, from the App's settings page (2026-11-11);
#           client Iv23liIw1wD3KJsoUUwr; installed on homelab-weather only, Contents r/w
#   4054155 GITSYNC_APP                 owner, from the App's settings page (2026-11-11);
#           installation 140314699; installed on llm-wiki (+ quartz-viewer reads)
#
# NEVER the GitHub Actions App (15368). On a user-owned repo GitHub rejects it:
#   422 "Actor GitHub Actions integration must be part of the ruleset source
#        or owner organization"   (homelab-weather, 2026-11-11)
# so a workflow pushing with GITHUB_TOKEN can't be exempted at all. It has to
# push as one of the owner's Apps instead. apply.sh refuses 15368 up front.
declare -A DIRECT_PUSH_APPS=(
  # The in-cluster collector commits samples/ via the Contents API (every
  # 15 min, CICD App). The off-cluster deriver (derive.yml, ubuntu-latest)
  # pushes derived/ every 3 h as its own App -- homelab-weather#13; its key is
  # a repo Actions secret so it keeps working with the cluster down.
  [dvystrcil/homelab-weather]="3693085 5715971"
  # wiki-mcp's git-sync sidecar pushes autosync commits; wiki-import and
  # wiki-lint push as the same App (llm-wiki#44), so one bypass covers all.
  [dvystrcil/llm-wiki]="4054155"
  # rebuild-configmap.yml pushes the regenerated ConfigMap to main as the CICD
  # App (6 rule-suite bypasses in Oct-Nov 2026, under the hand-made Ruleset).
  [dvystrcil/skills]="3693085"
  # n8n's heartbeat workflow commits every few minutes as the homelab n8n App
  # (99 rule-suite bypasses by homelab-n8n-workflow[bot] in a month).
  [dvystrcil/homelab-heartbeat]="3592257"
)

# Repos that keep a hand-made Ruleset instead of main-protection, and why.
# Anywhere else, audit.sh flags a hand-made Ruleset and
# `apply.sh --replace-hand-made` folds it into main-protection. Each entry
# names what has to happen before it can move.
declare -A HAND_MADE_RULESETS=(
  # Owned by homelab#2111 (verify-acs required check). Another session's AC7.
  [dvystrcil/gateway-services]="homelab#2111 owns this Ruleset (verify-acs gate)"
  # Backups land through a role bypass; it moves once the backup job pushes
  # as its own App (neptune-4pro-klipper-backup#10).
  [dvystrcil/neptune-4pro-klipper-backup]="backup job needs its own App first (neptune-4pro-klipper-backup#10)"
)
# Tests: HAND_MADE_RULESETS_OVERRIDE='owner/repo=reason'
if [ -n "${HAND_MADE_RULESETS_OVERRIDE:-}" ]; then
  HAND_MADE_RULESETS[${HAND_MADE_RULESETS_OVERRIDE%%=*}]="${HAND_MADE_RULESETS_OVERRIDE#*=}"
fi
# Tests: DIRECT_PUSH_APPS_OVERRIDE='owner/repo=id,id'
if [ -n "${DIRECT_PUSH_APPS_OVERRIDE:-}" ]; then
  DIRECT_PUSH_APPS[${DIRECT_PUSH_APPS_OVERRIDE%%=*}]="$(tr ',' ' ' <<<"${DIRECT_PUSH_APPS_OVERRIDE#*=}")"
fi

# CD repos: every repo argocd-image-updater pushes to (git write-back). These
# get the IU-bypass Ruleset instead of the solo one. apply.sh and audit.sh
# decide CD-ness from THIS list only.
#
# It used to be "has an image-updater/ directory", which was wrong both ways
# (audit --all, 2026-11-11): kroger-mcp-docker and syncthing hold their IU CR
# but IU writes to kroger-mcp and syncthing-chart, so they were audited as CD,
# got neither Ruleset and sat unprotected; cloudflare, syncthing-chart and
# trilium-notes are targets with no directory, so apply.sh would have dropped
# their IU bypass. The source of truth is the live CRs: each
# writeBackConfig.gitConfig.repository with method git. `iu-targets.sh` diffs
# this list against them -- run it after adding or removing an ImageUpdater.
# Read from the cluster 2026-11-11 (37 CRs, 37 repos).
IU_WRITEBACK_REPOS=(
  dvystrcil/argocd-mcp dvystrcil/bentopdf dvystrcil/cloudflare dvystrcil/cluster-ops
  dvystrcil/coder dvystrcil/deco-exporter dvystrcil/filebrowser-quantum dvystrcil/homepage
  dvystrcil/immich dvystrcil/infisical dvystrcil/invidious dvystrcil/jellyfin
  dvystrcil/kroger-mcp dvystrcil/language-tool dvystrcil/mcp-server dvystrcil/mealie
  dvystrcil/mealie-mcp dvystrcil/n8n-workflow dvystrcil/nscale-calc dvystrcil/ollama
  dvystrcil/open-terminal dvystrcil/open-webui dvystrcil/quartz-viewer dvystrcil/rpg-dice-mcp
  dvystrcil/searxng dvystrcil/searxng-mcp dvystrcil/string-tools dvystrcil/sweep-mcp
  dvystrcil/syncthing-chart dvystrcil/tailscale dvystrcil/tinysearch-mcp dvystrcil/tor-character-mcp
  dvystrcil/tor-dice dvystrcil/trilium-notes dvystrcil/tuber dvystrcil/wallos
  dvystrcil/wiki-mcp
)
# Tests: IU_WRITEBACK_REPOS_OVERRIDE='o/r o/s' replaces the list (set but empty = no CD repos).
if [ -n "${IU_WRITEBACK_REPOS_OVERRIDE+set}" ]; then
  read -ra IU_WRITEBACK_REPOS <<<"$IU_WRITEBACK_REPOS_OVERRIDE"
fi

# is_iu_writeback_repo <owner/repo>: exact match against IU_WRITEBACK_REPOS.
is_iu_writeback_repo() {
  local r
  for r in "${IU_WRITEBACK_REPOS[@]}"; do [ "$r" = "$1" ] && return 0; done
  return 1
}

# unexemptable_apps <owner/repo>: listed ids GitHub won't take as a bypass.
unexemptable_apps() {
  direct_push_apps "$1" | jq -r --argjson gha "$GHA_INTEGRATION_ID" '[.[] | select(. == $gha)] | join(" ")'
}

# direct_push_apps <owner/repo>: JSON array of App ids, sorted.
direct_push_apps() {
  # shellcheck disable=SC2086
  printf '%s\n' ${DIRECT_PUSH_APPS[$1]:-} | jq -sc 'map(tonumber) | sort'
}

# derive_required_checks <owner/repo>: JSON array of check names the GitHub
# Actions App reported on EVERY one of the last $SOLO_CHECKS_SAMPLE merged PRs.
# A path-filtered workflow that skipped some PR is NOT in it: requiring it
# would leave every PR that doesn't touch its paths waiting forever. With fewer
# than $SOLO_CHECKS_MIN_PRS merged PRs there is no evidence of what always
# runs, so: []. Fails (non-zero) if the API does.
derive_required_checks() {
  local repo="$1" shas sha names acc="" n=0
  shas=$(gh api "repos/$repo/pulls?state=closed&per_page=100" \
           --jq "[.[] | select(.merged_at)][:$SOLO_CHECKS_SAMPLE] | .[].head.sha") || return 1
  for sha in $shas; do
    names=$(gh api "repos/$repo/commits/$sha/check-runs?per_page=100" \
              --jq "[.check_runs[] | select(.app.id==$GHA_INTEGRATION_ID) | .name] | unique") || return 1
    if [ -z "$acc" ]; then acc="$names"
    else acc=$(jq -nc --argjson a "$acc" --argjson b "$names" '$a - ($a - $b)'); fi
    n=$((n + 1))
  done
  if [ "$n" -lt "$SOLO_CHECKS_MIN_PRS" ] || [ -z "$acc" ]; then echo '[]'; return 0; fi
  echo "$acc" | jq -c 'sort'
}

# solo_ruleset_payload <bypass-app-ids-json> <required-check-names-json>
solo_ruleset_payload() {
  jq -nc --arg name "$SOLO_RULESET_NAME" --argjson apps "$1" --argjson checks "$2" \
    --argjson gha "$GHA_INTEGRATION_ID" '{
      name: $name,
      target: "branch",
      enforcement: "active",
      bypass_actors: [$apps[] | {actor_id: ., actor_type: "Integration", bypass_mode: "always"}],
      conditions: {ref_name: {include: ["~DEFAULT_BRANCH"], exclude: []}},
      rules: ([
        {type: "deletion"},
        {type: "non_fast_forward"},
        {type: "pull_request", parameters: {
          required_approving_review_count: 0,
          dismiss_stale_reviews_on_push: false,
          require_code_owner_review: false,
          require_last_push_approval: false,
          required_review_thread_resolution: false,
          allowed_merge_methods: ["squash", "rebase"]
        }}
      ] + (if ($checks | length) > 0 then [
        {type: "required_status_checks", parameters: {
          strict_required_status_checks_policy: false,
          do_not_enforce_on_create: false,
          required_status_checks: [$checks[] | {context: ., integration_id: $gha}]
        }}
      ] else [] end))
    }'
}
