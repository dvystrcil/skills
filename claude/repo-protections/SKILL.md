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
- Template lives at `<skills-repo>/repo-protections/templates/LICENSE` (resolve `<skills-repo>` via the symlink — see "How to use" below; don't hardcode `~/Code/skills`)
- In the README, link the word "MIT" to `LICENSE` — bare text won't render as a link

**Forks are exempt from the license + default-branch rules.** A fork keeps
its upstream license and branch convention. Apply the rest (merge mode,
branch protection, CODEOWNERS) as normal.

### Dual licensing for repos with substantial prose

When a repo contains documentation, reports, methodology notes, or other
prose that's meaningfully distinct from code, split licensing into two
layers:

- **Code** (scripts, fixtures, payloads, configs) — **MIT**
- **Prose** (README, design docs, results, methodology) — **CC-BY-4.0**
  (Creative Commons Attribution 4.0 International)

This is intentional, not a workaround. CC-BY-4.0 is more appropriate for
written content because (a) it gives explicit attribution semantics for
quoted/excerpted material, and (b) MIT's "software" framing maps awkwardly
to prose.

Two valid structures:

1. **Umbrella + sibling** — `LICENSE` at the root carries the canonical MIT
   text plus a note explaining the dual setup, with `LICENSE-docs.md`
   holding the CC-BY-4.0 details. Example: `dvystrcil/model-testing`.
2. **Separate files** — `LICENSE-CODE.md` (MIT) and `LICENSE-DOCS.md`
   (CC-BY-4.0), no umbrella `LICENSE`. Example: `dvystrcil/claude-personal-config`.

Either structure makes `licensee` (GitHub's auto-detector) return
`NOASSERTION` because the umbrella has extra text or there's no canonical-
named `LICENSE` file. **`audit.sh` recognizes both patterns** — if it sees
a sibling `LICENSE-{docs,DOCS,CODE,prose}.md` it accepts NOASSERTION as
intentional rather than flagging as drift.

**When to dual-license:** any repo where the prose IS the deliverable, or
where you might want someone to cite the writing without inheriting an MIT
"software" framing. Repos that are purely code (a script, a Docker image,
a service) don't need this.

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

### CD repos (image-updater writeback targets) use Rulesets with IU bypass

Repos that argocd-image-updater pushes to directly (`writeBackConfig.gitConfig.repository`) CAN have branch protection — but it must be a **GitHub Ruleset** with the IU GitHub App in the `bypass_actors` list, not classic Branch Protection. Classic Branch Protection rejects the IU's `git push origin main` with `GH006`. Rulesets support per-actor bypass, so:

- **Humans** still go through PRs (PR review, CODEOWNERS gate, no force-push, no deletion)
- **IU controller** pushes directly to main via its GitHub App authentication

`apply.sh` and `audit.sh` both detect CD repos by looking for an `image-updater/` directory at the repo root. When present:

- `apply.sh` creates (or updates) a Ruleset named `main-protection-with-iu-bypass` with rules:
  - `deletion` (no branch delete)
  - `non_fast_forward` (no force-push)
  - `pull_request` (1 review, dismiss stale, require code-owner review)

  …and two bypass actors: the homelab IU GitHub App (default `app_id=378815`; override with `IU_APP_ID`) **and Repository admin (RepositoryRole id 5)**. The admin bypass is load-bearing for a solo operator: GitHub forbids self-approving your own PR, so without it the owner can never merge their own PRs into a CD repo (the review requirement is unsatisfiable). `audit.sh` checks for both.

  **Conversion case:** if a non-CD repo later becomes a CD repo (i.e. the deploy scaffold PR adds `image-updater/` after `apply.sh` had already installed classic Branch Protection), the next `apply.sh` run also strips the stale classic protection. Without that, classic and Ruleset enforce in parallel — classic has no per-actor bypass list, so IU's push fails with `GH006` even though the Ruleset bypass is correct. Burned 2026-05-29 on `dvystrcil/tor-character-mcp` and `dvystrcil/tor-dice`.
- `audit.sh` checks that the canonical Ruleset exists, is `active`, has the IU app in the bypass list, **and that classic Branch Protection is absent** (would conflict with the Ruleset bypass). CODEOWNERS is still required (the Ruleset's `require_code_owner_review` depends on it).

This convention was established 2026-05-26 (homelab#238) after the initial "skip protection on CD repos" approach turned out to be unnecessarily permissive. Rulesets give us the protection AND IU's direct-push.

**Identifying the IU app id:** the homelab's argocd-image-updater authenticates via a GitHub App stored in argocd's `creds-*` repo-credentials secret (labeled `argocd.argoproj.io/secret-type=repo-creds`). Decode the `githubAppID` value from base64. For the homelab default it's `378815`.

**Detection edge cases:**
- A repo with its own `image-updater/` directory IS treated as a CD repo (catches both pure CD repos and mixed-shape `-docker` repos that hold their own IU CR)
- A repo named as `writeBackConfig.gitConfig.repository` but where the CR lives elsewhere will NOT be auto-detected. If you create such a layout, either move the CR into the CD repo (the canonical distributed-IU pattern) or manually run `apply.sh` with `is_cd_repo=1` mode.

## How to use this skill

### Quick path — for a brand-new repo you just created

```bash
# 0. Resolve the skills-repo root from the symlink — works no matter where
#    dvystrcil/skills was cloned (default ~/Code/skills; a portable install
#    may clone it elsewhere via SKILLS_REPO_DIR). Do NOT hardcode ~/Code/skills.
SKILLS_REPO="$(cd "$(dirname "$(readlink -f ~/.claude/skills/repo-protections)")/../.." && pwd)"

# 1. Audit current state
"$SKILLS_REPO/repo-protections/bin/audit.sh" dvystrcil/<repo>

# 2. If files are missing locally, add them
cp "$SKILLS_REPO/repo-protections/templates/CODEOWNERS" .github/CODEOWNERS
sed "s/{{YEAR}}/$(date +%Y)/" "$SKILLS_REPO/repo-protections/templates/LICENSE" > LICENSE
git add LICENSE .github/CODEOWNERS && git commit -m "chore: add LICENSE + CODEOWNERS" && git push

# 3. Apply GH-side settings
"$SKILLS_REPO/repo-protections/bin/apply.sh" dvystrcil/<repo>

# 4. Re-audit to confirm
"$SKILLS_REPO/repo-protections/bin/audit.sh" dvystrcil/<repo>

# 5. Bootstrap Infisical CI secrets, if this repo's workflows need them
"$SKILLS_REPO/repo-protections/bin/bootstrap-infisical-ci.sh" dvystrcil/<repo>
```

Step 5 (homelab#345) closes a recurring gap: `feedback_new_repo_infisical_secrets`
was filed after a new repo's CI silently failed for 6 days because nobody
set `INFISICAL_CLIENT_ID`/`INFISICAL_CLIENT_SECRET` at creation time — twice.
The script detects whether the repo's workflows actually reference
`Infisical/secrets-action` or `secrets.INFISICAL_CLIENT_ID` at all (a no-op,
silent exit if not) and checks whether both secrets are already set
(idempotent — safe to re-run). Every homelab repo's CI shares the same
Infisical project/identity (`project-slug: homelab-bz-gt`, one set of
credentials for the whole fleet — verified by grepping every workflow's
`Infisical/secrets-action` step, not a new per-repo identity), so it just
prompts once for those two values, opening the Infisical Identities page
for you if you don't have them handy.

### Periodic drift audit

```bash
"$SKILLS_REPO/repo-protections/bin/audit.sh" --all   # $SKILLS_REPO resolved as in the Quick path above
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

Skills live in [`dvystrcil/skills`](https://github.com/dvystrcil/skills):

- **`claude/repo-protections/SKILL.md`** — this file (Claude / opencode flavor)
- **`owui/repo-protections/SKILL.md`** — OWUI flavor (with `tags` + `scope` frontmatter)
- **`repo-protections/bin/`** + **`repo-protections/templates/`** — shared executables and templates, referenced by both flavors

Locally:

- `~/.claude/skills/repo-protections` → symlinked to `<skills-repo>/claude/repo-protections/` (`<skills-repo>` defaults to `~/Code/skills`; a portable install may clone it elsewhere)
- The `bin/` scripts live at `<skills-repo>/repo-protections/bin/{audit,apply,bootstrap-infisical-ci}.sh` — resolve `<skills-repo>` from the symlink (see "How to use"), never hardcode the path

Keep the two SKILL.md flavors in sync when the convention changes.
