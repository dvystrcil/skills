---
name: upgrade-validate
description: Run the standard 6-test TDD validation suite against a service. Designed to be run identically before AND after an upgrade so the output can be diffed; same exit code, same shape. Step 6 of the seven-step upgrade process.
script: bin/upgrade-validate.sh
args:
  - name: argo_app
    type: string
    required: true
    cli_position: 1
    description: ArgoCD Application name (in argocd ns).
  - name: namespace
    type: string
    required: true
    cli_position: 2
    description: K8s namespace where the Deployment lives.
  - name: deployment
    type: string
    required: true
    cli_position: 3
    description: Deployment name to validate.
  - name: label
    type: string
    required: false
    cli_flag: --label
    description: Tag printed in output (no semantic effect — just for diffing baseline vs post).
  - name: probe_path
    type: string
    required: false
    cli_flag: --probe-path
    default: /api/status
    description: HTTP path for the T3 probe.
  - name: service
    type: string
    required: false
    cli_flag: --service
    description: Service name override (default same as deployment).
  - name: probe_port
    type: integer
    required: false
    cli_flag: --probe-port
    description: Force a specific port for T3 (default first port on the Service).
  - name: extra_check
    type: string
    required: false
    cli_flag: --extra-check
    description: Custom T6 check command; treated as PASS if exit 0.
---

# Upgrade Validate

You are validating a service's basic health — usually as part of an upgrade flow, sometimes for ad-hoc spot-checking. The script's job is to run a fixed 6-test suite and produce a stable, diff-able output.

## When to use this skill

- **Before** a chart bump, with `--label baseline`, to confirm the service is healthy and capture the pre-state.
- **After** the chart bump syncs, with `--label post`, to confirm the upgrade didn't regress anything. Diff the two outputs.
- For ad-hoc spot-checks of a service's health. The script is read-only and idempotent — safe on heavily-loaded services.

## When NOT to use it

- **As the only sign-off on an upgrade.** T1..T5 cover the "is it serving requests" surface. They do NOT verify functional correctness (logging in, reading a secret, pushing an image). Pair with an app-specific functional smoke test.
- **For services without an HTTP endpoint.** T3 will fail unless `--probe-path` points at something the service serves.
- **For services without a Deployment.** T2 expects a Deployment with `readyReplicas/replicas`. StatefulSets etc. need a v2 generalization.

## How to invoke

```bash
# Baseline run, before bumping Infisical chart
homelab/bin/upgrade-validate.sh infisical infisical \
  infisical-infisical-standalone-infisical \
  --label baseline

# Same args after the chart bump syncs
homelab/bin/upgrade-validate.sh infisical infisical \
  infisical-infisical-standalone-infisical \
  --label post

# Diff them — same output shape, identical positions
diff baseline.out post.out

# With a custom T6 check (e.g. "an InfisicalSecret consumer is Ready")
homelab/bin/upgrade-validate.sh infisical infisical \
  infisical-infisical-standalone-infisical \
  --extra-check "kubectl -n arc-runner get infisicalsecret arc-runner-infisical-secret \
    -o jsonpath='{.status.conditions[?(@.type==\"secrets.infisical.com/ReadyToSyncSecrets\")].status}' | grep -q True"

# Override the probe path / port / Service name when the defaults don't fit
homelab/bin/upgrade-validate.sh n8n n8n-workflow n8n \
  --probe-path /healthz --probe-port 5678
```

## Output contract

Stable enough that two runs are diff-able with `diff`:

```
T1 (Argo Synced|Healthy)         : PASS  Synced|Healthy
T2 (Deploy 2/2 ready)            : PASS  2/2
T3 (HTTP /api/status = 200)      : PASS  200
T4 (>=1 200-OK in last 60s)      : PASS  18
T5 (0 ERR/FATAL in last 15m)     : PASS  0
T6 (custom check)                : SKIP  (no --extra-check)
RESULT: PASS (5/5 hard, 1 skip) [baseline]
```

Exit 0 if every hard test passes (T6 SKIP is fine); non-zero if any hard test FAILs or `--extra-check` was supplied and T6 FAILs.

## Things that go wrong (and what to do)

- **T1 FAIL with `OutOfSync|Healthy`** — Argo sees a difference between desired and live state. Common cause: a Helm chart with a `now()` annotation (the Infisical chart does this; see `homelab/architecture/upgrade-playbook.md` for the `ignoreDifferences` workaround). Investigate; this often pre-existed and just got noticed.
- **T2 FAIL with `0/N`** — Deployment isn't rolled out yet, or the new replicas are crashing. Check `kubectl rollout status deploy/<deploy>` and pod events.
- **T3 FAIL** — service unreachable. Verify the Service exists and the probe path is right. Some services use `/healthz`, some `/api/status`, some `/health`. Pass `--probe-path` if the default is wrong.
- **T4 FAIL** — no 200-OK responses in the last 60s. If the service is genuinely idle (no traffic), that's expected; this test isn't useful for low-traffic services. Skip with a wrapper or pass `--extra-check 'true'` to ensure overall PASS.
- **T5 FAIL** — recent ERROR/FATAL/PANIC in logs. Read them. The grep is intentionally broad; false positives happen.

## Composability

```bash
# Pre-flight: backup + baseline validation
homelab/bin/pgo-pre-upgrade-backup.sh infisical infisical-postgres --label pre-1.8.0 \
  || exit 1
homelab/bin/upgrade-validate.sh infisical infisical \
  infisical-infisical-standalone-infisical --label baseline \
  || exit 1

# ...do the upgrade (chart bump, git push, argo sync)...

# Post: validate again
homelab/bin/upgrade-validate.sh infisical infisical \
  infisical-infisical-standalone-infisical --label post \
  || exit 1

# If both validations pass and the diff is clean, the upgrade is safe.
```

## See also

- Script source: `/home/dan/Code/homelab/bin/upgrade-validate.sh` — full AI metadata header at top.
- Tests: `/home/dan/Code/homelab/bin/tests/test_upgrade_validate.sh`.
- Architecture: `/home/dan/Code/homelab/architecture/upgrade-playbook.md` — Step 6 references this script.
- Sister script: `pgo-pre-upgrade-backup.sh` (Step 3).
