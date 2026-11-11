#!/usr/bin/env bash
# Hermetic tests for apply.sh's non-CD "already protected by a Ruleset?"
# probe -- skills#77. A stub `gh` on PATH stands in for the GitHub API;
# RULESETS_MODE picks what `gh api repos/X/rulesets` returns.
#
# The bug: `gh api` prints an error body to STDOUT and exits non-zero, so a
# 403 "Upgrade to GitHub Pro" body was read as a ruleset name and apply.sh
# reported "already protected by Ruleset(s): {"message":...}". Any other API
# failure skipped classic protection the same way (fail open).
#
# Run: bash tests/test_apply_rulesets_probe.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY="$HERE/../repo-protections/bin/apply.sh"

STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT

cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
# Minimal gh stub: only the `gh api` calls apply.sh makes on the non-CD path.
args="$*"
case "$args" in
  "api repos/o/r")
    echo '{"default_branch":"main","visibility":"private"}' ;;
  "api repos/o/r/contents/image-updater")
    echo '{"message":"Not Found","status":"404"}'; exit 1 ;;
  "api -X PATCH repos/o/r"*)
    echo '{}' ;;
  "api repos/o/r/rulesets"*)
    case "$RULESETS_MODE" in
      pro403)
        echo '{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","documentation_url":"https://docs.github.com/rest","status":"403"}'
        echo 'gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)' >&2
        exit 1 ;;
      ratelimit)
        echo '{"message":"API rate limit exceeded","status":"429"}'
        echo 'gh: API rate limit exceeded (HTTP 429)' >&2
        exit 1 ;;
      active)
        if [[ "$args" == *--jq* ]]; then echo 'main-protect'; else echo '[{"name":"main-protect","enforcement":"active"}]'; fi ;;
      *) echo "stub: unknown RULESETS_MODE" >&2; exit 99 ;;
    esac ;;
  "api -X PUT repos/o/r/branches/main/protection"*)
    echo '{}' ;;
  *)
    echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"

fail=0
run_apply() {  # sets $out and $rc
  set +e
  out=$(RULESETS_MODE="$1" PATH="$STUB_DIR:$PATH" bash "$APPLY" o/r 2>&1)
  rc=$?
  set -e
}
expect() {  # desc, condition-result
  if [ "$2" = 0 ]; then echo "ok - $1"; else echo "FAIL - $1"; echo "$out" | sed 's/^/    | /'; fail=1; fi
}

# 1. Private repo, 403 "Upgrade to GitHub Pro": since the account went Pro
#    (2026-11-10) this means the plan lapsed -- fail closed, never "n/a" and
#    never "protected by Ruleset". (tests/test_repo_protections_private_pro.sh)
run_apply pro403
expect "403 Pro: exits non-zero" "$([ "$rc" != 0 ]; echo $?)"
expect "403 Pro: does NOT report n/a" \
  "$(! grep -q 'n/a' <<<"$out"; echo $?)"
expect "403 Pro: does NOT claim a Ruleset protects it" \
  "$(! grep -q 'already protected by Ruleset' <<<"$out"; echo $?)"

# 2. Any other API failure fails closed (non-zero, no false "protected").
run_apply ratelimit
expect "other failure: exits non-zero" "$([ "$rc" != 0 ]; echo $?)"
expect "other failure: does NOT claim a Ruleset protects it" \
  "$(! grep -q 'already protected by Ruleset' <<<"$out"; echo $?)"

# 3. A real active Ruleset still skips classic protection (regression guard).
run_apply active
expect "active ruleset: exits 0" "$([ "$rc" = 0 ]; echo $?)"
expect "active ruleset: names it" \
  "$(grep -q 'already protected by Ruleset(s): main-protect' <<<"$out"; echo $?)"

exit "$fail"
