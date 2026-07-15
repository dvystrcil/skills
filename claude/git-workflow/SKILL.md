---
name: git-workflow
description: Strict GitOps workflow for every repo change — branch, rebase, test, push branch, open a PR. NEVER commit or push to main directly; never merge your own PR. Load BEFORE any git commit, push, or PR operation.
---

# Git Workflow

## Strict rules — no exceptions

1. **Never commit to or push `main` directly.** Always create a descriptive branch (`feature/...` or `fix/...`) first. Check `git branch --show-current` before committing — if it says `main`, branch NOW.
2. **Rebase before committing**: sync with `origin/main` to avoid conflicts.
3. **Test before committing**: verify the change works. Include test files where applicable.
4. **Commit with a clear message**, then push the **branch** (never `git push origin main`).
5. **Always create a PR** (`gh pr create`) with:
   - What was built/changed and why
   - How to test it
   - Dependencies/configuration notes
   - Known limitations or follow-up work
6. **Never merge your own PR.** Await user review and approval.
7. **Never `git push --force`** on any shared branch.

## Why this is absolute here

Most deploy repos in this homelab are watched by ArgoCD **auto-sync**: a push to `main` IS a production deployment, usually within ~3 minutes. There is no staging buffer. A direct-to-main push on 2026-07-15 deployed a mangled `values.yaml` to the monitoring stack and silently deleted live Grafana config (homelab#460).

## Editing YAML files (the incident's second half)

- **Never round-trip a YAML file through a parser** (`python yaml.load/dump`, `yq -i`) to make a small edit — it destroys comments, quoting, and anchors across the whole file. Make targeted text edits to the specific lines only.
- Before committing, check your diff: **if it deletes more lines than you intended to change, STOP** — do not commit it.
