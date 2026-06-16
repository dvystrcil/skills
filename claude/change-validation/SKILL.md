---
name: change-validation
description: Validate that a change (upgrade, migration, config bump, refactor of running infra) didn't regress anything by running an IDENTICAL check suite before and after, then diffing the two outputs. Use whenever you're about to change something already in production.
---

# change-validation

The cheapest way to know a change was safe is to prove the system behaves the
same after as before — with checks that are **identical and diffable**, not
eyeballed ad-hoc. Ad-hoc `curl`/`get` spot-checks vary between runs and can't
be compared; a fixed suite run twice can.

## The discipline

1. **Define the suite once, before touching anything.** A small fixed set of
   read-only checks covering "is it healthy and serving" for this service.
   Typical tiers:
   - Deploy/rollout state (desired == ready replicas, no crash loop)
   - GitOps sync + health (if you run GitOps: the app reports Synced/Healthy)
   - A liveness/readiness HTTP probe returns 200
   - Recent success signal (≥1 200-OK in the logs in the last minute)
   - No new ERROR/FATAL in the logs over a recent window
   - An app-specific functional check (login works, a secret is readable, a
     job completes) — the one tier the generic ones can't cover

2. **Capture the baseline.** Run the suite, label it `baseline`, save the output.

3. **Make the change.** Bump the chart/image/config, apply, let it converge.

4. **Re-run the IDENTICAL suite**, label it `post`, save the output.

5. **Diff baseline vs post.** Same checks, same order, same output shape, so a
   plain `diff` surfaces any regression. A clean diff + all-pass is your signal
   the change was safe.

## Rules that make it trustworthy

- **Same suite both times.** If you add or change a check between runs, the diff
  is meaningless. Freeze it before the baseline.
- **Read-only + idempotent.** The suite must be safe to run on a live, loaded
  service and safe to run twice.
- **Stable output shape.** Fixed labels and ordering so `diff` works. Avoid
  timestamps/counters in the lines you diff (or normalize them out).
- **Generic health ≠ functional correctness.** "Serving 200s" does not prove
  "can still log in / read its secret / push an image." Always pair the generic
  tiers with at least one app-specific functional check before sign-off.
- **Pair with a verified backup** for anything with persistent state — validation
  proves *health*, not *recoverability*. Back up first, validate second.

## Anti-patterns

- **Post-only checking** — "it looks up, ship it." Without a baseline you can't
  tell a pre-existing issue from one your change caused.
- **Eyeballing different commands each time** — not diffable; you'll miss the
  subtle regression.
- **Treating green generic tiers as sign-off** — they don't cover functional
  correctness. See the rule above.

> Homelab note: the homelab implements this as the `upgrade-validate` script
> skill (a fixed 6-test suite wired to ArgoCD + a Deployment), paired with
> `pgo-pre-upgrade-backup`. That script is homelab-specific; *this* skill is the
> portable discipline behind it.
