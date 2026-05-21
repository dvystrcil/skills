#!/usr/bin/env bash
# Integration test: scaffolded MCP tool inserts into the homelab_memory
# Postgres table with correct (user_id, domain, name, type) scope.
#
# Prereq: PG_URI env var pointing at the homelab_memory database. Local
# dev: kubectl port-forward svc/owui-postgres-pgbouncer 5432:5432 -n
# open-webui, then export PG_URI from secret owui-postgres-pguser-homelab.
#
# This test is the AC2/AC3 deliverable for homelab#161 — the primitive
# the OWUI bridge Function (Tool type) will call once shape 1 is ratified.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAVE_SCRIPT="${SCRIPT_DIR}/bin/homelab-memory-pg.sh"

if [[ -z "${PG_URI:-}" ]]; then
  echo "FAIL: PG_URI must be set (postgres://user:pass@host:port/homelab_memory)" >&2
  exit 1
fi

# Defense (mirrors the script): Infisical UI soft-wraps long URIs into
# the stored value sometimes; URIs have no legitimate whitespace.
PG_URI="${PG_URI//[[:space:]]/}"
export PG_URI

if [[ ! -x "${SAVE_SCRIPT}" ]]; then
  echo "FAIL: ${SAVE_SCRIPT} not found or not executable" >&2
  exit 1
fi

# Unique per-run name so concurrent runs don't collide.
RUN_ID="test-$(date +%s)-$$"
FIXTURE_NAME="homelab-memory-pg-test-${RUN_ID}"
FIXTURE_TYPE="user"
FIXTURE_USER="test-user-${RUN_ID}"
FIXTURE_DOMAIN="test-domain-${RUN_ID}"
FIXTURE_BODY="integration-test body for ${RUN_ID}"

cleanup() {
  psql "${PG_URI}" -c "DELETE FROM homelab_memory WHERE name = '${FIXTURE_NAME}'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Invoking save script (positional argv matches dispatcher cli_position convention)"
echo "${FIXTURE_BODY}" | "${SAVE_SCRIPT}" save \
  "${FIXTURE_TYPE}" \
  "${FIXTURE_NAME}" \
  "${FIXTURE_USER}" \
  "${FIXTURE_DOMAIN}"

echo "==> Verifying row in homelab_memory"
row=$(psql "${PG_URI}" -At -F'|' -c \
  "SELECT type, name, user_id, domain, body FROM homelab_memory WHERE name = '${FIXTURE_NAME}'")

if [[ -z "${row}" ]]; then
  echo "FAIL: no row found for name=${FIXTURE_NAME}"
  exit 1
fi

IFS='|' read -r got_type got_name got_user got_domain got_body <<<"${row}"

assert() {
  local label="$1" expected="$2" actual="$3"
  if [[ "${expected}" != "${actual}" ]]; then
    echo "FAIL: ${label}: expected '${expected}', got '${actual}'"
    exit 1
  fi
  echo "    ✓ ${label} = ${actual}"
}

assert "type"     "${FIXTURE_TYPE}"   "${got_type}"
assert "name"     "${FIXTURE_NAME}"   "${got_name}"
assert "user_id"  "${FIXTURE_USER}"   "${got_user}"
assert "domain"   "${FIXTURE_DOMAIN}" "${got_domain}"
assert "body"     "${FIXTURE_BODY}"   "${got_body}"

echo
echo "==> Re-running same save to verify idempotent upsert (no duplicate)"
echo "${FIXTURE_BODY}" | "${SAVE_SCRIPT}" save \
  "${FIXTURE_TYPE}" \
  "${FIXTURE_NAME}" \
  "${FIXTURE_USER}" \
  "${FIXTURE_DOMAIN}"

count=$(psql "${PG_URI}" -At -c "SELECT COUNT(*) FROM homelab_memory WHERE name = '${FIXTURE_NAME}'")
assert "row count after second save" "1" "${count}"

echo
echo "PASS"
