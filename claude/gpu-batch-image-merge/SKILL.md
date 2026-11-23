---
name: gpu-batch-image-merge
description: Tell the owner (only) when a gpu-batch image bump PR (dvystrcil/gpu-batch "deploy: gpu-batch-blender gpu-batch-freecad <ver>", opened by the CI bot because AUTO_DEPLOY is false) is safe to merge — green, and no batch Job or chain step in flight. Use at every status report, before submitting batch-lane work, and when a chain finishes; never merge it yourself.
script: null
args: []
---

# gpu-batch-image-merge

The CI bot opens a `deploy:` PR in `dvystrcil/gpu-batch` for each new
gpu-batch-docker release (example: dvystrcil/gpu-batch#56, 0.0.33 -> 0.0.34).
It only bumps `newTag` in `overlays/kustomization.yaml`. Once it's merged,
Argo CD rolls the CronJob templates, and `gpu-batch-submit.py` and n8n read
the image off the live CronJob **each time they make a Job**. So:

- a Job that is running keeps its old image (harmless);
- a chain whose later steps haven't started yet gets them on the **new**
  image: one refresh run on two images, and its report names both.

A good time to merge = the PR is green and cleanly mergeable, **and** the lane
is idle: no active Job (the watchdog CronJob doesn't count) and no chain step
waiting to start.

## Check

```bash
python3 ~/.claude/skills/gpu-batch-image-merge/bin/merge_window.py      # one line + the PR links
python3 ~/.claude/skills/gpu-batch-image-merge/bin/merge_window.py --json
```

Exit 0 READY, 1 WAIT (it says why), 2 nothing to merge, 3 couldn't read the
cluster or GitHub (say so; don't guess). Read-only: it never merges or cancels.

## When to run it

- At every status report or step summary in any session (alongside checking
  which of my PRs got merged).
- When a batch chain I submitted finishes (its GitHub comment lands, or
  `gpu-batch-submit.py status <id>` shows the last step done).
- Before submitting new batch-lane work while a deploy PR is open: **don't hold
  work back for it.** Merging can wait (owner, 2026-11-23: "unless you need that
  image to do work, merging can wait"). Only if the work needs the new image,
  say so and ask for the merge first.

## What to tell the owner

- **READY:** one line with the PR link, e.g. "gpu-batch#56 (0.0.34) is green
  and the lane is idle: a good time to merge." Add what the release changes,
  from the gpu-batch-docker release notes
  (`gh release view v<ver> -R dvystrcil/gpu-batch-docker`).
- **WAIT:** say nothing unless they ask. "All I need to know is when it's OK"
  (owner): no cancelling Jobs or pausing work to open the window.
- Several deploy PRs open: the newest supersedes the rest. Say so, and close
  the older ones with a comment pointing at the newest (they're bot PRs for
  the same file).

## Don't

- Merge it yourself: the owner merges (vt350/homelab working rule).
- Treat an old `"state": "running"` status.json as in flight: the check goes
  by the cluster's active Jobs; step dirs without a status count only when
  younger than 24 h and their chain has no failed step.
- Cancel the owner's or my running Jobs to open the window.
