#!/usr/bin/env bash
# Hermetic tests: CD repos (argocd-image-updater write-back targets) get the
# solo Ruleset -- 0 approvals, the IU App as the ONLY bypass actor.
#
# Decided by the owner 2026-11-10 after GitHub Pro made private-repo
# protection real. The previous CD Ruleset required 1 approval and listed
# Repository admin (role 5, `always`) and the CICD App as bypass actors. On a
# solo account every merge went through the admin bypass, and `always` also
# let the owner's credential -- i.e. every agent session -- push straight to
# main. The homelab Ruleset (no bypass, 0 approvals) closed that; CD repos
# keep exactly one exception: the IU App, which has to push directly.
#
# Run: bash tests/test_repo_protections_cd_solo.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
fail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; fail=1; }

IU='{"actor_id":378815,"actor_type":"Integration","bypass_mode":"always"}'
ADM='{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}'
CICD_PR='{"actor_id":3693085,"actor_type":"Integration","bypass_mode":"pull_request"}'
rs() {  # bypass-json approvals [name]
  jq -nc --argjson b "$1" --argjson n "$2" --arg name "${3:-main-protection-with-iu-bypass}" \
    '{id: 77, name: $name, enforcement: "active", bypass_actors: $b,
      rules: [{type: "deletion"}, {type: "non_fast_forward"},
              {type: "pull_request", parameters: {required_approving_review_count: $n}}]}'
}

# Stub gh. RULESETS_LIST is the JSON array `gh api repos/o/r/rulesets` returns;
# RULESET_77 the body of `gh api repos/o/r/rulesets/77`. POST/PUT payloads are
# written to $STUB_DIR/{post,put}.json.
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
args="$*"
case "$args" in
  "api repos/o/r")
    echo '{"default_branch":"main","visibility":"private","allow_merge_commit":false,"allow_squash_merge":true,"allow_rebase_merge":true,"delete_branch_on_merge":true,"allow_auto_merge":false,"has_issues":true,"fork":false}' ;;
  # No image-updater/ dir: CD-ness comes from the list (cloudflare, syncthing-chart, trilium-notes).
  "api repos/o/r/contents/image-updater") echo '{"message":"Not Found"}'; exit 1 ;;
  "api -X PATCH repos/o/r"*) echo '{}' ;;
  "api -X DELETE repos/o/r/branches/main/protection"*) touch "$STUB_DIR_OUT/classic_delete"; echo '' ;;
  "api repos/o/r/branches/main/protection"*)
    [ "${CLASSIC:-absent}" = present ] && { echo '{"required_pull_request_reviews":{"required_approving_review_count":1}}'; exit 0; }
    echo '{"message":"Branch not protected","status":"404"}'; exit 1 ;;
  "api repos/o/r/rulesets --jq "*)
    echo "$RULESETS_LIST" | jq -r "${args#api repos/o/r/rulesets --jq }" ;;
  "api repos/o/r/rulesets")    echo "$RULESETS_LIST" ;;
  "api repos/o/r/rulesets/77") echo "$RULESET_77" ;;
  *"-X POST"*"repos/o/r/rulesets"*)
    [ -n "${POST_FAIL:-}" ] && { cat >/dev/null; echo '{"message":"Validation Failed","status":"422"}'; exit 1; }
    cat > "$STUB_DIR_OUT/post.json"; echo '{"id":99}' ;;
  *"-X PUT"*"repos/o/r/rulesets/77"*)  cat > "$STUB_DIR_OUT/put.json";  echo '{"id":77}' ;;
  "api repos/o/r/contents/"*|"api repos/o/r/license"*)
    echo '{"message":"Not Found"}'; exit 1 ;;
  # Owner-only writers (the writers check is tested in solo_plain).
  "api repos/"*"/collaborators?per_page=100"*|"api repos/"*"/invitations?per_page=100"*) echo '[]' ;;
  *) echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH" STUB_DIR_OUT="$STUB_DIR"
export IU_WRITEBACK_REPOS_OVERRIDE=o/r   # o/r is an IU write-back target

run() { set +e; out=$(env "$@" 2>&1); rc=$?; set -e; }
payload_checks() {  # file label
  local p="$1" l="$2"
  [ "$(jq -c '[.bypass_actors[] | [.actor_type, .actor_id, .bypass_mode]]' "$p")" = '[["Integration",378815,"always"]]' ] \
    && ok "$l: IU App is the only bypass actor" || bad "$l: bypass actors: $(jq -c .bypass_actors "$p")"
  [ "$(jq '[.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count][0]' "$p")" = 0 ] \
    && ok "$l: 0 required approvals" || bad "$l: approvals $(jq -c '.rules' "$p")"
  [ "$(jq -c '[.rules[].type] | sort' "$p")" = '["deletion","non_fast_forward","pull_request"]' ] \
    && ok "$l: deletion + non_fast_forward + pull_request" || bad "$l: rules $(jq -c '[.rules[].type]' "$p")"
}

echo "apply.sh, CD repo with stale classic: Ruleset first, then strip"
rm -f "$STUB_DIR"/post.json "$STUB_DIR"/put.json "$STUB_DIR"/classic_delete
run RULESETS_LIST='[]' CLASSIC=present bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/post.json" ] && [ -e "$STUB_DIR/classic_delete" ] && ok "Ruleset created, classic stripped" || bad "conversion incomplete (rc=$rc)"
rm -f "$STUB_DIR"/post.json "$STUB_DIR"/classic_delete
run RULESETS_LIST='[]' CLASSIC=present POST_FAIL=1 bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && [ ! -e "$STUB_DIR/classic_delete" ] && ok "failed create: classic NOT deleted (main stays protected)" \
  || bad "classic deleted before the Ruleset existed (rc=$rc)"
rm -f "$STUB_DIR"/classic_delete

echo "apply.sh, CD repo, no Ruleset yet"
rm -f "$STUB_DIR"/post.json "$STUB_DIR"/put.json
run RULESETS_LIST='[]' bash "$BIN/apply.sh" o/r
[ "$rc" = 0 ] || bad "apply.sh exited $rc"
[ -s "$STUB_DIR/post.json" ] && payload_checks "$STUB_DIR/post.json" "POST" || bad "no Ruleset POSTed"

echo "apply.sh, CD repo, existing IU-bypass Ruleset under another name"
rm -f "$STUB_DIR"/post.json "$STUB_DIR"/put.json
run RULESETS_LIST="[$(rs "[$IU]" 1 main)]" RULESET_77="$(rs "[$IU]" 1 main)" bash "$BIN/apply.sh" o/r
[ -s "$STUB_DIR/put.json" ] && ok "updates the existing Ruleset (id 77) in place" || bad "did not PUT to the existing IU-bypass Ruleset"
[ ! -e "$STUB_DIR/post.json" ] && ok "does not create a duplicate Ruleset" || bad "POSTed a second Ruleset"
[ -s "$STUB_DIR/put.json" ] && payload_checks "$STUB_DIR/put.json" "PUT"

echo "audit.sh, CD repo"
audit_line() { run RULESETS_LIST="[$(rs "$1" "$2" "${3:-main-protection-with-iu-bypass}")]" RULESET_77="$(rs "$1" "$2" "${3:-main-protection-with-iu-bypass}")" bash "$BIN/audit.sh" o/r; }

audit_line "[$IU]" 0
grep -qE '✗.*(Ruleset|bypass|approvals)' <<<"$out" && bad "solo shape flagged" || ok "solo shape (IU only, 0 approvals) passes"

audit_line "[$IU]" 0 main
grep -qE '✗.*Ruleset \(IU bypass\)' <<<"$out" && bad "IU-bypass Ruleset not found under another name" || ok "finds the IU-bypass Ruleset whatever its name"

audit_line "[$IU,$ADM,$CICD_PR]" 1
grep -qE '✗.*admin bypass' <<<"$out" && ok "old shape: admin bypass is ✗" || bad "admin bypass not flagged"
grep -qE '✗.*approvals' <<<"$out" && ok "old shape: 1 approval is ✗" || bad "1 approval not flagged"

audit_line "[$IU,$CICD_PR]" 0
grep -qE '✗.*CICD' <<<"$out" && ok "CICD pull_request bypass is ✗ (not part of the solo shape)" || bad "CICD bypass not flagged"

audit_line "[$ADM]" 0
grep -qE '✗.*IU bypass' <<<"$out" && ok "no IU bypass is ✗" || bad "missing IU bypass not flagged"

[ "$fail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
