---
name: n8n-import-workflow
description: Deploy n8n workflow JSONs from a git repo to the running cluster's n8n instance. The canonical "load these workflows" action whenever a new or edited workflow JSON needs to reach n8n — replaces manual UI imports.
---

# n8n Import Workflow

You are deploying n8n workflows from this repo's `n8n-workflow/workflows/` directory (or any directory of valid n8n workflow JSONs) into the running cluster's n8n instance.

This is a *tool skill*, not a behavior skill. When you need to "make n8n run this workflow", invoke the script instead of asking the user to do a UI import.

## When to use this skill

- After editing or creating any file under `/home/dan/Code/n8n-workflow/workflows/`.
- After receiving a freshly-generated workflow JSON from another agent (opencode, future Claude session, the user pasting one in chat).
- During a re-baseline or recovery operation where you want to ensure n8n's database matches the source-of-truth in the git repo.

## When NOT to use it

- **Credential management** — the n8n CLI doesn't manage credentials (httpHeaderAuth, SMTP, OAuth2). Those still require the n8n UI. After importing a workflow that references credentials, the user has to wire them up in the UI before activating.
- **One-off execution** — to run a workflow once, hit its webhook URL or click Execute Workflow in the UI. Don't import-then-deactivate just to run.
- **Modifying an *already active* workflow** — deactivate it first, re-import, reactivate. Editing while active is racy.

## How to invoke

The script lives at `/home/dan/Code/homelab/bin/n8n-import-workflow.sh`.

```bash
# Single file
/home/dan/Code/homelab/bin/n8n-import-workflow.sh /home/dan/Code/n8n-workflow/workflows/cluster_service_health_watcher.json

# Whole directory (non-recursive — only top-level *.json)
/home/dan/Code/homelab/bin/n8n-import-workflow.sh /home/dan/Code/n8n-workflow/workflows/

# With activation (workflow becomes Active immediately on success)
/home/dan/Code/homelab/bin/n8n-import-workflow.sh \
  /home/dan/Code/n8n-workflow/workflows/foo.json --activate
```

The script does the kubectl-cp-into-pod + `n8n import:workflow` + `n8n list:workflow` verification dance. Idempotent — running it twice with the same file safely overwrites in place.

## Output contract

Stdout is machine-parseable. Three step lines + a trailing `OK` on success:

```
[1/3] resolving n8n pod ............... n8n-7f9f58c54d-c784q
[2/3] importing 1 workflow(s) ......... cluster_service_health_watcher.json
[3/3] verifying via list:workflow ..... EluoBiukIklrRjG6|Cluster Service Health Watcher
OK
```

Non-zero exit on any failure with a one-line error to stderr. Failures are non-resumable — fix the reported issue and re-run.

## Things that go wrong (and what to do)

- **"no Running pod found"** — n8n itself is down or in mid-rollout. Run `kubectl -n n8n-workflow get pods -l app=n8n` and either wait for it to come back up, or investigate why it isn't.
- **"n8n import did not report success"** — the workflow JSON is probably malformed (missing required fields, invalid node connections). Validate locally with `jq . workflow.json >/dev/null` first.
- **Workflow imports but doesn't appear in n8n UI** — refresh the browser; n8n caches the workflow list client-side. The CLI's `list:workflow` is the source of truth.
- **Activation fails after import** — the workflow is referencing a credential by ID that doesn't exist in this n8n instance. Wire the credential in the UI, then activate (manually or re-run with `--activate`).

## Composability

After importing, the workflow may have a scheduled trigger. To verify it's behaving:

- Check the n8n executions tab in the UI.
- Or run `homelab/bin/upgrade-validate.sh <argo-app> <ns> <deploy>` to confirm the cluster state the workflow probes is what you expect.
- Or hit the workflow's webhook (if it has one) to fire a test execution.

## See also

- Script source: `/home/dan/Code/homelab/bin/n8n-import-workflow.sh` (has full AI-readable header at top of file).
- Tests: `/home/dan/Code/homelab/bin/tests/test_n8n_import.sh`.
- Architecture: `/home/dan/Code/homelab/architecture/local-ai-stack.md` — Tier 3 (operational autonomous workflows) is the broader context this script enables.
- Memory: `feedback_n8n_cli_import.md` documents why we use the in-pod CLI rather than the n8n REST API (no API key needed, no public exposure of n8n needed).
