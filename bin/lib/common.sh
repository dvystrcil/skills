#!/bin/bash
# Shared helpers for homelab/bin/ scripts.
# Source this from each script: . "$(dirname "$0")/lib/common.sh"

# Strict mode by default. Each script can opt out individually.
set -euo pipefail

# ---- output --------------------------------------------------------------

# log_step <step-num> <total> <label> <value>
# Renders one line of the contracted progress format used by both scripts:
#   [1/5] resolving primary pod ............ infisical-postgres-instance1-g8ng-0
log_step() {
    local n=$1 total=$2 label=$3 value=$4
    # left-pad label to a fixed width so trailing dots line up
    printf '[%d/%d] %-32s %s\n' "$n" "$total" "$label" "$value"
}

# log_info <msg>
# Diagnostic line that doesn't fit the step format. Goes to stderr so it
# doesn't pollute the script's machine-parseable stdout contract.
log_info() {
    echo "  $*" >&2
}

# err <msg>
# Print to stderr and exit non-zero. Used for fatal errors.
err() {
    echo "ERROR: $*" >&2
    exit 1
}

# require <name> [<install-hint>]
# Assert a command is on PATH. Useful at the top of each script so missing
# tools fail fast with a clear message instead of a cryptic later error.
require() {
    local cmd=$1
    local hint=${2:-}
    if ! command -v "$cmd" >/dev/null 2>&1; then
        err "required command not found: $cmd${hint:+ (}${hint:-}${hint:+)}"
    fi
}

# ---- argument parsing ---------------------------------------------------

# usage_and_exit <usage-string>
# Print a usage block and exit non-zero. Used by --help flag handlers.
usage_and_exit() {
    cat <<EOF >&2
$1
EOF
    exit 0
}

# ---- testing helpers (used by tests/, not by the scripts themselves) ----

# assert_equals <expected> <actual> <description>
# Exits non-zero on mismatch with a clear diff.
assert_equals() {
    local expected=$1 actual=$2 desc=$3
    if [ "$expected" != "$actual" ]; then
        echo "FAIL: $desc" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        return 1
    fi
}

# assert_contains <substring> <haystack> <description>
assert_contains() {
    local needle=$1 hay=$2 desc=$3
    if [[ "$hay" != *"$needle"* ]]; then
        echo "FAIL: $desc" >&2
        echo "  expected substring: $needle" >&2
        echo "  in:                 $(echo "$hay" | head -c 200)..." >&2
        return 1
    fi
}

# assert_exit_nonzero <command...>
# Runs the command and asserts it returned non-zero. Used to test
# bad-input paths.
assert_exit_nonzero() {
    if "$@" >/dev/null 2>&1; then
        echo "FAIL: expected non-zero exit from: $*" >&2
        return 1
    fi
}
