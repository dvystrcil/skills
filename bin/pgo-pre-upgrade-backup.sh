#!/bin/bash
# pgo-pre-upgrade-backup.sh
#
# Pg_dump one database of a CloudNativePG (CNPG) cluster to the NAS as a
# verified backup. (The "pgo" in the name is historical: it was written for
# Crunchy PGO, which was removed on 2026-11-12. homelab#2215 ported it to
# CNPG and kept the name, which the pgo-pre-upgrade-backup skill and the
# dvystrcil/skills dispatcher copy call.)
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Take a verified, durable logical backup (pg_dump -Fc) of
#                   one database in a CNPG Cluster before an app upgrade.
#                   The dump lands on the NAS, so it survives the cluster
#                   and restores into ANY Postgres -- the rollback path for
#                   app schema migrations (architecture/postgres-upgrade-
#                   playbook.md).
#
#   when_to_use   : Step 3 of the seven-step upgrade process for any app
#                   whose data lives in a CNPG Cluster (Harbor, Infisical,
#                   n8n, OpenWebUI, ...). Run BEFORE bumping the app.
#
#   when_not_to_use:
#                 : - Routine backups: each Cluster already ships WAL + base
#                     backups through the barman-cloud plugin. This is the
#                     upgrade-time, named, verified, off-cluster dump.
#                   - PG MAJOR upgrades: those are gated on a CNPG Barman
#                     `Backup` (homelab#2064), not on this dump.
#                   - Restore: this script does NOT restore. pg_restore is
#                     destructive; do it by hand with eyes on it.
#                   - >100 GB databases in a tight window: pg_dump is
#                     single-threaded and streams through `kubectl exec`.
#
#   input         : Two positional args:
#                     <namespace>     - namespace of the CNPG Cluster.
#                     <cluster-name>  - the Cluster's name (`<app>-postgres`).
#                   Optional flags:
#                     --label <suffix> - embedded in the dump filename
#                                        ("pre-1.8.0"). Default "backup".
#                     --db <database>  - required when the cluster holds more
#                                        than one database.
#
#   output        : Stdout: 5 contracted progress lines + trailing 'OK'.
#                     [1/5] resolving primary pod ............ <pod>
#                     [2/5] streaming pg_dump ................ <size>
#                     [3/5] checking dump file ............... <local-path>
#                     [4/5] verifying TOC .................... <N> entries
#                     [5/5] uploading to NAS ................. <nfs-path>
#                     OK
#                   Stderr: error messages.
#                   Side: a .pgdump file at
#                     dan@192.168.86.176:/mnt/pool/nfs-storage/pgo-backups/
#                     <cluster>-<db>-<label>-<timestamp>.pgdump
#
#   exit_codes    : 0 on success. Non-zero with a single-line stderr
#                   message on: missing args, no such Cluster, no primary,
#                   ambiguous/unknown database, pg_dump failure, bad magic
#                   bytes, TOC verification failure, NAS upload failure,
#                   NAS-side size mismatch.
#
#   side_effects  : - `kubectl exec` pg_dump in the primary's `postgres`
#                     container (CPU + I/O on that pod). The dump streams on
#                     stdout into a local mktemp dir (removed on EXIT): the
#                     CNPG pod's /tmp is read-only, so nothing is written in
#                     the pod and there is no `kubectl cp`.
#                   - `kubectl exec -i` pg_restore -l, the local file on
#                     stdin (the host has no pg_restore).
#                   - ssh + scp to the NAS (ssh-key auth needed).
#                   - Timestamped filename: reruns never clobber.
#
#   requires      : kubectl (get clusters.postgresql.cnpg.io + pods, exec),
#                   ssh, scp; numfmt optional (size readout).
#                   Connects over the pod's local socket as `postgres` (peer
#                   auth), like every other CNPG tool in bin/. No Secret is
#                   read: every prod Cluster has enableSuperuserAccess=false,
#                   so there is no <cluster>-superuser Secret, and the
#                   <cluster>-app role cannot read every object.
#
#   safe_in_dry_run:
#                 : No --dry-run. Closest: `kubectl -n <ns> get pod -l
#                   cnpg.io/cluster=<c>,cnpg.io/instanceRole=primary`.
#
#   composable_with:
#                 : - homelab/bin/upgrade-validate.sh (Step 6).
#                   - architecture/upgrade-playbook.md (Step 3 = this).
#
#   tests         : bin/tests/test_pgo_backup.sh -- hermetic tier in CI; the
#                   kind tier via lab/cnpg-pre-upgrade-backup/run.sh test.
#
#   skill_pointer : dvystrcil/skills claude/pgo-pre-upgrade-backup/SKILL.md
#
# === END METADATA ===

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

# Overridable only so the kind test can point the upload at a local dir.
NFS_HOST="${PGO_BACKUP_NFS_HOST:-dan@192.168.86.176}"
NFS_DIR="${PGO_BACKUP_NFS_DIR:-/mnt/pool/nfs-storage/pgo-backups}"

print_usage() {
    cat <<EOF
Usage: pgo-pre-upgrade-backup.sh <namespace> <cluster-name> [--label <suffix>] [--db <database>]

Pg_dump one database of a CloudNativePG cluster to the NAS as a verified backup.

Args:
  <namespace>     namespace of the CNPG Cluster (e.g. n8n-workflow)
  <cluster-name>  name of the CNPG Cluster (e.g. n8n-postgres)

Options:
  --label <suffix>   tag inserted into the dump filename (e.g. pre-1.8.0)
  --db <database>    database to dump. Required when the cluster holds more
                     than one (read live from pg_database, so databases made
                     with plain SQL count); run once per database. The name
                     is always in the dump filename.
  -h, --help         show this help

Example:
  pgo-pre-upgrade-backup.sh n8n-workflow n8n-postgres --label pre-3.0

NAS destination: ${NFS_HOST}:${NFS_DIR}/<cluster>-<db>-<label>-<YYYYMMDD-HHMMSS>.pgdump
EOF
}

# ---- arg parsing ----

set +e
label=""
db=""
positional=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) print_usage; exit 0 ;;
        --label)   label="$2"; shift 2 ;;
        --label=*) label="${1#--label=}"; shift ;;
        --db)      db="$2"; shift 2 ;;
        --db=*)    db="${1#--db=}"; shift ;;
        --*)       err "unknown flag: $1" ;;
        *)         positional+=("$1"); shift ;;
    esac
done
set -e

if [ ${#positional[@]} -lt 1 ]; then
    err "missing required argument: <namespace>. Run with --help for usage."
fi
if [ ${#positional[@]} -lt 2 ]; then
    err "missing required argument: <cluster-name>. Run with --help for usage."
fi

NS=${positional[0]}
CLUSTER=${positional[1]}
LABEL=${label:-backup}
TS=$(date +%Y%m%d-%H%M%S)
LOCAL_DIR=$(mktemp -d)
trap 'rm -rf "$LOCAL_DIR"' EXIT

require kubectl
require scp
require ssh

# ---- step 1: resolve primary pod ----

OUT=$(kubectl -n "$NS" get clusters.postgresql.cnpg.io "$CLUSTER" -o name 2>&1) || \
    err "CNPG Cluster '$CLUSTER' not found in namespace '$NS' (or unauthorized): $OUT"

PRIMARY=$(kubectl -n "$NS" get pod \
    -l "cnpg.io/cluster=${CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>&1) || \
    err "could not list CNPG primary pod for cluster '$CLUSTER' in namespace '$NS': $PRIMARY"
[ -n "$PRIMARY" ] || err "no Running CNPG primary pod for cluster '$CLUSTER' in namespace '$NS'"
log_step 1 5 "resolving primary pod" "$PRIMARY"

pexec() { kubectl -n "$NS" exec "$PRIMARY" -c postgres -- "$@"; }

# ---- choose the database ----

# argocd-projects#310: a cluster can hold several databases (owui-postgres:
# owui + homelab_memory). Dumping only the first and saying nothing about the
# rest made a "verified backup" silently miss data, so fail closed. The list
# comes from the live pg_database, not the Cluster spec: homelab_memory was
# made with plain SQL, so neither bootstrap.initdb nor a Database CR names it.
DBS=$(pexec psql -X -Atq -U postgres -d postgres -c \
    "select datname from pg_database where datallowconn and not datistemplate and datname <> 'postgres' order by 1" 2>&1) || \
    err "could not list databases in pod $PRIMARY: $DBS"
DB_LIST=$(echo $DBS)   # one line, space-separated
if [ -n "$db" ]; then
    grep -qxF -- "$db" <<<"$DBS" || \
        err "cluster '$CLUSTER' has no database '$db' (it holds: ${DB_LIST:-none})"
    DB_NAME=$db
else
    case $(wc -w <<<"$DB_LIST") in
        0) err "cluster '$CLUSTER' holds no application database" ;;
        1) DB_NAME=$DB_LIST ;;
        *) err "cluster '$CLUSTER' holds more than one database ($DB_LIST); pass --db <name>, once per database" ;;
    esac
fi
# The database is always in the name: n8n-postgres-n8n-pre-3.0-<ts>.pgdump
BASE="${CLUSTER}-${DB_NAME}-${LABEL}-${TS}.pgdump"
LOCAL_FILE="$LOCAL_DIR/$BASE"
NFS_FILE="${NFS_DIR}/$BASE"

# ---- step 2: stream pg_dump out of the pod ----

# homelab#405: pg_dump's own stderr goes into the error, never /dev/null; it
# is what told us "terminating connection due to administrator command".
# `|| RC=$?`: under set -e a bare failing command would exit before the
# message (found by T8, 2026-11-07). No -t: a TTY would mangle the binary.
PG_DUMP_RC=0
pexec pg_dump -U postgres -Fc -d "$DB_NAME" > "$LOCAL_FILE" 2> "$LOCAL_DIR/pg_dump.err" || PG_DUMP_RC=$?
[ "$PG_DUMP_RC" -eq 0 ] || \
    err "pg_dump failed inside pod $PRIMARY (db=$DB_NAME): $(tr '\n' ' ' < "$LOCAL_DIR/pg_dump.err" | head -c 500) (rc=$PG_DUMP_RC)"

SIZE=$(stat -c '%s' "$LOCAL_FILE")
HUMAN_SIZE=$(numfmt --to=iec --suffix=B "$SIZE" 2>/dev/null || echo "${SIZE} bytes")
log_step 2 5 "streaming pg_dump" "$HUMAN_SIZE"

# ---- step 3: check the local file ----

[ -s "$LOCAL_FILE" ] || err "dump file is empty: $LOCAL_FILE"
MAGIC=$(head -c 5 "$LOCAL_FILE")
[ "$MAGIC" = "PGDMP" ] || err "dump does not start with PGDMP magic bytes (got '$MAGIC')"
log_step 3 5 "checking dump file" "$LOCAL_FILE"

# ---- step 4: verify the TOC parses ----

# The host has no pg_restore; feed the local file to the pod's on stdin.
# A custom-format TOC sits at the head of the file, so -l needs no seeking.
TOC_OUT=$(kubectl -n "$NS" exec -i "$PRIMARY" -c postgres -- pg_restore -l < "$LOCAL_FILE" 2>&1) || \
    err "pg_restore -l failed: $(echo "$TOC_OUT" | head -1)"
TOC_COUNT=$(grep -cE '^[0-9]+;\s+[0-9]+\s+[0-9]+' <<<"$TOC_OUT" || true)
[ "$TOC_COUNT" -gt 0 ] || err "pg_restore -l returned 0 TOC entries — backup likely corrupt"
log_step 4 5 "verifying TOC" "$TOC_COUNT entries"

# ---- step 5: upload to the NAS ----

ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "mkdir -p '$NFS_DIR'" >/dev/null 2>&1 || \
    err "could not prepare NAS dir at ${NFS_HOST}:${NFS_DIR}"
scp -o BatchMode=yes -o ConnectTimeout=10 -q "$LOCAL_FILE" "${NFS_HOST}:${NFS_FILE}" 2>&1 || \
    err "scp to NAS failed"
NFS_SIZE=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "stat -c '%s' '$NFS_FILE'" 2>/dev/null) || \
    err "could not stat uploaded file on NAS"
[ "$NFS_SIZE" = "$SIZE" ] || err "NAS file size ($NFS_SIZE) does not match the dump ($SIZE)"

log_step 5 5 "uploading to NAS" "$NFS_FILE"
echo "OK"
