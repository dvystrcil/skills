#!/usr/bin/env bash
# homelab-memory-pg — save a fact to the homelab_memory Postgres table.
#
# AC1/AC2 deliverable for homelab#161 Shape 1 (saver-as-MCP-tool).
#
# Compound scope per homelab#96: (user_id, domain). Bridge-injected;
# never model-supplied. The model only ever sees type / name / body.
#
# Invocation (positional argv — see SKILL.md cli_position):
#   echo "<body>" | homelab-memory-pg.sh save <type> <name> <user_id> <domain>
#
# Env: PG_URI must be set to a postgres:// URI for homelab_memory.

set -euo pipefail

die() { echo "FAIL: $*" >&2; exit 1; }

[[ -n "${PG_URI:-}" ]] || die "PG_URI env var not set"

# Defense: long URIs pasted into Infisical's UI sometimes pick up soft-wrap
# newlines that get stored as literal `\n` in the secret. URIs have no
# legitimate whitespace, so strip any before handing to psql.
PG_URI="${PG_URI//[[:space:]]/}"

subcommand="${1:-}"
case "${subcommand}" in
  save)
    shift
    [[ $# -eq 4 ]] || die "save expects 4 args (type name user_id domain), got $#"
    type="$1"; name="$2"; user_id="$3"; domain="$4"

    case "${type}" in
      user|feedback|project|reference) ;;
      *) die "type must be one of: user feedback project reference (got: ${type})" ;;
    esac

    [[ -n "${name}"    ]] || die "name must not be empty"
    [[ -n "${user_id}" ]] || die "user_id must not be empty"
    [[ -n "${domain}"  ]] || die "domain must not be empty"

    body="$(cat)"
    [[ -n "${body}" ]] || die "body must not be empty (read from stdin)"

    # Same upsert SQL as memory_saver_postgres._upsert. The WHERE clause
    # on the UPDATE branch skips no-op writes (same body/type/etc.) so
    # updated_at only moves on real changes.
    psql "${PG_URI}" --quiet --no-psqlrc \
         --set=ON_ERROR_STOP=1 \
         --set=type="${type}" \
         --set=name="${name}" \
         --set=user_id="${user_id}" \
         --set=domain="${domain}" \
         --set=body="${body}" <<'SQL'
INSERT INTO homelab_memory (type, name, description, body, domain, user_id)
VALUES (:'type', :'name', '', :'body', :'domain', :'user_id')
ON CONFLICT (name) DO UPDATE SET
    type        = EXCLUDED.type,
    description = EXCLUDED.description,
    body        = EXCLUDED.body,
    domain      = EXCLUDED.domain,
    user_id     = EXCLUDED.user_id,
    updated_at  = NOW()
WHERE homelab_memory.body        IS DISTINCT FROM EXCLUDED.body
   OR homelab_memory.type        IS DISTINCT FROM EXCLUDED.type
   OR homelab_memory.description IS DISTINCT FROM EXCLUDED.description
   OR homelab_memory.domain      IS DISTINCT FROM EXCLUDED.domain
   OR homelab_memory.user_id     IS DISTINCT FROM EXCLUDED.user_id;
SQL
    ;;

  ""|-h|--help)
    cat <<USAGE
homelab-memory-pg — Postgres-backed memory save (homelab#161 Shape 1)

Usage:
  echo "<body>" | $0 save <type> <name> <user_id> <domain>

  <type>     One of: user, feedback, project, reference
  <name>     Kebab-case slug (UNIQUE inside user_id × domain scope)
  <user_id>  Bridge-injected from __user__.id — NOT model-supplied
  <domain>   Bridge-injected from 4-rule preset resolution

Env:
  PG_URI     Postgres URI for the homelab_memory database
             (read pgbouncer-uri from secret owui-postgres-pguser-homelab)
USAGE
    [[ "${subcommand}" == "" ]] && exit 2 || exit 0
    ;;

  *)
    die "unknown subcommand: ${subcommand} (try --help)"
    ;;
esac
