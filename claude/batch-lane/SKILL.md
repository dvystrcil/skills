---
name: batch-lane
description: Hand long-running, read-only work (FreeCAD runs, vt350 refresh/sweeps, clash checks, Blender renders, anything a session would sit and wait on for minutes) to the cluster batch lane with `homelab/bin/gpu-batch-submit.py` — it returns at once and the result arrives as ONE GitHub comment. Use before running or babysitting such work in the session or on the laptop, and before polling a job.
script: null
args: []
---

# batch-lane

Waiting is the expensive part of a session: every minute spent watching a
FreeCAD sweep or a render costs context, and the laptop does work that
max-01 or the GTX 970 should do. The batch lane takes the work, returns at
once, and posts one comment on an issue when it ends. Decision:
`homelab/architecture/ways-of-working.md` D-038. Pattern and recipes:
`homelab/architecture/n8n-job-chains.md`. Lane design:
`homelab/architecture/gpu-batch-lane.md`.

## Use it when

- the work runs for more than a few minutes, or would need watching;
- it only **reads** its inputs (it writes to its own `out/` only);
- a check can judge it (a log line, outputs that exist, a summary);
- nothing later in this turn needs its answer.

Don't use it for work that writes to a repo or a model file (GUI
model-writing lite-N passes stay on the laptop, homelab#1961 AC9), work
needing a human between steps, or anything quick.

## Commands (run from `~/Code/homelab`)

```bash
# CAD chains (vt350)
bin/gpu-batch-submit.py chain vt350-refresh --model ~/Documents/VT350/vt350-lite-26.FCStd \
    --notify dvystrcil/<repo>#<n>          # derive_stls -> sweep -> print_area (max-01)
bin/gpu-batch-submit.py chain vt350-render --model ~/Documents/VT350/vt350-lite-26.FCStd \
    --extra ~/Documents/VT350/vt350-ebox.FCStd --notify dvystrcil/<repo>#<n>   # export -> Blender
# one Blender render of an export
bin/gpu-batch-submit.py blender --input <export dir> --script <render.py> --notify dvystrcil/<repo>#<n> -- <args>

# add --dry-run to see the job dirs and request without starting anything
bin/gpu-batch-submit.py status <job-id>   # read ONCE, later. exit 0 ok, 1 failed, 2 running, 3 refused, 4 none
```

Prerequisites: the TrueNAS media share mounted at `/mnt/nfs/media`, prod
kubectl rights (they mint the per-run token), and the Infisical login (the
webhook secret). `--help` on each subcommand lists deadlines and options.

## After submitting

1. Tell the user the chain/job id and where the comment will land
   (`--notify`), then **end the turn**. Don't loop on `status`, `kubectl get
   jobs`, or `sleep`.
2. The result is the comment on `--notify`. A webhook 202 only means
   "started". The comment says succeeded with outputs, or which step failed
   with its log tail.
3. Read the comment (or `status` once) in a later turn or session.

## When no chain fits

Extend the lane rather than run the work in the session, cheapest first
(recipes in `n8n-job-chains.md`):
1. a new **step** in an existing image (a step builder in
   `bin/gpu-batch-submit.py`);
2. a new **chain** over existing templates (a workflow in `n8n-workflow`,
   imported, not synced; a `CHAINS` entry; a case in the kind e2e test);
3. a new **image + template** (`gpu-batch-docker` stage named
   `gpu-batch-<tool>`, a suspended CronJob in `gpu-batch` sized from a
   measured peak, the template name in the step sub-workflow's allowlist,
   which is a held node edit).

If extending is bigger than the task, say so and let the user choose
between running it once in the session and building the step.

## Traps

- Comparing lane output with a laptop run: compare geometry or summaries,
  not bytes. FreeCAD's tessellation differs by CPU (homelab#1961 AC8).
- Inside a pod `os.cpu_count()` is the node's (max-01: 32). Pin workers.
- The report's `image` field is empty for chain jobs until
  dvystrcil/gpu-batch#16 is fixed.
