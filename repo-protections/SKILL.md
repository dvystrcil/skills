---
name: repo-protections
description: Standard repository hygiene for new GitHub repos — MIT license, branch protection on main, squash/rebase only, CODEOWNERS file. Run after `gh repo create` and any time a public repo lacks these.
---

# Repo Protections

Apply the canonical settings whenever you create a new public repo, push the
first commit, or notice that an existing public repo is missing protections.

**This is not optional once a repo is public.** A public repo with no branch
protection, no LICENSE, and merge commits enabled is a hygiene gap that
should be closed within the same session it's noticed.

## The convention

### License

- **MIT** for original repos, with copyright line `Copyright (c) <YEAR> Daniel Vystrcil`
- File at repo root, named `LICENSE` (no extension)
- Template lives at `~/Code/skills/repo-protections/templates/LICENSE`
- In the README, link the word "MIT" to `LICENSE` — bare text won't render as a link

**Forks are exempt from the license + default-branch rules.** A fork keeps
its upstream license and branch convention. Apply the rest (merge mode,
branch protection, CODEOWNERS) as normal.

### Required files at repo root or `.github/`

| File | Where | Why |
|---|---|---|
| `LICENSE` | root | MIT, required for any public repo |
| `README.md` | root | Project intent + install/use instructions |
| `.github/CODEOWNERS` | `.github/` | Required because branch protection requires code-owner review |

### Default branch

- Always `main`. Never `master`.

### Repo-level settings

| Setting | Value | Reason |
|---|---|---|
| `allow_merge_commit` | **false** | Squash + rebase only; cleaner history |
| `allow_squash_merge` | true | Default merge mode |
| `allow_rebase_merge` | true | For series of clean commits |
| `allow_auto_merge` | false | Manual merge only |
| `delete_branch_on_merge` | true | Stops stale branches from accumulating |
| `has_issues` | true | Project board entries link to issues |

### Branch protection on `main`

| Rule | Value | Reason |
|---|---|---|
| `required_approving_review_count` | 1 | Force review even when self-reviewing |
| `dismiss_stale_reviews` | true | Re-review after new commits |
| `require_code_owner_reviews` | true | Honors `.github/CODEOWNERS` |
| `allow_force_pushes` | false | No history rewrites on main |
| `allow_deletions` | false | No accidental branch deletion |
| `enforce_admins` | false | Admin can still merge in emergencies |

> Private repos without GitHub Pro **can't** apply branch protection. The
> apply script will detect this and skip the protection step gracefully.

## How to use this skill

### Quick path — for a brand-new repo you just created

```bash
# 1. Audit current state
~/Code/skills/repo-protections/bin/audit.sh dvystrcil/<repo>

# 2. If files are missing locally, add them
cp ~/Code/skills/repo-protections/templates/CODEOWNERS .github/CODEOWNERS
sed "s/{{YEAR}}/$(date +%Y)/" ~/Code/skills/repo-protections/templates/LICENSE > LICENSE
git add LICENSE .github/CODEOWNERS && git commit -m "chore: add LICENSE + CODEOWNERS" && git push

# 3. Apply GH-side settings
~/Code/skills/repo-protections/bin/apply.sh dvystrcil/<repo>

# 4. Re-audit to confirm
~/Code/skills/repo-protections/bin/audit.sh dvystrcil/<repo>
```

### Periodic drift audit

```bash
~/Code/skills/repo-protections/bin/audit.sh --all
```

Lists every public repo with PASS/FAIL per dimension.

## When the AI should invoke this skill

- **Immediately after `gh repo create`** with `--public`, before considering the task done
- **When the user notices** a public repo is missing protections (the trigger that created this skill)
- **As a periodic audit**, if the user asks "are all my repos protected?"
- **Before flipping a repo from private to public**

## What this skill does NOT do

- It does not create commits on your behalf. If `LICENSE` or `CODEOWNERS` is
  missing, audit.sh will flag it and the human (or you, on instruction) needs
  to write + commit + push the files. This is intentional — file-creation
  decisions belong with the repo owner.
- It does not enforce CI requirements (no `required_status_checks`). Add
  those manually once the repo has a CI workflow worth gating on.
- It does not enable Dependabot or secret scanning. Those are separate
  concerns; consider a follow-up skill.

## Provenance

Conventions inferred from `dvystrcil/model-testing` and
`dvystrcil/open-terminal-docker` (the two best-protected public repos in
the org as of 2026-05-18) plus session discussion with the operator on
that date. Originally created because `dvystrcil/dp-wake` was pushed
without protections — exactly the gap this skill closes.

## Where this skill lives

- **Canonical source:** `~/Code/skills/repo-protections/` (this directory)
- **Claude Code & opencode** read it via the symlink at `~/.claude/skills/repo-protections`
- **OWUI** reads its own flavor at `~/Code/skills/owui/repo-protections/SKILL.md`

Both SKILL.md files reference the same scripts in `bin/` — keep them in sync.
