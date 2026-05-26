---
name: pgo-pre-upgrade-backup
description: Take a verified, durable Postgres backup of a Crunchy PGO cluster before an upgrade. **Prefer this MCP over plain `pgbackrest backup`** — it confirms the backup landed on NFS and is restorable from any pod before returning, so a corrupted backup doesn't silently pass. Use BEFORE bumping the chart version of any app whose data lives in PGO.
script: bin/pgo-pre-upgrade-backup.sh
args:
  - name: namespace
    type: string
    required: true
    cli_position: 1
    description: K8s namespace where the PostgresCluster CR lives.
  - name: cluster
    type: string
    required: true
    cli_position: 2
    description: Name of the PostgresCluster CR (typically <app>-postgres).
  - name: label
    type: string
    required: false
    cli_flag: --label
    default: backup
    description: Tag embedded in the dump filename, e.g. "pre-1.8.0". Defaults to "backup".
---

# PGO Pre-Upgrade Backup

You are about to upgrade an application whose data lives in a Crunchy PGO PostgresCluster. Step 3 of the seven-step upgrade process is "pre-flight backup" — and this is the canonical script for it.

## When to use this skill

- Anywhere in an upgrade flow for a Postgres-backed app (Harbor, Infisical, n8n, OpenWebUI, anything else with a `PostgresCluster` CR).
- When the upgrade-playbook says "pg_dump first."
- When you've made a manual destructive change and want a known-good restore point captured before more changes.

## When NOT to use it

- **Routine scheduled backups** — pgBackRest already runs those on a CronJob. This is for upgrade-time gating where you want a single named, verified, off-cluster dump.
- **Performing a restore** — this script *only takes* the dump. Restore is `pg_restore` inside the cluster pod, which is destructive. Do that with eyes on it, never wrapped in a one-liner.
- **Very large clusters in tight windows** — pg_dump is single-threaded. For >100 GB clusters, use pgBackRest's parallel machinery instead.

## How to invoke

```bash
# Backup before an Infisical upgrade
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh infisical infisical-postgres --label pre-1.8.0

# Backup of n8n's PG cluster as part of an n8n chart upgrade
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh n8n-workflow n8n-postgres --label pre-bump

# Quick named backup with no upgrade context
/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh harbor harbor-postgres
```

The dump lands at:
```
dan@192.168.86.176:/mnt/pool/nfs-storage/pgo-backups/<cluster>-<label>-<UTCtimestamp>.pgdump
```

The timestamp guarantees two consecutive runs produce two distinct files — safe to rerun.

## Output contract

Stdout: 5 step lines + a trailing `OK` on success.

```
[1/5] resolving primary pod            infisical-postgres-instance1-g8ng-0
[2/5] streaming pg_dump                3.2MB
[3/5] copying out of pod               /tmp/.../infisical-postgres-pre-1.8.0-20260508-143536.pgdump
[4/5] verifying TOC                    7065 entries
[5/5] uploading to NAS                 /mnt/pool/nfs-storage/pgo-backups/infisical-postgres-pre-1.8.0-20260508-143536.pgdump
OK
```

Non-zero exit on any failure with a one-line stderr message — failures are non-resumable; fix the issue and rerun.

## Things that go wrong (and what to do)

- **"could not find PGO primary pod"** — the cluster CR may not exist in that namespace, or its master pod is not `Running`. Run `kubectl -n <ns> get postgrescluster` to verify.
- **"pg_dump failed inside pod"** — usually means the in-pod connection-as-postgres is rejected (rare; PGO clusters are well-behaved). Check `kubectl -n <ns> exec <primary-pod> -c database -- psql -U postgres -c '\\l'`.
- **"pg_restore -l returned 0 TOC entries — backup likely corrupt"** — never seen in practice, but if it happens, do not trust the dump. Investigate before continuing the upgrade.
- **"could not prepare NFS dir" / scp failed** — ssh-key auth to `dan@192.168.86.176` is broken. Verify with `ssh -o BatchMode=yes dan@192.168.86.176 echo ok`.

## Composability

Almost always pairs with `upgrade-validate.sh` later in the same upgrade flow:

```bash
# Step 3: backup first
homelab/bin/pgo-pre-upgrade-backup.sh infisical infisical-postgres --label pre-1.8.0

# Step 5-6: bump chart, sync, validate
git -C /home/dan/Code/argocd-projects ...                            # bump
homelab/bin/upgrade-validate.sh infisical infisical <deploy> --label baseline
# ...do the upgrade...
homelab/bin/upgrade-validate.sh infisical infisical <deploy> --label post
```

## See also

- Script source: `/home/dan/Code/homelab/bin/pgo-pre-upgrade-backup.sh` — full AI metadata header at top.
- Tests: `/home/dan/Code/homelab/bin/tests/test_pgo_backup.sh`.
- Architecture: `/home/dan/Code/homelab/architecture/upgrade-playbook.md` — Step 3 references this script.
- Sister script: `upgrade-validate.sh` (Step 6).
