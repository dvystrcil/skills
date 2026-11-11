#!/usr/bin/env bash
# Hermetic tests: repo-protections keeps the CICD App's merge bypass
# (homelab D-037, homelab#1225). Re-running apply.sh used to PUT a Ruleset
# whose bypass list had only the IU App and admin, which silently removed
# the hand-added CICD App entry, so bot PRs stopped auto-merging.
#
# Run: bash tests/test_repo_protections_cicd_bypass.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
tfail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; tfail=1; }

# --- apply.sh, CD repo, no Ruleset yet: the POSTed payload --------------------
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
args="$*"
case "$args" in
  "api repos/o/r")                          echo '{"default_branch":"main","visibility":"public"}' ;;
  "api repos/o/r/contents/image-updater")   echo '[]' ;;
  "api -X PATCH repos/o/r"*)                echo '{}' ;;
  "api repos/o/r/branches/main/protection") echo '{"message":"Branch not protected"}'; exit 1 ;;
  "api repos/o/r/rulesets --jq"*)           echo '' ;;
  "api repos/o/r/rulesets")                 echo '[]' ;;
  *"-X POST"*"repos/o/r/rulesets"*)          cat > "$PAYLOAD_OUT"; echo '{}' ;;
  *) echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"

echo "apply.sh (CD repo)"
# Since the solo CD Ruleset (owner decision 2026-11-10) the CICD App and the
# admin role are deliberately NOT bypass actors on CD repos -- 0 approvals
# leaves them nothing to bypass. Full shape: tests/test_repo_protections_cd_solo.sh.
PAYLOAD_OUT="$STUB_DIR/payload.json" PATH="$STUB_DIR:$PATH" bash "$BIN/apply.sh" o/r >/dev/null 2>&1 \
  || bad "apply.sh exited non-zero"
p="$STUB_DIR/payload.json"
if [ -s "$p" ]; then
  [ "$(jq -r '[.bypass_actors[] | select(.actor_type=="Integration" and .actor_id==3693085)] | length' "$p")" = 0 ] \
    && ok "CICD App is not a CD bypass actor" || bad "CICD App still a CD bypass actor: $(jq -c .bypass_actors "$p")"
  [ "$(jq -r '[.bypass_actors[] | select(.actor_type=="Integration" and .actor_id==378815)] | length' "$p")" = 1 ] \
    && ok "IU App still a bypass actor" || bad "IU App bypass lost"
  [ "$(jq -r '[.bypass_actors[] | select(.actor_type=="RepositoryRole")] | length' "$p")" = 0 ] \
    && ok "admin role is not a bypass actor" || bad "admin bypass still present"
else
  bad "no Ruleset payload was POSTed"
fi

# --- audit.sh bypass checks (sourced; nothing runs on source) ---------------
echo "audit.sh"
# shellcheck source=/dev/null
# NB: audit.sh sets its own `fail=0` at top level, which is why this test
# counts in $tfail -- with `fail` the apply.sh section's failures above were
# silently reset to 0 here and the test passed red.
source "$BIN/audit.sh"
rs() { jq -nc --argjson a "$1" '{enforcement:"active", bypass_actors:$a}'; }
IU='{"actor_id":378815,"actor_type":"Integration","bypass_mode":"always"}'
ADM='{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}'
CICD_PR='{"actor_id":3693085,"actor_type":"Integration","bypass_mode":"pull_request"}'
CICD_ALWAYS='{"actor_id":3693085,"actor_type":"Integration","bypass_mode":"always"}'

v() { cicd_bypass_verdict "$(rs "$1")" "$2"; }
[ "$(v "[$IU,$ADM,$CICD_PR]" 1)" = ok ]          && ok "CD: pull_request bypass is ok"            || bad "CD pull_request: $(v "[$IU,$ADM,$CICD_PR]" 1)"
[ "$(v "[$IU,$ADM]" 1)" = missing ]              && ok "CD: no CICD bypass is missing"            || bad "CD missing: $(v "[$IU,$ADM]" 1)"
[ "$(v "[$IU,$ADM,$CICD_ALWAYS]" 1)" = too-wide ] && ok "CD: always mode is too wide"             || bad "CD always: $(v "[$IU,$ADM,$CICD_ALWAYS]" 1)"
[ "$(v "[$ADM]" 0)" = ok ]                        && ok "non-CD: no CICD bypass is fine (opt-in)" || bad "non-CD none: $(v "[$ADM]" 0)"
[ "$(v "[$ADM,$CICD_PR]" 0)" = ok ]               && ok "non-CD: pull_request bypass is ok"       || bad "non-CD pr: $(v "[$ADM,$CICD_PR]" 0)"
[ "$(v "[$ADM,$CICD_ALWAYS]" 0)" = too-wide ]     && ok "non-CD: always mode is too wide"         || bad "non-CD always: $(v "[$ADM,$CICD_ALWAYS]" 0)"

# A repo the CICD App pushes to DIRECTLY (skills: rebuild-configmap.yml commits
# the regenerated ConfigMap to main) needs `always`. That's a named exception,
# not a looser rule.
[ "$(cicd_bypass_verdict "$(rs "[$ADM,$CICD_ALWAYS]")" 0 dvystrcil/skills)" = ok ] \
  && ok "listed direct-push repo may use always" || bad "direct-push exception not honoured"
[ "$(cicd_bypass_verdict "$(rs "[$ADM,$CICD_ALWAYS]")" 0 dvystrcil/gpu-batch)" = too-wide ] \
  && ok "an unlisted repo with always is still too wide" || bad "exception leaked to other repos"

# The IU check must match the IU App by id, not "the first Integration".
[ -z "$(iu_bypass_id "$(rs "[$CICD_PR,$ADM]")")" ] \
  && ok "IU check is not satisfied by the CICD App" || bad "IU check matched the CICD App"
[ "$(iu_bypass_id "$(rs "[$CICD_PR,$IU,$ADM]")")" = 378815 ] \
  && ok "IU check finds the IU App by id" || bad "IU check missed the IU App"

[ "$tfail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
