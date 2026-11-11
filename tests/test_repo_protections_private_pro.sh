#!/usr/bin/env bash
# Hermetic tests: with the account on GitHub Pro (since 2026-11-10), a private
# repo that can't be protected is DRIFT, not "n/a".
#
# Before Pro, branch protection and Rulesets on private repos returned
#   403 "Upgrade to GitHub Pro or make this repository public"
# and apply.sh/audit.sh treated that as "n/a (private, no Pro)": exit 0, a
# yellow dot, nothing to fix. So every private repo -- homelab, a live ArgoCD
# source, included -- passed the audit while being unprotected, and --all
# never looked at private repos at all. Pro made protection possible; these
# tests make sure the tooling stops excusing its absence. If the plan lapses,
# the 403 comes back and the audit goes red -- which is the point.
#
# Run: bash tests/test_repo_protections_private_pro.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
fail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; fail=1; }

# Stub gh. CD=1 makes image-updater/ exist. RULESETS: pro403 | empty.
# CLASSIC_PUT: ok | pro403. Every other contents/license probe is "missing".
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
args="$*"
pro403() {
  echo '{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","status":"403"}'
  echo 'gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)' >&2
  exit 1
}
case "$args" in
  "repo list"*)
    echo "$args" > "$REPO_LIST_ARGS"; echo "o/r" ;;
  "api repos/o/r")
    echo '{"default_branch":"main","visibility":"private","allow_merge_commit":false,"allow_squash_merge":true,"allow_rebase_merge":true,"delete_branch_on_merge":true,"allow_auto_merge":false,"has_issues":true,"fork":false}' ;;
  "api repos/o/r/contents/image-updater")
    [ "${CD:-0}" = 1 ] && echo '[]' || { echo '{"message":"Not Found"}'; exit 1; } ;;
  "api -X PATCH repos/o/r"*) echo '{}' ;;
  "api repos/o/r/branches/main/protection"*)
    [ "${RULESETS:-}" = pro403 ] && pro403
    echo '{"message":"Branch not protected","status":"404"}'; exit 1 ;;
  "api -X DELETE repos/o/r/branches/main/protection"*) echo '{}' ;;
  "api repos/o/r/rulesets"*)
    case "${RULESETS:-}" in
      pro403) pro403 ;;
      empty)  [[ "$args" == *--jq* ]] && echo '' || echo '[]' ;;
      *) echo "stub: bad RULESETS" >&2; exit 99 ;;
    esac ;;
  *"-X PUT"*"repos/o/r/branches/main/protection"*)
    cat >/dev/null
    [ "${CLASSIC_PUT:-ok}" = pro403 ] && pro403
    echo '{}' ;;
  "api repos/o/r/contents/"*|"api repos/o/r/license"*)
    echo '{"message":"Not Found"}'; exit 1 ;;
  *) echo "stub gh: unexpected call: $args" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH" REPO_LIST_ARGS="$STUB_DIR/repo-list-args"

run() {  # env assignments..., then the command; sets $out and $rc
  set +e; out=$(env "$@" 2>&1); rc=$?; set -e
}

echo "apply.sh"
run CD=0 RULESETS=pro403 bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && ok "non-CD private + 403: exits non-zero" || bad "non-CD private + 403 exited 0"
grep -q 'n/a' <<<"$out" && bad "non-CD private + 403 still says n/a" || ok "non-CD private + 403: no 'n/a'"

run CD=1 RULESETS=pro403 bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && ok "CD private + 403: exits non-zero" || bad "CD private + 403 exited 0"
grep -q 'SKIPPED' <<<"$out" && bad "CD private + 403 still says SKIPPED" || ok "CD private + 403: not SKIPPED"

run CD=0 RULESETS=empty CLASSIC_PUT=pro403 bash "$BIN/apply.sh" o/r
[ "$rc" != 0 ] && ok "private classic PUT 403: exits non-zero" || bad "private classic PUT 403 exited 0"

run CD=0 RULESETS=empty CLASSIC_PUT=ok bash "$BIN/apply.sh" o/r
[ "$rc" = 0 ] && grep -q 'protection applied' <<<"$out" \
  && ok "private, Pro works: classic protection applied (regression guard)" \
  || bad "private happy path broke"

echo "audit.sh"
run CD=0 RULESETS=pro403 bash "$BIN/audit.sh" o/r
grep -q 'n/a (private' <<<"$out" && bad "non-CD private + 403 audited as n/a" || ok "non-CD private + 403: not n/a"
grep -q '✗.*branch protection' <<<"$out" && ok "non-CD private + 403: branch protection is ✗" || bad "non-CD private + 403 not flagged"

run CD=0 RULESETS=empty bash "$BIN/audit.sh" o/r
grep -q '✗.*branch protection' <<<"$out" && ok "private, unprotected: branch protection is ✗" || bad "private unprotected repo not flagged"

run CD=1 RULESETS=pro403 bash "$BIN/audit.sh" o/r
[ "$rc" != 0 ] && ok "CD private + 403: audit exits non-zero" || bad "CD private + 403 audit exited 0"
grep -q 'n/a (private' <<<"$out" && bad "CD private + 403 audited as n/a" || ok "CD private + 403: not n/a"

run CD=0 RULESETS=empty bash "$BIN/audit.sh" --all
if grep -q -- '--visibility public' "$REPO_LIST_ARGS" 2>/dev/null; then
  bad "--all still lists only public repos: $(cat "$REPO_LIST_ARGS")"
else
  ok "--all includes private repos"
fi
grep -q -- '--no-archived' "$REPO_LIST_ARGS" 2>/dev/null \
  && ok "--all skips archived repos" || bad "--all includes archived repos: $(cat "$REPO_LIST_ARGS" 2>/dev/null)"

[ "$fail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
