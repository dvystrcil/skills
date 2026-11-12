---
name: repo-protections
description: Standard repository hygiene for new GitHub repos — MIT license, branch protection on main, squash/rebase only, CODEOWNERS only where a rule requires code-owner review. Run after `gh repo create` and any time a repo (public or private) lacks these.
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

**Forks of a third-party upstream are exempt from the license,
default-branch, AND CODEOWNERS rules.** Such a fork keeps its upstream
license and branch convention, and does not get a `CODEOWNERS` file:
that is our review governance written into someone else's tree, and a
file upstream doesn't have is friction on every merge from upstream —
exactly the repos where you're carrying a feature branch toward a PR.
Apply the rest (merge mode, branch protection) as normal: those govern
review *in our fork* and are ours to set. With no `CODEOWNERS` present,
branch protection's `require_code_owner_reviews` is simply vacuous — no
file owns any path — so the 1-approval rule still holds and nothing
breaks.

"Third-party" means the parent's owner is not us. A fork of one of our
own repos is not exempt.

Established 2026-08-10, after a fleet audit added CODEOWNERS PRs to
`fluidd` (fork of `fluidd-core`), `FreeCAD` (`FreeCAD/FreeCAD`),
`TinySearch` (`TinySuiteHQ`) and `open-terminal-app-fork`
(`open-webui`); the operator rejected them on exactly this reasoning —
"it's forked from a vendor, I should not impress my codeowners on it".
The previous wording explicitly told you to apply CODEOWNERS to forks
"as normal", which is what produced those PRs.

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

### Deliberately non-MIT repos
A repo whose license is a recorded owner decision goes in `LICENSE_EXCEPTIONS`
in `bin/audit.sh`, with the decision it came from. The audit then wants
exactly that SPDX id: drifting away from it is still a ✗. Today:
`dvystrcil/vt350` = GPL-3.0 (GPL-3.0-or-later for our own work; its
vendored/remixed parts are GPL-3.0 or CC BY-NC-SA — vt350#130).

**When to dual-license:** any repo where the prose IS the deliverable, or
where you might want someone to cite the writing without inheriting an MIT
"software" framing. Repos that are purely code (a script, a Docker image,
a service) don't need this.

### Required files at repo root or `.github/`

| File | Where | Why |
|---|---|---|
| `LICENSE` | root | MIT, required for any public repo |
| `README.md` | root | Project intent + install/use instructions |
| `.github/CODEOWNERS` | `.github/` | **Only where a rule requires code-owner review** (classic protection below). Elsewhere it must be **absent** — see "CODEOWNERS is conditional" |

### CODEOWNERS is conditional

Since GitHub Pro (2026-11-10) code owners work on private repos too, and a
`* @dvystrcil` CODEOWNERS file auto-requests the owner's review on **every
PR, bot PRs included** — one email each (first seen on cluster-ops#1049,
`dvystrcil-ci-cd[bot] requested your review … as a code owner`). The solo
Rulesets (homelab's and the CD one) require 0 approvals and no code-owner
review, so on those repos the file gates nothing and only makes noise.

`audit.sh` therefore requires `.github/CODEOWNERS` only when classic
protection or an active Ruleset requires code-owner review, and flags it
`✗ got=present want=absent` everywhere else. Forks and machine-managed repos
stay exempt either way.

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

### Writers: the owner only
Every Ruleset here requires **0 approvals**, so anyone with write access can
merge their own PR -- on `homelab` or `argocd-projects`, straight to
production. The owner removed every outside collaborator on 2026-11-11
(4 accounts across 5 repos). `audit.sh` keeps it that way: `writers` must read
`owner only`. It flags any non-owner collaborator with push and any pending
invite for write or above; read/triage access passes, and an API error is a
✗, not a pass. To give someone access again, they need a review rule that
binds them (approvals > 0 with an owner bypass), not just a collaborator
seat.

### Branch protection on `main` (FORKS only)

Every other non-CD repo, private or public, gets the solo Ruleset instead
(next section). Forks keep classic: a PR-required Ruleset with no bypass
blocks GitHub's "Sync fork", which fast-forwards the default branch directly.

| Rule | Value | Reason |
|---|---|---|
| `required_approving_review_count` | 1 | Force review even when self-reviewing |
| `dismiss_stale_reviews` | true | Re-review after new commits |
| `require_code_owner_reviews` | true | Honors `.github/CODEOWNERS` |
| `allow_force_pushes` | false | No history rewrites on main |
| `allow_deletions` | false | No accidental branch deletion |
| `enforce_admins` | false | Admin can still merge in emergencies |

> **Private repos are in scope.** The account has been on **GitHub Pro since
> 2026-11-10**, which unlocks branch protection and Rulesets on private
> repos. Before that, every private repo returned `403 Upgrade to GitHub Pro`
> and `apply.sh`/`audit.sh` reported it as "n/a" with exit 0 — so all 70
> private repos, `homelab` (a live ArgoCD source) included, passed the audit
> while being unprotected, and `audit.sh --all` never looked at them. Both
> scripts now treat that 403 as a **failure**: it means the Pro plan lapsed.
>
> **`enforce_admins: false` is weaker than it looks on a solo account.** It
> exempts admins from *every* rule, direct pushes to `main` included — and
> every agent session acts with the owner's admin credential. So classic
> protection here stops nobody who is likely to push. Where that matters, use
> the solo Ruleset below instead.

### Solo Ruleset (no bypass) — the `homelab` pattern, every non-CD non-fork repo

For a repo where "never push to `main`" has to actually hold for agents, not
just be written down: a Ruleset named `main-protection` on `~DEFAULT_BRANCH`
with **no bypass actors at all** and **0 required approvals** (a solo owner
can't approve their own PR, so 1 approval with no bypass would block every
merge, and 1 approval *with* an admin bypass makes every merge a bypass).

| Rule | Value |
|---|---|
| `deletion`, `non_fast_forward` | on |
| `pull_request` | 0 approvals, merge methods squash + rebase |
| `required_status_checks` | only checks that run on **every** PR (no path filter); `integration_id: 15368` (GitHub Actions) |
| `bypass_actors` | `[]` |

Required checks come from history, not from the workflow list: `apply.sh`
reads the GitHub Actions check runs on the last 30 merged PRs and requires
only the names present on **all** of them. A path-filtered check that's
required blocks every PR it doesn't run on. Fewer than 5 merged PRs (or no
CI) → no `required_status_checks` rule at all. A check added recently (e.g.
`gitleaks`, homelab#2079) isn't on all 30 yet and so isn't required until it
is — re-run `apply.sh` later to pick it up. Emergencies: switch the Ruleset's
enforcement off in Settings (it's logged), don't add a bypass.

`apply.sh` creates or updates it (in place, by name) on every non-CD,
non-fork repo — private since 2026-11-10, public since 2026-11-11 — strips any classic protection (it enforces in parallel and its
`enforce_admins: false` is the hole being closed), and `--dry-run` prints the
planned Ruleset without writing anything. `audit.sh` checks it is active,
0 approvals, no role/admin bypass, bypass Apps exactly as listed, no classic
protection. A repo whose only protection is a hand-made Ruleset under
another name (homelab-heartbeat, skills, neptune-4pro-klipper-backup — bot
bypasses that predate this shape) is left alone by both scripts -- but
classic protection beside it is still a ✗ in `audit.sh` (it enforces in
parallel, and its `enforce_admins: false` is the hole).

**Bots that push to `main`.** A Ruleset with no bypass rejects them with
`GH013`. Before rolling it onto a repo, list its `main` commits from the last
~2 months that belong to no PR (`GET /repos/{o}/{r}/commits/{sha}/pulls` is
empty). Each automated writer's App goes into `DIRECT_PUSH_APPS` in
`bin/solo-ruleset.sh` — with the source its id was read from (the App's
credential or a rule-suite log, never "a bypass that works elsewhere") — and
becomes an `always` bypass actor. `audit.sh` flags both an unlisted bypass
(a hole) and a listed App missing from the bypass (its pushes will break).

**A `GITHUB_TOKEN` push can't be exempted.** On a user-owned repo GitHub
rejects the GitHub Actions App (15368) as a bypass actor: `422 Actor GitHub
Actions integration must be part of the ruleset source or owner organization`
(homelab-weather, 2026-11-11). A workflow that pushes to `main` must push as
one of the owner's Apps (mint a token with `actions/create-github-app-token`,
as `rebuild-configmap.yml` here does) — and that App goes in the list.
`apply.sh` refuses a list containing 15368 before writing anything.

Applied by hand to `dvystrcil/homelab` 2026-11-10 (Ruleset id 27005532;
required checks `gitleaks` + `canaries`). CD repos use the CD Ruleset in the
next section: this same solo shape plus exactly one bypass actor, the IU App.

### CD repos (image-updater writeback targets) use Rulesets with IU bypass

Repos that argocd-image-updater pushes to directly (`writeBackConfig.gitConfig.repository`) CAN have branch protection — but it must be a **GitHub Ruleset** with the IU GitHub App in the `bypass_actors` list, not classic Branch Protection. Classic Branch Protection rejects the IU's `git push origin main` with `GH006`. Rulesets support per-actor bypass, so:

- **Humans and agents** still go through PRs (no direct push, no force-push, no deletion)
- **IU controller** pushes directly to main via its GitHub App authentication

`apply.sh` and `audit.sh` both detect CD repos by looking for an `image-updater/` directory at the repo root. When present:

- `apply.sh` creates (or updates) a Ruleset named `main-protection-with-iu-bypass` with rules:
  - `deletion` (no branch delete)
  - `non_fast_forward` (no force-push)
  - `pull_request` (**0 approvals**, merge through a PR)

  …and **exactly one bypass actor: the homelab IU GitHub App** (default `app_id=378815`; override with `IU_APP_ID`). It replaces an existing Ruleset that already lists the IU App under another name (e.g. a hand-made `main`) in place rather than adding a second one.

  **Why this shape (owner decision 2026-11-10, after GitHub Pro).** The previous CD Ruleset required 1 approval and listed **Repository admin (`always`)** and **the CICD App (`pull_request`)** as bypass actors. A solo owner can't approve their own PR, so every merge went through the admin bypass — and `always` also let the owner's credential, which every agent session uses, push straight to `main`. With 0 approvals neither bypass has a job: the owner merges normally, and homelab's auto-merge gate succeeds on its first, plain `gh pr merge` (D-037 only reaches for `--admin` after a plain merge is refused as a policy block). This is the same solo shape as homelab's `main-protection`, plus the one actor that genuinely has to push directly.

  **Conversion case:** if a non-CD repo later becomes a CD repo (i.e. the deploy scaffold PR adds `image-updater/` after `apply.sh` had already installed classic Branch Protection), the next `apply.sh` run also strips the stale classic protection. Without that, classic and Ruleset enforce in parallel — classic has no per-actor bypass list, so IU's push fails with `GH006` even though the Ruleset bypass is correct. Burned 2026-05-29 on `dvystrcil/tor-character-mcp` and `dvystrcil/tor-dice`.
- `audit.sh` finds the CD Ruleset (canonical name, or any Ruleset listing the IU App) and checks it is `active`, has the IU App (matched by id), requires **0** approvals, and has **no** admin and **no** CICD bypass — **and that classic Branch Protection is absent**. On non-CD repos a CICD bypass stays opt-in but never wider than `pull_request` (`always`/`exempt` fails), unless the repo is in `CICD_DIRECT_PUSH_REPOS` with its reason (today only `skills`, whose `rebuild-configmap.yml` pushes to `main`).

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
SKILLS_REPO="$(cd "$(readlink -f ~/.claude/skills/repo-protections)/../.." && pwd)"

# 1. Audit current state
"$SKILLS_REPO/repo-protections/bin/audit.sh" dvystrcil/<repo>

# 2. If files are missing locally, add them
#    CODEOWNERS ONLY if this repo will use classic protection (which requires
#    code-owner review) -- never for a solo-Ruleset repo:
#    cp "$SKILLS_REPO/repo-protections/templates/CODEOWNERS" .github/CODEOWNERS
sed "s/{{YEAR}}/$(date +%Y)/" "$SKILLS_REPO/repo-protections/templates/LICENSE" > LICENSE
git add LICENSE && git commit -m "chore: add LICENSE" && git push

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

Lists every non-archived repo — public **and private** — with PASS/FAIL per dimension.

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
