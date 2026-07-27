---
name: "Onboard New App"
description: "Use the trigger_onboarding tool when the user asks to onboard, deploy, or scaffold a new app's Kubernetes/ArgoCD setup."
tags: ["kubernetes", "argocd", "onboarding", "deployment", "tool-use"]
scope: "task"
---

# onboard-new-app

Use the `trigger_onboarding` tool whenever the user asks to bring a new
Docker image into the cluster — phrases like "onboard X", "deploy X to
the cluster", "set up K8s manifests for X", or "scaffold ArgoCD for X"
all mean this.

## What it actually does

`trigger_onboarding` fires a GitHub Actions workflow
(`onboard-new-app.yaml` in `dvystrcil/homelab`) that generates the full,
correct K8s + ArgoCD shape for the app — namespace, Deployment/StatefulSet,
Service, VPA, ImageUpdater CR, ArgoCD AppProject + Application — and opens
real PRs across `dvystrcil/homelab` and `dvystrcil/argocd-projects` for a
human to review. **It does not merge anything itself** — always tell the
user PRs were opened and need their review, never that the app is
"deployed" until they've merged.

## Required parameters

- `app` — the git repo name (must already exist under `dvystrcil`)
- `port` — the container port
- `workload_kind` — `Deployment` or `StatefulSet`
- Exactly one of `image` (a full, already-pinned `registry/repo:tag`) or
  `upstream_repo` (a GitHub `owner/repo` to resolve a version tag from —
  requires `image_name` too, since the Docker image name is NOT assumed
  to match the GitHub repo name)

## When NOT to use this

- The app repo doesn't exist yet — ask the user to create it first (this
  tool does not create GitHub repos).
- The user is asking about an app that's already deployed (e.g. "why
  isn't X working" or "restart X") — this is onboarding brand-new apps
  only, not troubleshooting existing ones.
- The user just wants to know what the workflow *would* do, without
  actually running it — don't call the tool for a hypothetical question.

## Related

- `dvystrcil/homelab#559` — the underlying deterministic scaffold (`bin/onboard-new-app.py`)
- `dvystrcil/homelab#560` — the workflow_dispatch front-end this tool calls
- `dvystrcil/homelab#561` — this tool's own build issue
- `architecture/owui-extensibility-mechanisms.md` (homelab repo) — why
  this is an OWUI Tool and not a Skill-only or dedicated-MCP-server design
