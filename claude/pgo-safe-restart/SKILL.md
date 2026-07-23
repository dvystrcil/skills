---
name: pgo-safe-restart
description: How to safely restart Patroni/PGO-managed Postgres pods without breaking leader election or the DCS watch. Covers single-instance restarts and multi-replica failover restarts (both validated). Load BEFORE restarting any pod backed by a PostgresCluster CR — including as a side effect of istio ambient enrollment, node draining, or config changes.
---

# PGO Safe Restart

## Why this exists

Patroni (which PGO uses to manage every PostgresCluster, HA or not) holds a
persistent watch on the Kubernetes API as its DCS (distributed configuration
store) — that's how it tracks leadership and cluster topology. Any change
that disrupts an **already-established** long-lived connection to the
apiserver — without the pod restarting — can sever that watch. A restarting
pod re-establishes it cleanly from birth; a pod captured or reconfigured
*in place* while already running does not get that clean slate.

This bit us for real: enrolling `n8n-workflow` in the istio ambient mesh
(`n8n-workflow#97`) captured the running `n8n-postgres` pods in place. That
severed Patroni's DCS watch, no leader got (re-)elected, Postgres went down,
n8n crash-looped. `n8n-workflow#98` reverted it, with the lesson written
into the commit: **restart the pods, don't just label the namespace and
trust in-place capture.**

The general rule is broader than ambient mesh: **any operation that changes
a running pod's network path (CNI changes, mesh enrollment, node
migrations) needs an explicit restart of anything Patroni-managed, never a
"leave it running and see" approach.**

## Before touching anything: know the shape

```bash
kubectl get postgrescluster -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,INSTANCES:.spec.instances[0].replicas
```

- **1 instance** → single-instance restart (see below). No failover
  choreography — the pod just reboots as the same leader.
- **2+ instances** → HA restart (see below). Restarting the leader triggers
  a *real* Patroni failover onto whichever replica is already fresh — this
  is the higher-stakes path and the one that actually broke n8n.

As of the ambient epic (homelab#481): `harbor` and `n8n-workflow` are
2-instance HA. `homeassistant`, `infisical`, `obico`, `open-webui` are
single-instance. Re-check before acting — instance counts change.

## Single-instance restart (validated: `homeassistant`, 2026-07-23)

1. Baseline: `kubectl exec -n <ns> <pg-pod> -c database -- patronictl list` —
   confirm `Leader | running` before you start.
2. Restart order, one at a time, verifying each is healthy before the next:
   stateless app pod → pgbouncer → the Postgres pod itself.
3. `kubectl delete pod` (not `rollout restart` — ArgoCD's `selfHeal` can
   double-roll it; see feedback_argocd_rollout_restart_double_rollout).
4. After the Postgres pod restart, re-run `patronictl list` until it shows
   `Leader | running` again. **Give it real time** — a fresh pod can sit at
   `starting` for a couple of minutes on a transient issue (see Diagnostics
   below) that has nothing to do with the restart itself. Don't roll back
   on `starting` alone; investigate first.
5. Confirm istio-cni actually captured the new pod: `kubectl logs -n
   istio-system <istio-cni-node pod on that node> -c install-cni --since=5m
   | grep <new-pod-name>` — expect `adding pod to the mesh` →
   `Applying iptables chains and rules` → `sending pod add to ztunnel`.

## Multi-replica (HA) restart (validated: `n8n-workflow`, 2026-07-23)

Single-instance restarts don't exercise real failover — this is the part
that actually matches what broke n8n originally.

1. Baseline: `patronictl list` — identify which member is `Leader` and
   which are `Replica`, and each replica's replay lag.
2. **Restart replica(s) first, one at a time.** After each, wait for
   `patronictl list` to show it back as a healthy `Replica` with lag caught
   up (near-zero) before touching the next member. A replica that never
   catches up, or comes back in a bad state (not streaming), is a stop
   signal — do not proceed to the leader.
3. **Restart the leader last.** This is the real failover: Patroni should
   promote the already-fresh replica to `Leader`. On n8n-workflow this was
   fast and clean — the promotion showed up in `patronictl list` within
   one poll of deleting the leader pod. Verify:
   - The new leader shows `Leader | running` with low lag.
   - The old leader (now restarting) rejoins as a healthy `Replica`.
4. If the cluster doesn't reach a clean `Leader | running` + healthy
   replica(s) state within a few minutes, or you see repeated failed
   promotion attempts, stop and consider the rollback below rather than
   retrying blindly.
5. **Restart the application pod too, *after* the failover settles —
   don't assume its in-process connection/scheduler state survived the
   failover just because it never crashed.** On n8n-workflow, the app's
   own health monitor correctly detected the disruption and logged
   `Database connection recovered` — but one in-flight write landed in the
   exact window where it still reconnected to the just-demoted node
   (`cannot execute INSERT in a read-only transaction`), and n8n's internal
   scheduler did not self-heal from that: zero new workflow executions for
   several minutes afterward, with no further errors logged either (it
   wasn't retrying, it was just quiet). Restarting the app pod immediately
   fixed it — two scheduled workflows executed successfully within 90
   seconds of the restart. Treat "the DB layer is healthy again" and "the
   app's in-process state recovered" as two separate things to verify, not
   one — especially for anything with an internal scheduler/cron/queue
   component, which tend to fail differently (and more silently) than a
   simple request-response connection pool.

### Rollback

The proven-good revert (`n8n-workflow#98`): remove the ambient label from
the namespace (revert the enrollment PR/commit) and force-recreate any
stuck pod(s). This is a known-working path — don't hesitate to use it if
the HA restart isn't converging.

## Diagnostics

- **`kubectl logs` on the `database` container is not enough.** PGO/Patroni
  redirects Postgres's actual log output to a log-collector process; the
  stdout you see from `kubectl logs` is Patroni's own chatter (repeated
  `/tmp/postgres:5432 - rejecting connections`, `Lock owner: ...`) and
  misses the real `FATAL`/`ERROR` lines entirely. Read the actual log file:

  ```bash
  kubectl exec -n <ns> <pg-pod> -c database -- tail -60 /pgdata/pg16/log/postgresql-<Day>.log
  ```

  (path/day format may vary by PG major version — `find /pgdata -iname
  '*.log' -newer /tmp -mmin -5` if the exact filename isn't obvious.)

- **A transient DNS resolution failure in a pod's first ~1-3 minutes is not
  unusual and is not necessarily ambient's fault.** Observed on
  `homeassistant`: pgbackrest couldn't resolve the repo-host's DNS name for
  about a minute right after pod start (`HostConnectError... Name or
  service not known`), stalling a WAL-archive-fetch retry — then resolved
  on its own once DNS came up, with zero intervention. Confirm DNS
  currently works (`kubectl exec ... -- getent hosts <name>`) before
  assuming a real breakage.

- **pgbouncer's `server_login_retry` circuit breaker firing during the
  restart window is expected collateral, not a second bug.** You'll see
  client-facing errors like `server login has been failing, try again
  later (server_login_retry)` piling up in the app while Postgres is down
  — that's pgbouncer protecting itself, and it clears on its own once the
  backend is actually reachable again. Don't chase it as a separate issue.

- **Application connection pools (SQLAlchemy and similar) usually recover
  silently** — there's rarely a "reconnected!" log line, only the original
  error followed by silence. Confirm recovery by cross-checking pgbouncer's
  own logs for a fresh successful backend login (`new connection to
  server` → `SSL established` with no subsequent `login failed`), not by
  waiting for app-side confirmation that may never come.

- **For anything with an internal scheduler/cron/queue (n8n, and similar),
  don't trust log silence as proof of recovery — query the actual
  downstream evidence.** Logs alone said nothing was wrong on n8n-workflow
  after the failover (no new errors), but nothing was actually running
  either. What exposed it was querying the app's own execution record
  table directly for anything newer than the failover:

  ```bash
  kubectl exec -n <ns> <pg-pod> -c database -- psql -U postgres -d <db> \
    -c "SELECT id, status, \"startedAt\" FROM execution_entity \
        WHERE \"startedAt\" > now() - interval '5 minutes' \
        ORDER BY \"startedAt\" DESC;"
  ```

  Zero rows for longer than the app's normal schedule interval is the
  actual signal to restart the app pod — not the presence or absence of
  error lines.

## Verification checklist before calling it done

- [ ] `patronictl list` — every member `running`, replicas (if any) at
      near-zero lag
- [ ] No new `FATAL`/`ERROR` lines in the real postgres log file since the
      initial startup window
- [ ] pgbouncer's logs show a clean, recent, successful backend login
- [ ] The actual application works end-to-end (hit its real UI/API — not
      just "pod is Ready")
- [ ] For anything with an internal scheduler/cron/queue: query the app's
      own data for fresh, successful activity since the failover — not
      just an absence of errors in its logs

## Related

- [[git-workflow]] — `kubectl delete pod` over `rollout restart` for
  ArgoCD-managed pods; general restart-and-verify discipline.
- `n8n-workflow#97`/`#98` — the incident and its revert.
- `n8n-workflow#99` — the redo, following this runbook; first validation
  of the HA/failover section.
- `homelab#481` — istio ambient mesh epic; this procedure is a hard
  dependency for enrolling any remaining PostgresCluster-backed namespace
  (`harbor`, `infisical`).
