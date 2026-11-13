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
#                     [2/5] streaming pg_dump ................ <size> sha256 <12 hex>… (attempt <n>)
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
#                   NAS-side sha256 mismatch, no sha256-verified dump
#                   after PGO_BACKUP_ATTEMPTS tries.
#
#   side_effects  : - `kubectl exec` pg_dump in the primary's `postgres`
#                     container (CPU + I/O on that pod). The dump streams on
#                     stdout into a local mktemp dir (removed on EXIT): the
#                     CNPG pod's /tmp is read-only, so nothing is written in
#                     the pod and there is no `kubectl cp`. The pod hashes
#                     what it wrote; a local copy with another sha256 is
#                     re-dumped, up to PGO_BACKUP_ATTEMPTS (default 3) times,
#                     PGO_BACKUP_RETRY_SLEEP (10 s) apart: exec streams here
#                     can drop bytes and still exit 0 (homelab#2215).
#                     The remote shell lingers PGO_BACKUP_DRAIN_SECS (30 s)
#                     after pg_dump exits, so a slow reader gets the buffered
#                     tail before kubelet closes the stream (homelab#2225).
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

# ---- step 2: stream pg_dump out of the pod, verified ----

# `kubectl exec` streams on this cluster DROP BYTES AND STILL EXIT 0
# (homelab#2215 AC2 run, 2026-11-13: 100 MiB of zeros arrived as 100.7-104.5
# MB with rc=0 over both SPDY and WebSockets; the first n8n dump came out
# 7.6 MB of an 88 MB database). So rc proves nothing about the bytes. The pod
# hashes the dump as pg_dump writes it (tee -> sha256sum -> stderr, so
# nothing touches the read-only /tmp), and a local copy whose sha256 differs
# -- or that arrives without the digest -- is thrown away and re-dumped.
#
# homelab#405: pg_dump's own stderr goes into the error, never /dev/null.
# `|| RC=$?`: under set -e a bare failing command would exit before the
# message (found by T8, 2026-11-07). No -t: a TTY would mangle the binary.
#
# Drain (homelab#2225): the bytes are lost when the remote process EXITS.
# kubelet then tears the stream down, and whatever is still buffered toward
# a reader slower than pg_dump is dropped. Measured 2026-11-13 from the laptop
# (10 Mb/s link): `head -c 20MiB` arrived short 2/2, while
# `head -c 20MiB; sleep 30` arrived whole 2/2. A fast reader on a CORE host
# drains as it goes and lost nothing. So the remote shell outlives pg_dump by
# PGO_BACKUP_DRAIN_SECS and then exits with pg_dump's status. The sha256 check
# stays: the drain makes success likely, and the hash proves it.
ATTEMPTS=${PGO_BACKUP_ATTEMPTS:-3}
RETRY_SLEEP=${PGO_BACKUP_RETRY_SLEEP:-10}
DRAIN_SECS=${PGO_BACKUP_DRAIN_SECS:-30}
[[ "$DRAIN_SECS" =~ ^[0-9]+$ ]] || err "PGO_BACKUP_DRAIN_SECS must be a whole number of seconds (got '$DRAIN_SECS')"
DUMP_SH="set -o pipefail; { pg_dump -U postgres -Fc -d $(printf %q "$DB_NAME") | tee /dev/fd/4 | sha256sum | sed 's/^/PGB-SHA256 /' >&2; } 4>&1; rc=\$?; sleep $DRAIN_SECS; exit \$rc"
why=""
for attempt in $(seq 1 "$ATTEMPTS"); do
    PG_DUMP_RC=0
    pexec bash -c "$DUMP_SH" > "$LOCAL_FILE" 2> "$LOCAL_DIR/pg_dump.err" || PG_DUMP_RC=$?
    POD_SHA=$(sed -n 's/^PGB-SHA256 \([0-9a-f]\{64\}\).*/\1/p' "$LOCAL_DIR/pg_dump.err" | tail -1)
    LOCAL_SHA=$(sha256sum < "$LOCAL_FILE" | cut -d' ' -f1)
    if [ "$PG_DUMP_RC" -ne 0 ]; then
        # `|| true`: a pg_dump that dies without a word (OOM kill) leaves
        # nothing for grep -v, and under pipefail that exited silently (T16).
        why="pg_dump failed inside pod $PRIMARY (db=$DB_NAME): $({ grep -v '^PGB-SHA256 ' "$LOCAL_DIR/pg_dump.err" || true; } | tr '\n' ' ' | head -c 500) (rc=$PG_DUMP_RC)"
    elif [ -z "$POD_SHA" ]; then
        why="no in-pod sha256 arrived for the dump (the exec stream lost stderr)"
    elif [ "$POD_SHA" != "$LOCAL_SHA" ]; then
        why="sha256 mismatch: pod wrote $POD_SHA, received $LOCAL_SHA ($(stat -c '%s' "$LOCAL_FILE") bytes) -- the exec stream was cut"
    else
        why=""; break
    fi
    echo "  attempt $attempt/$ATTEMPTS: $why" >&2
    if [ "$attempt" -lt "$ATTEMPTS" ]; then sleep "$RETRY_SLEEP"; fi
done
[ -z "$why" ] || err "no verified dump after $ATTEMPTS attempts: $why"

SIZE=$(stat -c '%s' "$LOCAL_FILE")
HUMAN_SIZE=$(numfmt --to=iec --suffix=B "$SIZE" 2>/dev/null || echo "${SIZE} bytes")
log_step 2 5 "streaming pg_dump" "$HUMAN_SIZE sha256 ${LOCAL_SHA:0:12}… (attempt $attempt)"

# ---- step 3: check the local file ----

[ -s "$LOCAL_FILE" ] || err "dump file is empty: $LOCAL_FILE"
MAGIC=$(head -c 5 "$LOCAL_FILE")
[ "$MAGIC" = "PGDMP" ] || err "dump does not start with PGDMP magic bytes (got '$MAGIC')"
log_step 3 5 "checking dump file" "$LOCAL_FILE"

# ---- step 4: verify the TOC parses ----

# The host has no pg_restore; feed the local file to the pod's on stdin.
# A custom-format TOC sits at the head of the file, so -l needs no seeking --
# and that is the trap: pg_restore exits after the TOC while kubectl is still
# pushing the rest, and kubectl then fails although the TOC printed (n8n,
# 7.6 MB, 2026-11-13; the 2.7 KB kind dump fit in one pipe buffer). So the
# pod drains stdin after pg_restore and keeps pg_restore's exit code. The
# stdin direction can still be cut by the network: that read-only check is
# retried. Diagnostics skip TOC lines (`errorMessage` columns matched `error`).
TOC_SH='pg_restore -l; rc=$?; cat >/dev/null; exit $rc'
toc_err() { grep -vE '^[0-9]+;|^;|^$' <<<"$TOC_OUT" | head -1 | head -c 300; }
for attempt in $(seq 1 "$ATTEMPTS"); do
    TOC_RC=0
    TOC_OUT=$(kubectl -n "$NS" exec -i "$PRIMARY" -c postgres -- bash -c "$TOC_SH" < "$LOCAL_FILE" 2>&1) || TOC_RC=$?
    [ "$TOC_RC" -eq 0 ] && break
    echo "  pg_restore -l attempt $attempt/$ATTEMPTS failed (rc=$TOC_RC): $(toc_err)" >&2
    if [ "$attempt" -lt "$ATTEMPTS" ]; then sleep "$RETRY_SLEEP"; fi
done
[ "$TOC_RC" -eq 0 ] || err "pg_restore -l failed (rc=$TOC_RC): $(toc_err)"
TOC_COUNT=$(grep -cE '^[0-9]+;\s+[0-9]+\s+[0-9]+' <<<"$TOC_OUT" || true)
[ "$TOC_COUNT" -gt 0 ] || err "pg_restore -l returned 0 TOC entries — backup likely corrupt"
log_step 4 5 "verifying TOC" "$TOC_COUNT entries"

# ---- step 5: upload to the NAS ----

ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "mkdir -p '$NFS_DIR'" >/dev/null 2>&1 || \
    err "could not prepare NAS dir at ${NFS_HOST}:${NFS_DIR}"
scp -o BatchMode=yes -o ConnectTimeout=10 -q "$LOCAL_FILE" "${NFS_HOST}:${NFS_FILE}" 2>&1 || \
    err "scp to NAS failed"
NFS_SHA=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "sha256sum '$NFS_FILE'" 2>/dev/null | cut -d' ' -f1) || \
    err "could not hash uploaded file on NAS"
[ "$NFS_SHA" = "$LOCAL_SHA" ] || err "NAS file sha256 ($NFS_SHA) does not match the dump ($LOCAL_SHA)"

log_step 5 5 "uploading to NAS" "$NFS_FILE"
echo "OK"
