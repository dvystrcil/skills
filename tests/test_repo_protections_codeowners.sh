#!/usr/bin/env bash
# Hermetic tests: CODEOWNERS is required only where a rule requires
# code-owner review; anywhere else it is drift.
#
# GitHub Pro (2026-11-10) turned on code owners for private repos. Every
# `* @dvystrcil` CODEOWNERS file then auto-requested the owner's review on
# EVERY PR, bot PRs included (cluster-ops#1049: "dvystrcil-ci-cd[bot]
# requested your review ... as a code owner"). The solo Rulesets require 0
# approvals and no code-owner review, so the file gates nothing -- it only
# sends mail. The audit used to demand it on every repo.
#
# Run: bash tests/test_repo_protections_codeowners.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
tfail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; tfail=1; }

# Env knobs: CD=0|1, OWNERS=0|1 (.github/CODEOWNERS exists),
# CLASSIC=none|owners|plain, RS_OWNERS=0|1 (Ruleset requires code-owner review).
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
args="$*"
rs() {
  jq -nc --argjson o "${RS_OWNERS:-0}" '{id: 77, name: "main-protection-with-iu-bypass", enforcement: "active",
    bypass_actors: [{actor_id: 378815, actor_type: "Integration", bypass_mode: "always"}],
    rules: [{type: "deletion"}, {type: "non_fast_forward"},
            {type: "pull_request", parameters: {required_approving_review_count: 0, require_code_owner_review: ($o == 1)}}]}'
}
case "$args" in
  "api repos/o/r")
    echo '{"default_branch":"main","visibility":"private","allow_merge_commit":false,"allow_squash_merge":true,"allow_rebase_merge":true,"delete_branch_on_merge":true,"allow_auto_merge":false,"has_issues":true,"fork":false}' ;;
  "api repos/o/r/contents/image-updater")
    [ "${CD:-0}" = 1 ] && echo '[]' || { echo '{"message":"Not Found"}'; exit 1; } ;;
  "api repos/o/r/contents/.github/CODEOWNERS")
    [ "${OWNERS:-0}" = 1 ] && echo '{"name":"CODEOWNERS"}' || { echo '{"message":"Not Found"}'; exit 1; } ;;
  "api repos/o/r/branches/main/protection"*)
    case "${CLASSIC:-none}" in
      owners) echo '{"required_pull_request_reviews":{"required_approving_review_count":1,"require_code_owner_reviews":true,"dismiss_stale_reviews":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false}}' ;;
      plain)  echo '{"required_pull_request_reviews":{"required_approving_review_count":1,"require_code_owner_reviews":false,"dismiss_stale_reviews":true},"allow_force_pushes":{"enabled":false},"allow_deletions":{"enabled":false}}' ;;
      *) echo '{"message":"Branch not protected","status":"404"}'; exit 1 ;;
    esac ;;
  "api repos/o/r/rulesets --jq "*)
    if [ "${CLASSIC:-none}" = none ]; then echo "[$(rs)]" | jq -r "${args#api repos/o/r/rulesets --jq }"; fi ;;
  "api repos/o/r/rulesets")
    if [ "${CLASSIC:-none}" = none ]; then echo "[$(rs)]"; else echo '[]'; fi ;;
  "api repos/o/r/rulesets/77") rs ;;
  "api repos/o/r/contents/"*|"api repos/o/r/license"*)
    echo '{"message":"Not Found"}'; exit 1 ;;
  # Owner-only writers (the writers check is tested in solo_plain).
  "api repos/"*"/collaborators?per_page=100"*|"api repos/"*"/invitations?per_page=100"*) echo '[]' ;;
  *) echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH"

run() { set +e; out=$(env "$@" bash "$BIN/audit.sh" o/r 2>&1 | sed 's/\x1b\[[0-9;]*m//g'); set -e; }
line() { grep -E 'CODEOWNERS' <<<"$out" || true; }

run CD=1 OWNERS=1
grep -qE '✗ file: \.github/CODEOWNERS +got=present want=absent' <<<"$out" \
  && ok "solo Ruleset + CODEOWNERS present: ✗ present, want absent" || bad "unneeded CODEOWNERS not flagged: $(line)"

run CD=1 OWNERS=0
grep -qE '✗.*CODEOWNERS' <<<"$out" && bad "absent CODEOWNERS flagged on a solo Ruleset repo: $(line)" \
  || ok "solo Ruleset + no CODEOWNERS: not flagged"

run CD=1 OWNERS=1 RS_OWNERS=1
grep -qE '✓ file: \.github/CODEOWNERS +present' <<<"$out" \
  && ok "Ruleset requiring code-owner review + present: ✓" || bad "required-by-Ruleset CODEOWNERS not ✓: $(line)"

run CD=0 OWNERS=0 CLASSIC=owners
grep -qE '✗ file: \.github/CODEOWNERS +got=missing want=present' <<<"$out" \
  && ok "classic requiring code-owner review + missing: ✗ missing" || bad "missing required CODEOWNERS not flagged: $(line)"

run CD=0 OWNERS=1 CLASSIC=owners
grep -qE '✓ file: \.github/CODEOWNERS +present' <<<"$out" \
  && ok "classic requiring code-owner review + present: ✓" || bad "required-by-classic CODEOWNERS not ✓: $(line)"

run CD=0 OWNERS=1 CLASSIC=plain
grep -qE '✗ file: \.github/CODEOWNERS +got=present want=absent' <<<"$out" \
  && ok "classic WITHOUT code-owner review + present: ✗" || bad "classic-without-owners CODEOWNERS not flagged: $(line)"

[ "$tfail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
