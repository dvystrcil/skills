---
name: onboard-new-app
description: Trigger the onboard-new-app.yaml GitHub Actions workflow (dvystrcil/homelab) to generate the full K8s + ArgoCD scaffold for a new app -- namespace, Deployment/StatefulSet, Service, VPA, ImageUpdater CR, ArgoCD AppProject + Application. Opens real PRs across dvystrcil/homelab and dvystrcil/argocd-projects for human review; never merges anything itself. Use whenever asked to onboard, deploy, or scaffold a new app's cluster setup for a repo that already exists under dvystrcil.
script: bin/onboard-new-app-dispatch.sh
args:
  - name: app
    type: string
    required: true
    cli_flag: --app
    description: Git repo name under dvystrcil (must already exist). Always used for repoURL.
  - name: image
    type: string
    required: false
    cli_flag: --image
    description: Full registry/repo:tag, already pinned. Exactly one of image / upstream_repo is required.
  - name: upstream_repo
    type: string
    required: false
    cli_flag: --upstream-repo
    description: owner/repo to resolve a version tag from. Requires image_name too (the Docker image name is not assumed to match the GitHub repo name).
  - name: image_name
    type: string
    required: false
    cli_flag: --image-name
    description: Bare image name (no tag). Required when upstream_repo is given.
  - name: override_name
    type: string
    required: false
    cli_flag: --override-name
    description: Used for generated resource naming; defaults to app. Never affects the git repoURL.
  - name: port
    type: integer
    required: true
    cli_flag: --port
    description: Container port.
  - name: workload_kind
    type: enum
    required: true
    cli_flag: --workload-kind
    values: [Deployment, StatefulSet]
    description: Kubernetes workload kind to generate.
  - name: pvc_size
    type: string
    required: false
    cli_flag: --pvc-size
    description: e.g. "1Gi". Required when workload_kind is StatefulSet.
  - name: namespace
    type: string
    required: false
    cli_flag: --namespace
    description: Defaults to override_name (or app) if not given.
  - name: pull_secret
    type: string
    required: false
    cli_flag: --pull-secret
    description: e.g. pullsecret:<ns>/<name>. Only for private-registry images; omit for public images.
  - name: expose
    type: boolean
    required: false
    cli_flag: --expose
    default: false
    description: Whether the app should be reachable outside the cluster via gateway-services.
  - name: hosts
    type: string
    required: false
    cli_flag: --hosts
    description: Comma-separated *.sirddail.net hostnames. Required when expose is true.
---

# onboard-new-app

Dispatches `onboard-new-app.yaml` in `dvystrcil/homelab` -- the same
`workflow_dispatch` front-end the OWUI-side `trigger_onboarding` Tool
calls (homelab#561), reached here via `mcp-server`'s script-dispatch
mechanism instead, since `mcp-server` isn't one of OWUI's connected MCP
servers but *is* exactly what opencode's `homelab-skills` MCP connects
to (`mcp.sirddail.net`).

No independent design here -- this skill's `args` mirror the workflow's
`workflow_dispatch.inputs` 1:1, which themselves mirror
`bin/onboard-new-app.py`'s CLI flags 1:1. Keep all three in sync; a flag
added to one without the others is drift (same warning the workflow file
gives about itself).

## What actually happens

The dispatch script POSTs a `workflow_dispatch` event to GitHub's REST
API and returns immediately -- it does NOT wait for the workflow to
finish, and does NOT itself validate input combinations (image XOR
upstream_repo, pvc_size-when-StatefulSet, hosts-when-expose) since the
workflow's own "Validate inputs" step already does that and fails loudly
on a bad combination. A dispatch that returns success means "the
workflow started," not "the onboarding succeeded" -- check the run's
step summary (or `gh run list --workflow=onboard-new-app.yaml`) for the
actual PR URLs.

**Never merges anything.** Always report that PRs were opened and need
review, never that the app is "deployed," until a human has merged them.

## When NOT to use this

- The app repo doesn't exist yet -- this tool does not create GitHub
  repos.
- The app is already deployed and something's wrong with it -- this is
  onboarding brand-new apps only, not troubleshooting.
- A hypothetical "what would this do" question -- don't dispatch for that.

## Related

- `dvystrcil/homelab#559` -- the underlying deterministic scaffold
- `dvystrcil/homelab#560` -- the workflow_dispatch front-end this calls
- `dvystrcil/homelab#561` -- the OWUI-side equivalent (`trigger_onboarding`
  Tool) -- different mechanism, same underlying workflow
- `dvystrcil/homelab#601` -- this skill's own build issue
- `dvystrcil/homelab#620` -- follow-up to replace this skill's static PAT
  with dynamically-minted tokens
