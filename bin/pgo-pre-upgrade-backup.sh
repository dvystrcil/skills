#!/bin/bash
# pgo-pre-upgrade-backup.sh
#
# Pg_dump a Crunchy PGO cluster's database to NFS as a verified backup.
# Replaces the manual chain of `kubectl exec → kubectl cp → scp →
# pg_restore -l` we used to do by hand.
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Take a verified, durable backup of a single Crunchy PGO
#                   PostgresCluster's database before an upgrade. Backup
#                   ends up on NFS so it survives node failures and is
#                   reachable from any pod for restore.
#
#   when_to_use   : Step 3 of the seven-step upgrade process for any tool
#                   backed by a Crunchy PGO cluster (Harbor, Infisical,
#                   n8n, OpenWebUI, etc). Run BEFORE bumping the chart
#                   version of the consuming app.
#
#   when_not_to_use:
#                 : - Routine ad-hoc backups: PGO already has pgBackRest for
#                     scheduled backups; this is for upgrade-time gating
#                     where you want a single named, verified, off-cluster
#                     dump you can restore from manually.
#                   - Restore: this script does NOT restore. Restore is
#                     pg_restore inside the cluster pod, which is a
#                     destructive operation that should not be wrapped in
#                     a one-liner. Do that manually with eyes on it.
#                   - Backing up large clusters in tight maintenance windows:
#                     pg_dump is single-threaded; for >100 GB clusters,
#                     prefer pgBackRest's parallel backup machinery.
#
#   input         : Two positional args:
#                     <namespace>     - K8s namespace where the
#                                       PostgresCluster CR lives.
#                     <cluster-name>  - The name of the PostgresCluster
#                                       CR (typically `<app>-postgres`).
#                   Optional flags:
#                     --label <suffix> - Embedded in the dump filename;
#                                        use to tag a backup ("pre-1.8.0").
#                                        Defaults to "backup".
#
#   output        : Stdout: 5 contracted progress lines + trailing 'OK'.
#                     [1/5] resolving primary pod ............ <pod>
#                     [2/5] streaming pg_dump ................ <size>
#                     [3/5] copying out of pod ............... <local-path>
#                     [4/5] verifying TOC .................... <N> entries
#                     [5/5] uploading to NAS ................. <nfs-path>
#                     OK
#                   Stderr: log_info diagnostics, error messages.
#                   Side: a .pgdump file at
#                     dan@192.168.86.176:/mnt/pool/nfs-storage/pgo-backups/
#                     <cluster>-<label>-<UTCtimestamp>.pgdump
#
#   exit_codes    : 0 on success. Non-zero with a single-line stderr
#                   message on any of: missing args, no such cluster,
#                   pg_dump failure, copy failure, TOC verification
#                   failure (corrupt dump), NFS upload failure, NFS-side
#                   size mismatch.
#
#   side_effects  : - kubectl exec pg_dump inside the cluster's primary
#                     database container (CPU + I/O on that pod).
#                   - kubectl cp out of the pod into a local mktemp dir
#                     (cleaned up on EXIT regardless of success/failure).
#                   - kubectl cp BACK into the pod for TOC verification,
#                     then rm. The verification path needs pg_restore
#                     which only exists inside the postgres container.
#                   - ssh + scp to dan@192.168.86.176 (NFS host) — needs
#                     ssh-key auth set up beforehand.
#                   - Idempotent: the timestamp in the filename means
#                     two consecutive runs produce two distinct files;
#                     no clobbering or partial-write race.
#
#   requires      : kubectl (read + exec on the namespace), ssh, scp,
#                   numfmt (optional, used only for the size readout).
#                   The PostgresCluster's primary pod must be Running.
#                   The NFS host must accept ssh-key auth from this user.
#
#   safe_in_dry_run:
#                 : No --dry-run flag. The closest equivalent is
#                   `kubectl get postgrescluster -n <ns> <cluster>` to
#                   confirm the resource exists and what its primary pod
#                   selector resolves to.
#
#   composable_with:
#                 : - homelab/bin/upgrade-validate.sh (Step 6 — run
#                     immediately after the upgrade, with --label post,
#                     to confirm the upgrade didn't regress anything).
#                   - The seven-step upgrade process in
#                     architecture/upgrade-playbook.md (Step 3 = this).
#
#   skill_pointer : See ~/.claude/skills/pgo-pre-upgrade-backup/SKILL.md
#                   for the canonical skill description (Claude Code /
#                   opencode-readable).
#
# === END METADATA ===
#
# Usage:
#   pgo-pre-upgrade-backup.sh <namespace> <cluster-name> [--label <suffix>]
#
# Output (machine-parseable contract):
#   [1/5] resolving primary pod ............ <pod-name>
#   [2/5] streaming pg_dump ................ <size>
#   [3/5] copying out of pod ............... <local-path>
#   [4/5] verifying TOC .................... <toc-entries> entries
#   [5/5] uploading to NAS ................. <nfs-path>
#   OK
#
# Exit 0 on success; non-zero on any step failure with a clear message.

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

NFS_HOST="dan@192.168.86.176"
NFS_DIR="/mnt/pool/nfs-storage/pgo-backups"

print_usage() {
    cat <<EOF
Usage: pgo-pre-upgrade-backup.sh <namespace> <cluster-name> [--label <suffix>]

Pg_dump a Crunchy PGO cluster to NFS as a verified backup.

Args:
  <namespace>     namespace where the PostgresCluster lives (e.g. infisical)
  <cluster-name>  name of the PostgresCluster (e.g. infisical-postgres)

Options:
  --label <suffix>   tag inserted into the dump filename (e.g. pre-1.8.0)
  -h, --help         show this help

Example:
  pgo-pre-upgrade-backup.sh infisical infisical-postgres --label pre-1.8.0

NFS destination: ${NFS_HOST}:${NFS_DIR}/<cluster>-<label>-<YYYYMMDD-HHMMSS>.pgdump
EOF
}

# ---- arg parsing ----

# disable -e for the parse loop (we want our own error handling)
set +e

label=""
positional=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) print_usage; exit 0 ;;
        --label)   label="$2"; shift 2 ;;
        --label=*) label="${1#--label=}"; shift ;;
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
LOCAL_FILE="$LOCAL_DIR/${CLUSTER}-${LABEL}-${TS}.pgdump"
NFS_FILE="${NFS_DIR}/${CLUSTER}-${LABEL}-${TS}.pgdump"

require kubectl
require scp
require ssh

# ---- step 1: resolve primary pod ----

# Crunchy PGO labels primary pods with role=master in
# postgres-operator.crunchydata.com group.
PRIMARY=$(kubectl -n "$NS" get pod \
    -l "postgres-operator.crunchydata.com/cluster=${CLUSTER},postgres-operator.crunchydata.com/role=master" \
    -o jsonpath='{.items[0].metadata.name}' 2>&1) || \
    err "could not find PGO primary pod for cluster '$CLUSTER' in namespace '$NS' (NotFound or unauthorized): $PRIMARY"
[ -n "$PRIMARY" ] || err "no PGO primary pod found for cluster '$CLUSTER' in namespace '$NS'"
log_step 1 5 "resolving primary pod" "$PRIMARY"

# ---- step 2: pg_dump in pod ----

# Determine DB name from the cluster spec. PGO's spec.users[].name is the
# USERNAME; the actual database name(s) live in spec.users[].databases[].
# They often match (e.g. owui-postgres has user=database=owui) but Harbor
# differs (user=harbor, database=registry). Prefer databases[0]; fall back
# to name; final fallback is the cluster name.
DB_NAME=$(kubectl -n "$NS" get postgrescluster "$CLUSTER" \
    -o jsonpath='{.spec.users[0].databases[0]}' 2>/dev/null) || true
if [[ -z "$DB_NAME" ]]; then
    DB_NAME=$(kubectl -n "$NS" get postgrescluster "$CLUSTER" \
        -o jsonpath='{.spec.users[0].name}' 2>/dev/null) || true
fi
DB_NAME=${DB_NAME:-$CLUSTER}

# Run pg_dump inside the database container, write to /tmp inside pod.
POD_TMP="/tmp/pgdump-$$.pgdump"
kubectl -n "$NS" exec "$PRIMARY" -c database -- \
    pg_dump -U postgres -Fc -d "$DB_NAME" -f "$POD_TMP" >/dev/null 2>&1 || \
    err "pg_dump failed inside pod $PRIMARY (db=$DB_NAME)"

POD_SIZE=$(kubectl -n "$NS" exec "$PRIMARY" -c database -- \
    stat -c '%s' "$POD_TMP" 2>/dev/null) || err "could not stat dump file inside pod"
HUMAN_SIZE=$(numfmt --to=iec --suffix=B "$POD_SIZE" 2>/dev/null || echo "${POD_SIZE} bytes")
log_step 2 5 "streaming pg_dump" "$HUMAN_SIZE"

# ---- step 3: kubectl cp out ----

kubectl -n "$NS" cp -c database "$PRIMARY:$POD_TMP" "$LOCAL_FILE" >/dev/null 2>&1 || \
    err "kubectl cp out of pod failed"

# Clean up the in-pod temp dump immediately (don't leave behind data).
kubectl -n "$NS" exec "$PRIMARY" -c database -- rm -f "$POD_TMP" >/dev/null 2>&1 || true

# Sanity check the local file
[ -s "$LOCAL_FILE" ] || err "copied dump file is empty or missing: $LOCAL_FILE"

# Verify magic bytes
MAGIC=$(head -c 5 "$LOCAL_FILE")
[ "$MAGIC" = "PGDMP" ] || err "copied dump does not start with PGDMP magic bytes (got '$MAGIC')"

log_step 3 5 "copying out of pod" "$LOCAL_FILE"

# ---- step 4: verify TOC parses ----

# Round-trip through the postgres pod since the host doesn't have pg_restore.
VERIFY_PATH="/tmp/verify-$$-${TS}.pgdump"
kubectl -n "$NS" cp -c database "$LOCAL_FILE" "$PRIMARY:$VERIFY_PATH" >/dev/null 2>&1 || \
    err "kubectl cp back into pod for verification failed"

TOC_OUT=$(kubectl -n "$NS" exec "$PRIMARY" -c database -- \
    pg_restore -l "$VERIFY_PATH" 2>&1) || \
    err "pg_restore -l failed: $(echo "$TOC_OUT" | head -1)"

# Clean up verify file
kubectl -n "$NS" exec "$PRIMARY" -c database -- rm -f "$VERIFY_PATH" >/dev/null 2>&1 || true

TOC_COUNT=$(echo "$TOC_OUT" | grep -cE '^[0-9]+;\s+[0-9]+\s+[0-9]+')
[ "$TOC_COUNT" -gt 0 ] || err "pg_restore -l returned 0 TOC entries — backup likely corrupt"
log_step 4 5 "verifying TOC" "$TOC_COUNT entries"

# ---- step 5: scp to NFS ----

# Ensure the NFS directory exists (idempotent).
ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "mkdir -p '$NFS_DIR'" >/dev/null 2>&1 || \
    err "could not prepare NFS dir at ${NFS_HOST}:${NFS_DIR}"

scp -o BatchMode=yes -o ConnectTimeout=10 -q "$LOCAL_FILE" "${NFS_HOST}:${NFS_FILE}" 2>&1 || \
    err "scp to NFS failed"

# Confirm size on the NFS side matches.
NFS_SIZE=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$NFS_HOST" "stat -c '%s' '$NFS_FILE'" 2>/dev/null) || \
    err "could not stat uploaded file on NFS"
[ "$NFS_SIZE" = "$POD_SIZE" ] || err "NFS file size ($NFS_SIZE) does not match in-pod size ($POD_SIZE)"

log_step 5 5 "uploading to NAS" "$NFS_FILE"
echo "OK"
