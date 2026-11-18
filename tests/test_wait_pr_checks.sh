#!/usr/bin/env bash
# Hermetic tests for claude/issue-director/bin/wait-pr-checks.sh.
#
# The script exists so a director can wait on CI with ONE command and no pipe:
# `gh pr checks | wc -l` (to wait for checks to register) trips the
# pr-checks-pipe-guard hook, and a pipe after `gh pr checks` can hide failing
# rows (vt350#156). It must print every row and judge by the exit code.
#
# Run: bash tests/test_wait_pr_checks.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../claude/issue-director/bin/wait-pr-checks.sh"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
fail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; fail=1; }

# Stub gh. Per-PR knobs via env, keyed by the PR number N:
#   RC_<N>       exit code of `gh pr checks N` (0 pass, 1 fail, 8 pending)
#   LATE_<N>     number of `gh pr view` calls that report 0 checks before rows appear
#   NEVER_<N>    set: checks never register
cat >"$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
# gh pr view N -R repo --json statusCheckRollup -q '...'
# gh pr checks N -R repo [--watch]
sub="$1 $2"; n="$3"
state="$STUB_STATE/$n"
case "$sub" in
  "pr view")
    v="NEVER_$n"; [ -n "${!v:-}" ] && { echo 0; exit 0; }
    calls=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 )); echo "$calls" >"$state"
    l="LATE_$n"; if [ "$calls" -le "${!l:-0}" ]; then echo 0; else echo 2; fi ;;
  "pr checks")
    r="RC_$n"; rc="${!r:-0}"
    case " $* " in *" --watch "*) exit "$rc" ;; esac
    echo "build	pass	10s	https://example/$n/1"
    [ "$rc" = 1 ] && echo "lint	fail	5s	https://example/$n/2"
    exit "$rc" ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
STUB
chmod +x "$STUB_DIR/gh"
export PATH="$STUB_DIR:$PATH" STUB_STATE="$STUB_DIR/state" WAIT_PR_CHECKS_POLL=0
mkdir -p "$STUB_STATE"
run() { rm -f "$STUB_STATE"/*; out="$(env "$@" "$SCRIPT" o/r#11 o/s#12 2>&1)"; rc=$?; }

echo "wait-pr-checks.sh"

set +e
run RC_11=0 RC_12=0
[ "$rc" = 0 ] && ok "all passed -> exit 0" || bad "all passed -> exit 0 (got $rc)"
grep -q "== o/r#11 rc=0" <<<"$out" && grep -q "== o/s#12 rc=0" <<<"$out" \
  && ok "a verdict line per PR" || bad "a verdict line per PR"

run RC_11=0 RC_12=1
[ "$rc" = 1 ] && ok "one failed -> exit 1" || bad "one failed -> exit 1 (got $rc)"
grep -q "lint	fail" <<<"$out" && ok "failing row is printed" || bad "failing row is printed"

# The verdict names the outcome in one word. It used to end in a fixed legend,
# "(0 passed, 1 failed, 8 pending)", which two readers on 2026-11-18 took for
# counts on an all-green PR. Nothing on a passing PR's verdict may say "failed".
grep -qx "== o/r#11 rc=0 PASS" <<<"$out" && grep -qx "== o/s#12 rc=1 FAIL" <<<"$out" \
  && ! grep "^== o/r#11 rc=" <<<"$out" | grep -qi "fail" \
  && ok "verdict word: PASS / FAIL, no legend" || bad "verdict word: PASS / FAIL, no legend"
run RC_11=8 RC_12=0
grep -qx "== o/r#11 rc=8 PENDING" <<<"$out" \
  && ok "verdict word: PENDING" || bad "verdict word: PENDING"

run RC_11=0 RC_12=0 LATE_11=3
[ "$rc" = 0 ] && grep -q "== o/r#11 rc=0" <<<"$out" \
  && ok "waits for checks that register late" || bad "waits for checks that register late (got $rc)"

run RC_11=0 RC_12=0 NEVER_11=1 WAIT_PR_CHECKS_REGISTER=0
[ "$rc" = 1 ] && grep -q "o/r#11: no checks registered" <<<"$out" && grep -q "== o/s#12 rc=0" <<<"$out" \
  && ok "no checks -> reported, others still watched, exit 1" \
  || bad "no checks -> reported, others still watched, exit 1 (got $rc)"

out="$("$SCRIPT" 2>&1)"; rc=$?
[ "$rc" = 2 ] && ok "no args -> usage, exit 2" || bad "no args -> usage, exit 2 (got $rc)"
out="$("$SCRIPT" not-a-pr 2>&1)"; rc=$?
[ "$rc" = 2 ] && ok "bad arg -> exit 2" || bad "bad arg -> exit 2 (got $rc)"
set -e

exit "$fail"
