---
name: "Repo Protections"
description: "Standard repo hygiene for new GitHub repos — MIT license, branch protection on main, squash/rebase only, CODEOWNERS file."
tags: ["github", "gitops", "repo-hygiene", "license", "branch-protection"]
scope: "complex"
---

# Repo Protections

Apply the canonical settings whenever a new public repo is created or any
public repo is found lacking them. **Not optional once a repo is public.**

## The convention

### License
- **MIT** for original repos, copyright `Copyright (c) <YEAR> Daniel Vystrcil`
- File at repo root, named `LICENSE` (no extension)
- In README, link the word "MIT" to `LICENSE` (`[MIT](LICENSE)`)
- **Forks keep upstream's license + default branch** — apply the rest of
  the rules but skip these two.

### Required files
| File | Location | Reason |
|---|---|---|
| `LICENSE` | repo root | MIT, public repos must have one |
| `README.md` | repo root | Intent + install/use |
| `.github/CODEOWNERS` | `.github/` | Branch protection requires code-owner review |

### Default branch — always `main`, never `master`.

### Repo-level settings
| Setting | Value |
|---|---|
| `allow_merge_commit` | **false** |
| `allow_squash_merge` | true |
| `allow_rebase_merge` | true |
| `allow_auto_merge` | false |
| `delete_branch_on_merge` | true |
| `has_issues` | true |

### Branch protection on `main`
| Rule | Value |
|---|---|
| `required_approving_review_count` | 1 |
| `dismiss_stale_reviews` | true |
| `require_code_owner_reviews` | true |
| `allow_force_pushes` | false |
| `allow_deletions` | false |
| `enforce_admins` | false |

> Private repos without GitHub Pro cannot apply branch protection — the
> apply script detects this and skips that step.

## Tooling

Canonical scripts live in `~/Code/skills/repo-protections/bin/`:

```bash
# Check drift for one repo or every public repo:
~/Code/skills/repo-protections/bin/audit.sh dvystrcil/<repo>
~/Code/skills/repo-protections/bin/audit.sh --all

# Apply canonical settings + branch protection:
~/Code/skills/repo-protections/bin/apply.sh dvystrcil/<repo>
```

The audit script flags drift without changing anything. The apply script is
idempotent — safe to re-run.

## When to apply

- Immediately after `gh repo create` with `--public`
- When a public repo is noticed without protections
- Before flipping a repo private → public
- During a periodic `--all` audit

## What it does NOT do

- Does not commit `LICENSE` / `CODEOWNERS` for you — those are local file
  decisions; the audit flags missing ones and the operator commits them.
- Does not enable Dependabot, secret scanning, or required CI status checks.
  Add those when the repo has CI worth gating on.

## Provenance

Conventions extracted from the two best-protected public repos in the org
(`dvystrcil/model-testing`, `dvystrcil/open-terminal-docker`) on 2026-05-18.
Skill created because `dvystrcil/dp-wake` was pushed without protections.
