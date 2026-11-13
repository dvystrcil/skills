---
name: pgo-pre-upgrade-backup
description: Take a verified, durable pg_dump of one database in a CloudNativePG (CNPG) cluster to the NAS before an app upgrade. **Prefer this MCP over a hand-run `kubectl exec ... pg_dump`** — it refuses a multi-database cluster unless you name the database, streams the dump out (the CNPG pod's /tmp is read-only), hashes the dump in the pod and re-dumps any copy whose sha256 differs (exec streams here can drop bytes and exit 0), checks the TOC with `pg_restore -l`, and confirms the NAS copy's sha256 before returning, so a partial or corrupt dump can't pass silently. Use BEFORE bumping any app whose data lives in a CNPG Cluster (the "pgo" in the name is historical).
script: bin/pgo-pre-upgrade-backup.sh
args:
  - name: namespace
    type: string
    required: true
    cli_position: 1
    description: Namespace of the CNPG Cluster.
  - name: cluster
    type: string
    required: true
    cli_position: 2
    description: Name of the CNPG Cluster (clusters.postgresql.cnpg.io, typically <app>-postgres).
  - name: label
    type: string
    required: false
    cli_flag: --label
    default: backup
    description: Tag embedded in the dump filename, e.g. "pre-1.8.0". Defaults to "backup".
  - name: db
    type: string
    required: false
    cli_flag: --db
    description: Database to dump. Required when the cluster holds more than one (e.g. owui-postgres holds owui and homelab_memory); run once per database.
---

# Pre-Upgrade Backup (CNPG)

You are about to upgrade an application whose data lives in a CloudNativePG `Cluster`. Step 3 of the seven-step upgrade process is "pre-flight backup", and this is the canonical script for it. The dump restores into **any** Postgres, which makes it the rollback path for an app's schema migration (e.g. n8n 3.x).

The script was written for Crunchy PGO and ported to CNPG in [homelab#2215](https://github.com/dvystrcil/homelab/issues/2215) when PGO was removed (2026-11-12). The name stayed.

## When to use this skill

- Before upgrading any Postgres-backed app (Harbor, Infisical, n8n, OpenWebUI, obico, immich, invidious: anything with a `clusters.postgresql.cnpg.io` CR).
- When the upgrade playbook says "pg_dump first".
- When you've made a manual destructive change and want a known-good restore point captured before more changes.

## When NOT to use it

- **Routine backups**: every Cluster already ships WAL + base backups through the barman-cloud plugin.
- **PG major upgrades**: those are gated on an on-demand CNPG Barman `Backup` ([homelab#2064](https://github.com/dvystrcil/homelab/issues/2064)), not on this dump. Taking this dump as well is harmless.
- **Performing a restore**: this script only takes the dump. Restore is `pg_restore` into the primary, which is destructive; do it with eyes on it (homelab `architecture/disaster-recovery.md` §6c).
- **Very large databases in tight windows**: pg_dump is single-threaded and streams through `kubectl exec`.

## How to invoke

```bash
# n8n before the 3.x upgrade
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh n8n-workflow n8n-postgres --label pre-3.0

# A multi-database cluster: once per database
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh open-webui owui-postgres --db owui --label pre-bump
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh open-webui owui-postgres --db homelab_memory --label pre-bump
```

The dump lands at:
```
dan@192.168.86.176:/mnt/pool/nfs-storage/pgo-backups/<cluster>-<db>-<label>-<YYYYMMDD-HHMMSS>.pgdump
```

The timestamp guarantees two consecutive runs produce two distinct files, so it is safe to rerun.

## What it does

1. Primary: `cnpg.io/cluster=<cluster>,cnpg.io/instanceRole=primary`, Running.
2. Databases: read from the live `pg_database`, not the Cluster spec (owui's `homelab_memory` was created with SQL, so no CR names it). More than one and no `--db` → refused, naming them. `--db` naming one that isn't there → refused.
3. `pg_dump -Fc` in the `postgres` container as the `postgres` OS user over the local socket. No Secret is read: every Cluster has `enableSuperuserAccess: false`. The dump **streams on stdout** to a local temp dir; nothing is written in the pod. The pod hashes what it wrote (`tee | sha256sum` → stderr); a local copy with another sha256, or with no hash, is re-dumped up to `PGO_BACKUP_ATTEMPTS` (default 3) times, `PGO_BACKUP_RETRY_SLEEP` (10 s) apart. `kubectl exec` streams on this cluster can drop bytes and still exit 0 (homelab#2215, homelab#2225), so rc alone proves nothing.
4. `PGDMP` magic bytes, then `pg_restore -l` in the pod with the file on stdin (the pod drains the rest of stdin, so a dump bigger than a pipe buffer doesn't fail kubectl).
5. scp to the NAS, then the NAS-side sha256 must match.

## Output contract

Stdout: 5 step lines + a trailing `OK` on success.

```
[1/5] resolving primary pod            n8n-postgres-1
[2/5] streaming pg_dump                161MB sha256 812c14303e57… (attempt 1)
[3/5] checking dump file               /tmp/tmp.XXXX/n8n-postgres-n8n-pre-3.0-20261113-120000.pgdump
[4/5] verifying TOC                    812 entries
[5/5] uploading to NAS                 /mnt/pool/nfs-storage/pgo-backups/n8n-postgres-n8n-pre-3.0-20261113-120000.pgdump
OK
```

Non-zero exit on any failure with a one-line stderr message. Failures are not resumable: fix the issue and rerun.

## Things that go wrong (and what to do)

- **"CNPG Cluster '…' not found"**: wrong namespace or name. `kubectl get clusters.postgresql.cnpg.io -A`.
- **"no Running CNPG primary pod"**: the cluster is failing over or down. `kubectl -n <ns> get pods -l cnpg.io/cluster=<cluster>`.
- **"holds more than one database"**: pass `--db`, once per database listed in the message.
- **"pg_dump failed inside pod"**: the message carries pg_dump's own stderr (homelab#405). If it is `terminating connection due to administrator command` mid-`COPY` on an otherwise healthy cluster, don't loop on it. Take an on-demand Barman `Backup` instead (server-side, no client COPY) and confirm it reaches `completed`:
  ```bash
  kubectl -n <ns> apply -f - <<EOF
  apiVersion: postgresql.cnpg.io/v1
  kind: Backup
  metadata: {name: <cluster>-pre-upgrade-$(date +%s), namespace: <ns>}
  spec: {cluster: {name: <cluster>}, method: plugin, pluginConfiguration: {name: barman-cloud.cloudnative-pg.io}}
  EOF
  kubectl -n <ns> get backups.postgresql.cnpg.io -w
  ```
  Unlike the dump, that backup restores only into the same PG major.
- **"pg_restore -l returned 0 TOC entries"**: do not trust the dump. Investigate before continuing the upgrade.
- **"could not prepare NAS dir" / scp failed**: ssh-key auth to `dan@192.168.86.176` is broken. Check with `ssh -o BatchMode=yes dan@192.168.86.176 echo ok`.

## Composability

Almost always pairs with `upgrade-validate.sh` later in the same upgrade flow:

```bash
# Step 3: backup first
homelab/bin/pgo-pre-upgrade-backup.sh infisical infisical-postgres --label pre-1.8.0

# Step 5-6: bump, sync, validate
homelab/bin/upgrade-validate.sh infisical infisical <deploy> --label baseline
# ...do the upgrade...
homelab/bin/upgrade-validate.sh infisical infisical <deploy> --label post
```

## See also

- Script source: `homelab/bin/pgo-pre-upgrade-backup.sh` (AI metadata header at the top). `bin/pgo-pre-upgrade-backup.sh` in this repo is the dispatcher's copy; sync it from homelab.
- Tests: `homelab/bin/tests/test_pgo_backup.sh`. Hermetic in CI; real CNPG via `homelab/lab/cnpg-pre-upgrade-backup/run.sh test`.
- Restore: `homelab/architecture/disaster-recovery.md` §6c.
- Playbooks: `homelab/architecture/upgrade-playbook.md` (Step 3) and `postgres-upgrade-playbook.md` (§3, §Rollback).
