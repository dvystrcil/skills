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
6. **Wait for PR checks after creating any PR**: `gh pr checks <url> --watch --fail-fast`. A red check gets fixed on the same branch before you report done. "No checks reported" passes — **but check first whether that's a real gap or just miswired coverage**, in this order:
   - **First, look for an existing check that's close but not covering this path/file type**, and widen or fix *that one* rather than bolting on a new, possibly-redundant workflow. `.github/workflows/*.yml` may already run the exact validation needed (a test suite via `unittest`/`pytest discover`, a schema linter, a build check) but simply not be path-triggered for what you just touched — this is a more common gap than "no CI exists at all" (`dvystrcil/skills#39`: `test_skill_schema.py` already linted every `claude/*/SKILL.md`, the workflow just never triggered on that path).
   - **Only if nothing adjacent exists**, add a new one. For a kustomize-based deploy repo with no manifest validation at all, that's `.github/workflows/validate.yaml` using the shared `dvystrcil/kustomize-validate-action@v1` (the pattern on `mealie`/`reloader`/`home-assistant`/etc.).
   - Either way, do it in the *same* PR — don't leave the gap for a follow-up. Test locally with `act` first; a self-hosted runner label (not `ubuntu-latest`) needs `-P <label>=ghcr.io/catthehacker/ubuntu:act-latest` or `act` just skips with "unsupported platform" instead of testing anything.
7. **Never merge your own PR.** Await user review and approval.
8. **Never `git push --force`** on any shared branch.
9. **After a merge, verify what actually landed** — `gh pr view <n> --json files,commits` (or diff against `main`) — before treating the PR as fully done, especially if you pushed follow-up commits after the PR was first opened. A squash-merge clicked from a stale, already-open browser tab can silently pin to an old `headRefOid` and merge only the first commit, dropping everything pushed afterward even though it's still visible on the branch (home-assistant#4, 2026-07-23 — the "CI check never registered" mystery was actually this: the check was never in what merged).

## Why this is absolute here

Most deploy repos in this homelab are watched by ArgoCD **auto-sync**: a push to `main` IS a production deployment, usually within ~3 minutes. There is no staging buffer. A direct-to-main push on 2026-07-15 deployed a mangled `values.yaml` to the monitoring stack and silently deleted live Grafana config (homelab#460).

## Editing YAML files (the incident's second half)

- **Never round-trip a YAML file through a parser** (`python yaml.load/dump`, `yq -i`) to make a small edit — it destroys comments, quoting, and anchors across the whole file. Make targeted text edits to the specific lines only.
- Before committing, check your diff: **if it deletes more lines than you intended to change, STOP** — do not commit it.
