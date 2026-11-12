#!/usr/bin/env bash
# Hermetic tests: plain (non-CD) PRIVATE repos get the solo Ruleset -- the
# homelab pattern -- instead of classic Branch Protection.
#
# Owner decision 2026-11-10 (after GitHub Pro): classic protection with
# 1 approval and enforce_admins:false let any admin credential -- i.e. every
# agent session -- push straight to main, and a solo owner cannot approve
# their own PR anyway. The solo Ruleset `main-protection`:
#   - PR required, 0 approvals, squash + rebase only
#   - no bypass actors, EXCEPT Apps listed in DIRECT_PUSH_APPS for that repo
#     (automation that pushes to main by design, e.g. a sample collector)
#   - required status checks = the GitHub Actions (integration 15368) check
#     names present on EVERY one of the last merged PRs; none when the repo
#     has too few merged PRs to tell what always runs.
#
# Run: bash tests/test_repo_protections_solo_plain.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
fail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; fail=1; }

# Stub gh. Knobs (env):
#   VIS            private | public                       (default private)
#   CLASSIC        present | absent                       (default absent)
#   RULESETS_LIST  JSON array for repos/o/r/rulesets      (default [])
#   RULESET_77     body of repos/o/r/rulesets/77
#   PRS            JSON array of merged-PR head SHAs, newest first (default [])
#   CHECKS_<sha>   JSON array of [name, app_id] pairs for that SHA's check-runs
# Writes: $OUT/post.json, $OUT/put.json, $OUT/classic_put.json, $OUT/classic_delete,
#         $OUT/patch (repo settings).
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
args="$*"
# Like gh: apply the --jq filter (raw output) when one was passed.
jqf() { if [[ "$args" == *" --jq "* ]]; then jq -r "${args#* --jq }"; else cat; fi; }
case "$args" in
  "api repos/o/r")
    jq -nc --arg v "${VIS:-private}" --arg f "${FORK:-false}" --arg l "${LIC:-MIT}" '{default_branch:"main",visibility:$v,allow_merge_commit:false,allow_squash_merge:true,allow_rebase_merge:true,delete_branch_on_merge:true,allow_auto_merge:false,has_issues:true,fork:($f=="true"),license:{spdx_id:$l}}' ;;
  "api repos/o/r/contents/image-updater") echo '{"message":"Not Found"}'; exit 1 ;;
  "api -X PATCH repos/o/r"*) touch "$OUT/patch"; echo '{}' ;;
  "api -X DELETE repos/o/r/branches/main/protection"*) touch "$OUT/classic_delete"; echo '' ;;
  *"-X PUT"*"repos/o/r/branches/main/protection"*) cat > "$OUT/classic_put.json"; echo '{}' ;;
  "api repos/o/r/branches/main/protection"*)
    if [ "${CLASSIC:-absent}" = present ]; then
      echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false}}'
    else
      echo '{"message":"Branch not protected","status":"404"}'; exit 1
    fi ;;
  "api repos/o/r/pulls?state=closed&per_page=100"*)
    echo "${PRS:-[]}" | jq -c '[.[] | {merged_at: "2026-11-01T00:00:00Z", head: {sha: .}}]' | jqf ;;
  "api repos/o/r/commits/"*"/check-runs?per_page=100"*)
    sha=${args#api repos/o/r/commits/}; sha=${sha%%/*}
    var="CHECKS_$sha"
    echo "${!var:-[]}" | jq -c '{check_runs: [.[] | {name: .[0], app: {id: .[1]}}]}' | jqf ;;
  "api repos/o/r/rulesets --jq "*)
    echo "${RULESETS_LIST:-[]}" | jq -r "${args#api repos/o/r/rulesets --jq }" ;;
  "api repos/o/r/rulesets")    echo "${RULESETS_LIST:-[]}" ;;
  "api repos/o/r/rulesets/77") echo "$RULESET_77" ;;
  *"-X POST"*"repos/o/r/rulesets"*)
    [ -n "${POST_FAIL:-}" ] && { cat >/dev/null; echo '{"message":"Validation Failed","status":"422"}'; exit 1; }
    cat > "$OUT/post.json"; echo '{"id":99}' ;;
  *"-X PUT"*"repos/o/r/rulesets/77"*) cat > "$OUT/put.json";  echo '{"id":77}' ;;
  "api repos/o/r/collaborators?per_page=100"*)
    [ -n "${COLLABS_ERR:-}" ] && { echo '{"message":"Server Error","status":"500"}'; exit 1; }
    # Not ${COLLABS:-<json>}: the JSON's first `}` would end the expansion.
    owner_only='[{"login":"o","permissions":{"push":true,"admin":true}}]'
    echo "${COLLABS:-$owner_only}" | jqf ;;
  "api repos/o/r/invitations?per_page=100"*)
    [ -n "${INVITES_ERR:-}" ] && { echo '{"message":"Server Error","status":"500"}'; exit 1; }
    echo "${INVITES:-[]}" | jqf ;;
  "api repos/o/r/license"*) echo '{}' ;;
  # The solo Ruleset requires no code-owner review, so no CODEOWNERS (skills#93).
  "api repos/o/r/contents/.github/CODEOWNERS"*) echo '{"message":"Not Found"}'; exit 1 ;;
  "api repos/o/r/contents/"*) echo '{}' ;;
  *) echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH" OUT="$STUB_DIR"

run() { rm -f "$STUB_DIR"/{post.json,put.json,classic_put.json,classic_delete,patch}; set +e; out=$(env "$@" 2>&1); rc=$?; set -e; }
GHA=15368

# Six merged PRs: lint + test ran on every one; e2e (path-filtered) on some;
# "ext" is a third-party App's check on every one (not ours to require).
six_prs() {
  local env=(PRS='["a1","a2","a3","a4","a5","a6"]')
  for s in a1 a2 a3 a4 a5 a6; do
    if [ "$s" = a3 ] || [ "$s" = a5 ]; then
      env+=("CHECKS_$s=[[\"lint\",$GHA],[\"test\",$GHA],[\"ext\",999]]")
    else
      env+=("CHECKS_$s=[[\"lint\",$GHA],[\"test\",$GHA],[\"e2e\",$GHA],[\"ext\",999]]")
    fi
  done
  printf '%s\n' "${env[@]}"
}
mapfile -t SIX < <(six_prs)

echo "apply.sh, private non-CD, no protection yet"
run "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ "$rc" = 0 ] || bad "apply.sh exited $rc"
[ ! -e "$STUB_DIR/classic_put.json" ] && ok "no classic Branch Protection" || bad "classic protection PUT"
if [ -s "$STUB_DIR/post.json" ]; then
  p="$STUB_DIR/post.json"
  [ "$(jq -r .name "$p")" = main-protection ] && ok "Ruleset named main-protection" || bad "name $(jq -r .name "$p")"
  [ "$(jq -r .enforcement "$p")" = active ] && ok "enforcement active" || bad "enforcement $(jq -r .enforcement "$p")"
  [ "$(jq -c .bypass_actors "$p")" = '[]' ] && ok "no bypass actors" || bad "bypass $(jq -c .bypass_actors "$p")"
  [ "$(jq -c '.conditions.ref_name.include' "$p")" = '["~DEFAULT_BRANCH"]' ] && ok "targets the default branch" || bad "conditions $(jq -c .conditions "$p")"
  [ "$(jq '[.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count][0]' "$p")" = 0 ] \
    && ok "0 required approvals" || bad "approvals $(jq -c .rules "$p")"
  [ "$(jq -c '[.rules[] | select(.type=="pull_request") | .parameters.allowed_merge_methods][0]' "$p")" = '["squash","rebase"]' ] \
    && ok "squash + rebase only" || bad "merge methods $(jq -c .rules "$p")"
  [ "$(jq -c '[.rules[].type] | sort' "$p")" = '["deletion","non_fast_forward","pull_request","required_status_checks"]' ] \
    && ok "deletion + non_fast_forward + pull_request + required_status_checks" || bad "rules $(jq -c '[.rules[].type]' "$p")"
  [ "$(jq -c '[.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[]] | sort_by(.context)' "$p")" \
      = "[{\"context\":\"lint\",\"integration_id\":$GHA},{\"context\":\"test\",\"integration_id\":$GHA}]" ] \
    && ok "required checks = Actions checks on EVERY recent PR (lint, test; not e2e, not ext)" \
    || bad "required checks $(jq -c '.rules[] | select(.type=="required_status_checks")' "$p")"
else
  bad "no Ruleset POSTed"
fi

echo "apply.sh, too few merged PRs -> no required-checks rule"
run PRS='["b1","b2"]' "CHECKS_b1=[[\"lint\",$GHA]]" "CHECKS_b2=[[\"lint\",$GHA]]" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/post.json" ] && [ "$(jq -c '[.rules[].type] | sort' "$STUB_DIR/post.json")" = '["deletion","non_fast_forward","pull_request"]' ] \
  && ok "2 merged PRs: no required_status_checks rule" || bad "rules with 2 PRs: $(jq -c '[.rules[].type]' "$STUB_DIR/post.json" 2>/dev/null)"

echo "apply.sh, PRs but no CI -> no required-checks rule"
run PRS='["c1","c2","c3","c4","c5"]' bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/post.json" ] && [ "$(jq -c '[.rules[].type] | sort' "$STUB_DIR/post.json")" = '["deletion","non_fast_forward","pull_request"]' ] \
  && ok "no check-runs: no required_status_checks rule" || bad "rules without CI: $(jq -c '[.rules[].type]' "$STUB_DIR/post.json" 2>/dev/null)"

echo "apply.sh, a direct-push repo gets exactly its listed Apps as bypass"
run DIRECT_PUSH_APPS_OVERRIDE='o/r=3693085,3592257' "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/post.json" ] && [ "$(jq -c '[.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode]] | sort' "$STUB_DIR/post.json")" \
    = '[["Integration",3592257,"always"],["Integration",3693085,"always"]]' ] \
  && ok "bypass = the two listed Apps, always" || bad "bypass $(jq -c .bypass_actors "$STUB_DIR/post.json" 2>/dev/null)"

echo "apply.sh, the GitHub Actions App can't be a bypass actor on a user-owned repo"
# Live 2026-11-11, homelab-weather: POST -> 422 "Actor GitHub Actions
# integration must be part of the ruleset source or owner organization".
# A GITHUB_TOKEN push can never be exempted; the bot must push as an App.
run DIRECT_PUSH_APPS_OVERRIDE='o/r=3693085,15368' "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && [ ! -e "$STUB_DIR/post.json" ] && grep -q '15368' <<<"$out" \
  && ok "refuses, names 15368, writes nothing" || bad "accepted 15368 as a bypass (rc=$rc)"
grep -E '^\s*\[[^]]+\]="[^"]*\b15368\b' "$BIN/solo-ruleset.sh" \
  && bad "DIRECT_PUSH_APPS lists 15368" || ok "DIRECT_PUSH_APPS lists no 15368"

echo "apply.sh, existing main-protection is updated in place"
EXIST='{"id":77,"name":"main-protection","enforcement":"active","bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}],"rules":[]}'
run RULESETS_LIST="[$EXIST]" RULESET_77="$EXIST" "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/put.json" ] && ok "PUT to the existing Ruleset 77" || bad "did not PUT to main-protection"
[ ! -e "$STUB_DIR/post.json" ] && ok "no duplicate Ruleset" || bad "POSTed a second Ruleset"
[ -s "$STUB_DIR/put.json" ] && [ "$(jq -c .bypass_actors "$STUB_DIR/put.json")" = '[]' ] && ok "admin bypass removed" || bad "PUT bypass $(jq -c .bypass_actors "$STUB_DIR/put.json" 2>/dev/null)"

echo "apply.sh, a hand-made Ruleset under another name is left alone"
OTHER='{"id":77,"name":"protect-main","enforcement":"active","bypass_actors":[{"actor_id":3592257,"actor_type":"Integration","bypass_mode":"always"}],"rules":[]}'
run RULESETS_LIST="[$OTHER]" RULESET_77="$OTHER" "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ "$rc" = 0 ] && [ ! -e "$STUB_DIR/post.json" ] && [ ! -e "$STUB_DIR/put.json" ] && grep -q SKIPPED <<<"$out" \
  && ok "SKIPPED, nothing written" || bad "touched a hand-made Ruleset (rc=$rc)"

echo "apply.sh, stale classic protection is stripped"
run CLASSIC=present "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -e "$STUB_DIR/classic_delete" ] && [ -s "$STUB_DIR/post.json" ] && ok "classic deleted, Ruleset created" || bad "classic not stripped (rc=$rc)"

echo "apply.sh, a failed Ruleset create leaves classic protection in place"
# The Ruleset is created FIRST, classic stripped only after it exists:
# the other order leaves main unprotected whenever the create fails.
run CLASSIC=present POST_FAIL=1 "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && ok "exit non-zero" || bad "exit 0 on a failed create"
[ ! -e "$STUB_DIR/classic_delete" ] && ok "classic NOT deleted (main stays protected)" || bad "classic deleted before the Ruleset existed"

echo "apply.sh --dry-run writes nothing"
run "${SIX[@]}" bash "$BIN/apply.sh" o/r --dry-run
[ "$rc" = 0 ] && ok "exit 0" || bad "dry-run exited $rc"
[ ! -e "$STUB_DIR/post.json" ] && [ ! -e "$STUB_DIR/patch" ] && [ ! -e "$STUB_DIR/classic_delete" ] \
  && ok "no POST, no PATCH, no DELETE" || bad "dry-run wrote something"
grep -q '"main-protection"' <<<"$out" && ok "prints the planned Ruleset" || bad "planned Ruleset not printed"

echo "apply.sh, PUBLIC non-CD gets the solo Ruleset too (owner decision 2026-11-11)"
run VIS=public "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/post.json" ] && [ ! -e "$STUB_DIR/classic_put.json" ] && ok "public: Ruleset, no classic" || bad "public still classic (rc=$rc)"
run VIS=public CLASSIC=present "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -e "$STUB_DIR/classic_delete" ] && [ -s "$STUB_DIR/post.json" ] && ok "public: classic stripped" || bad "public classic not stripped"

echo "apply.sh, a FORK keeps classic (a no-bypass Ruleset breaks 'Sync fork')"
run VIS=public FORK=true "${SIX[@]}" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/classic_put.json" ] && [ ! -e "$STUB_DIR/post.json" ] && ok "fork: classic, no Ruleset" || bad "fork got a Ruleset (rc=$rc)"

echo "audit.sh, private non-CD"
solo() {  # bypass-json approvals
  jq -nc --argjson b "$1" --argjson n "$2" '{id:77,name:"main-protection",enforcement:"active",bypass_actors:$b,
    rules:[{type:"deletion"},{type:"non_fast_forward"},{type:"pull_request",parameters:{required_approving_review_count:$n}}]}'
}
aud() { run RULESETS_LIST="[$1]" RULESET_77="$1" "${@:2}" bash "$BIN/audit.sh" o/r; }

aud "$(solo '[]' 0)"
grep -q '✗' <<<"$out" && bad "solo shape flagged" || ok "solo shape passes"

aud "$(solo '[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}]' 0)"
grep -qE '✗.*bypass' <<<"$out" && ok "admin bypass is ✗" || bad "admin bypass not flagged"

aud "$(solo '[]' 1)"
grep -qE '✗.*approvals' <<<"$out" && ok "1 approval is ✗" || bad "1 approval not flagged"

aud "$(solo '[{"actor_id":3693085,"actor_type":"Integration","bypass_mode":"always"}]' 0)"
grep -qE '✗.*bypass' <<<"$out" && ok "unlisted App bypass is ✗" || bad "unlisted App bypass not flagged"

aud "$(solo '[{"actor_id":3693085,"actor_type":"Integration","bypass_mode":"always"}]' 0)" DIRECT_PUSH_APPS_OVERRIDE='o/r=3693085'
grep -q '✗' <<<"$out" && bad "listed direct-push App flagged" || ok "listed direct-push App passes"

aud "$(solo '[]' 0)" DIRECT_PUSH_APPS_OVERRIDE='o/r=3693085'
grep -qE '✗.*bypass' <<<"$out" && ok "listed App missing from bypass is ✗ (its pushes would break)" || bad "missing listed App not flagged"

aud "$(solo '[]' 0)" CLASSIC=present
grep -qE '✗.*classic' <<<"$out" && ok "solo Ruleset + leftover classic is ✗ (classic blocks bypassed bots)" || bad "leftover classic not flagged"

run RULESETS_LIST='[]' CLASSIC=present bash "$BIN/audit.sh" o/r
grep -qE '✗.*main-protection' <<<"$out" && ok "private repo on classic protection is ✗" || bad "classic on private not flagged"

aud "$(solo '[]' 0)" VIS=public
grep -q '✗' <<<"$out" && bad "public solo shape flagged" || ok "public: solo shape passes"
run VIS=public RULESETS_LIST='[]' CLASSIC=present bash "$BIN/audit.sh" o/r
grep -qE '✗.*main-protection' <<<"$out" && ok "public repo still on classic is ✗" || bad "public classic not flagged"
run VIS=public FORK=true RULESETS_LIST='[]' CLASSIC=present bash "$BIN/audit.sh" o/r
grep -qE '✗.*main-protection' <<<"$out" && bad "fork on classic flagged" || ok "fork on classic is not flagged"

echo "audit.sh, hand-made Ruleset"
HAND='{"id":77,"name":"main","enforcement":"active","bypass_actors":[],"rules":[{"type":"deletion"},{"type":"non_fast_forward"}]}'
aud "$HAND"
grep -q '✗' <<<"$out" && bad "hand-made Ruleset alone flagged" || ok "hand-made Ruleset alone passes (left alone)"
# flatpak-repo, obico-docker, pihole-lists (2026-11-11): a hand-made Ruleset
# AND classic protection with enforce_admins:false. The audit returned early
# for hand-made Rulesets and never looked at classic.
aud "$HAND" CLASSIC=present
grep -qE '✗.*classic' <<<"$out" && ok "hand-made Ruleset + classic is ✗" || bad "hand-made + classic not flagged"

echo "audit.sh, license exceptions (LICENSE_EXCEPTIONS)"
aud "$(solo '[]' 0)" LIC=GPL-3.0
grep -qE '✗.*license.*GPL-3.0' <<<"$out" && ok "GPL with no exception is ✗" || bad "unlisted GPL not flagged"
aud "$(solo '[]' 0)" LIC=GPL-3.0 LICENSE_EXCEPTIONS_OVERRIDE='o/r=GPL-3.0'
grep -q '✗' <<<"$out" && bad "listed GPL flagged" || ok "listed exception passes"
grep -qE 'license.*GPL-3.0.*exception' <<<"$out" && ok "says it is a recorded exception" || bad "exception not labelled"
aud "$(solo '[]' 0)" LIC=MIT LICENSE_EXCEPTIONS_OVERRIDE='o/r=GPL-3.0'
grep -qE '✗.*license.*got=MIT want=GPL-3.0' <<<"$out" && ok "drift FROM the exception is ✗ (exact license, not 'anything goes')" || bad "drift from exception not flagged"
grep -qE '^\s*\[dvystrcil/vt350\]="GPL-3.0"' "$BIN/audit.sh" && ok "vt350 is listed as GPL-3.0" || bad "vt350 exception missing"

echo "audit.sh, writers: 0 approvals means any writer can self-merge (owner decision 2026-11-11)"
OWNER_ONLY='[{"login":"o","permissions":{"push":true,"admin":true}}]'
aud "$(solo '[]' 0)" COLLABS="${OWNER_ONLY%]},{\"login\":\"pal\",\"permissions\":{\"push\":true,\"admin\":false}}]"
grep -qE '✗.*writers.*pal' <<<"$out" && ok "a write collaborator is ✗, named" || bad "write collaborator not flagged"
aud "$(solo '[]' 0)" COLLABS="${OWNER_ONLY%]},{\"login\":\"viewer\",\"permissions\":{\"push\":false,\"admin\":false}}]"
grep -q '✗' <<<"$out" && bad "read-only collaborator flagged" || ok "read-only collaborator passes (can't merge)"
aud "$(solo '[]' 0)" INVITES='[{"invitee":{"login":"newbie"},"permissions":"write"}]'
grep -qE '✗.*writers.*newbie \(invited\)' <<<"$out" && ok "pending write invite is ✗ (one click from writer)" || bad "write invite not flagged"
aud "$(solo '[]' 0)" INVITES='[{"invitee":{"login":"reader"},"permissions":"read"}]'
grep -q '✗' <<<"$out" && bad "read invite flagged" || ok "read invite passes"
aud "$(solo '[]' 0)" COLLABS_ERR=1
grep -qE '✗.*writers' <<<"$out" && ok "collaborators API error is ✗ (fails closed)" || bad "API error read as owner-only"
aud "$(solo '[]' 0)" INVITES_ERR=1
grep -qE '✗.*writers' <<<"$out" && ok "invitations API error is ✗ (fails closed)" || bad "invitations error read as owner-only"
run VIS=public FORK=true RULESETS_LIST='[]' CLASSIC=present COLLABS="${OWNER_ONLY%]},{\"login\":\"pal\",\"permissions\":{\"push\":true,\"admin\":false}}]" bash "$BIN/audit.sh" o/r
grep -qE '✗.*writers.*pal' <<<"$out" && ok "forks too" || bad "fork writer not flagged"

[ "$fail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
