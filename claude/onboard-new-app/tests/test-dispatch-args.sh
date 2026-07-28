#!/usr/bin/env bash
# Hermetic test: onboard-new-app-dispatch.sh's argument-mapping and
# JSON-body-construction logic, without hitting GitHub's real API.
#
# Mocks curl via a fake binary earlier in PATH that just captures its
# args/stdin to a file instead of making a real request, then asserts
# the captured request body has the right shape. No network, no auth
# needed -- MCP_SERVER_GH_DISPATCH_TOKEN is set to a dummy value.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPATCH_SCRIPT="${SCRIPT_DIR}/bin/onboard-new-app-dispatch.sh"
FAKE_BIN_DIR="$(mktemp -d)"
CAPTURED_BODY="$(mktemp)"
CAPTURED_URL="$(mktemp)"

cleanup() { rm -rf "${FAKE_BIN_DIR}" "${CAPTURED_BODY}" "${CAPTURED_URL}"; }
trap cleanup EXIT

# Fake curl: writes the -d body and target URL to files, always
# reports the response file with status 204 (GitHub's real success
# code for workflow_dispatch), matching what the real script expects.
cat > "${FAKE_BIN_DIR}/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-d" ]]; then
        echo -n "$arg" > "${CAPTURED_BODY}"
    fi
    case "$arg" in
        https://*) echo -n "$arg" > "${CAPTURED_URL}" ;;
    esac
    prev="$arg"
done
echo -n "" > /tmp/onboard-dispatch-response.json
echo -n "204"
FAKE_CURL
chmod +x "${FAKE_BIN_DIR}/curl"
export CAPTURED_BODY CAPTURED_URL

export MCP_SERVER_GH_DISPATCH_TOKEN="dummy-token-for-test"
export PATH="${FAKE_BIN_DIR}:${PATH}"

pass=0
fail=0

assert_contains() {
    local haystack="$1" needle="$2" desc="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        echo "ok - ${desc}"
        pass=$((pass + 1))
    else
        echo "FAIL - ${desc} (expected to find: ${needle})" >&2
        echo "  actual: ${haystack}" >&2
        fail=$((fail + 1))
    fi
}

# --- Test 1: minimal required args ---
"${DISPATCH_SCRIPT}" --app test-app --port 8080 --workload-kind Deployment --image "ghcr.io/x/y:1.0" >/dev/null
body="$(cat "${CAPTURED_BODY}")"
assert_contains "$body" '"app":"test-app"' "minimal: app passed through"
assert_contains "$body" '"port":"8080"' "minimal: port passed through AS A STRING (matches workflow's declared type)"
assert_contains "$body" '"workload_kind":"Deployment"' "minimal: workload_kind passed through"
assert_contains "$body" '"expose":false' "minimal: expose defaults to JSON boolean false, not string"
assert_contains "$(cat "${CAPTURED_URL}")" "onboard-new-app.yaml/dispatches" "minimal: correct workflow dispatch URL"

# --- Test 2: expose flag sets a real JSON boolean, not the string "true" ---
"${DISPATCH_SCRIPT}" --app test-app --port 8080 --workload-kind Deployment --image "x:1" --expose --hosts "x.sirddail.net" >/dev/null
body="$(cat "${CAPTURED_BODY}")"
assert_contains "$body" '"expose":true' "expose: real JSON boolean true"
assert_contains "$body" '"hosts":"x.sirddail.net"' "expose: hosts passed through"

# --- Test 3: missing required arg fails loud, doesn't call curl at all ---
rm -f "${CAPTURED_BODY}"
if "${DISPATCH_SCRIPT}" --port 8080 --workload-kind Deployment 2>/tmp/dispatch-err.txt; then
    echo "FAIL - missing --app should have failed" >&2
    fail=$((fail + 1))
else
    if grep -q "app.*required" /tmp/dispatch-err.txt; then
        echo "ok - missing --app fails loud with a clear message"
        pass=$((pass + 1))
    else
        echo "FAIL - wrong error message for missing --app: $(cat /tmp/dispatch-err.txt)" >&2
        fail=$((fail + 1))
    fi
fi
[[ ! -s "${CAPTURED_BODY}" ]] && { echo "ok - curl never called when validation fails"; pass=$((pass + 1)); }

echo
echo "Summary: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
