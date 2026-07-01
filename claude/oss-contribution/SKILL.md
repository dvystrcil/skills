---
name: oss-contribution
description: Contribute to a third-party / upstream open-source repo the *right* way — read their norms first, search prior art, propose features before building them, and never presume acceptance. Use whenever opening an issue or PR on a repo you don't maintain (most often an upstream you forked).
---

# OSS Contribution (the polite path)

**You are a guest in someone else's project.** The maintainer owes you nothing —
not their review time, not acceptance, not agreement with your design. Every
step below optimizes for two things: *making it cheap for them to say yes*, and
*not spending their attention uninvited*.

**Trigger:** any time you're about to open an issue or PR on a repo the user
does not own or maintain — most commonly an upstream project the user has forked
(`upstream` remote points somewhere other than the user's account).

## The cardinal rule: propose before you build (for features)

An unsolicited, fully-built **feature** PR is impolite. It presumes the
maintainer wants the feature, presumes your design is the one they'd accept, and
hands them a review-time bill they never agreed to. A surprise feature PR is a
worse first impression than no PR at all.

So for **features → issue-first, PR-on-invitation:**

1. Open a feature-request issue (use *their* template).
2. State the use case, show the problem, propose the approach.
3. Mention you have a working, tested reference implementation on a fork, and
   **offer to open a PR *if they're interested***.
4. Defer to their design authority — ask how they'd want it scoped (e.g. global
   setting vs. per-component, which options).
5. Open the PR only once a maintainer signals interest.

**Bug fixes are different.** A small, correct fix with a clear repro is usually
welcome as a direct PR — but still check for an existing issue first, still read
`CONTRIBUTING`. If the fix is large, architectural, or changes behavior, propose
it first like a feature.

## Step 1 — Read their norms BEFORE writing anything

Never assume generic GitHub conventions. Read, in the repo:

- **`CONTRIBUTING.md`** (root or `.github/`) — the stated process.
- **`.github/ISSUE_TEMPLATE/`** — templates + `config.yml`. Note
  `blank_issues_enabled` (false = they funnel through templates, so use one) and
  `contact_links` (a Discord/Matrix link often means *chat-first is preferred*
  for features).
- **`.github/PULL_REQUEST_TEMPLATE*`** — what they expect in a PR body.
- **`CODE_OF_CONDUCT.md`**, **DCO** (`developer-certificate-of-origin`).
- Their commit + PR conventions: conventional-commit type list, subject-length
  limits (git hooks enforce these), **Signed-off-by / DCO** (`git commit -s`),
  PR-title CI checks, **which branch to target** (often `develop`, NOT the
  default), squash/rebase policy.

Match their conventions exactly. Your contribution should look like it came from
a regular contributor, not an outsider imposing their own style.

## Step 2 — Do the prior-art homework

Before proposing anything, search issues **and** PRs, **open and closed**:

```bash
gh search issues --repo OWNER/REPO "<terms>" --include-prs --limit 10 \
  --json number,title,state,isPullRequest
```

- `--state all` is **invalid** (valid: `open`|`closed`); omit it. And piping a
  failed `gh` call into `jq` hides the error as "no results" — eyeball the raw
  output before concluding "no prior art."
- Re-pitching something already declined is worse than a surprise. If a related
  discussion exists, join it instead of opening a duplicate.
- In the issue, state you searched and found no prior request — it shows homework
  and invites correction ("apologies if I missed one").

## Step 3 — Write it to be easy to say yes to

- **Small, focused diff.** One concern per PR.
- **Concrete problem statement.** Show, don't tell — screenshots for UI, a repro
  for bugs, numbers where relevant.
- **Opt-in + safe defaults** for behavior changes — "default off, no change
  unless enabled" dramatically lowers the risk of acceptance.
- **Gates green.** Run their *full* check suite (lint, type-check, tests, build —
  whatever CI runs) before pushing.
- **Honest claims — do NOT overclaim.** No coverage-theater tests dressed up as
  meaningful. No manufactured red-green TDD story if the code path was already
  covered. Say plainly what changed and what's actually tested. If you're only
  adding values to an already-tested, unchanged function, *say that* — don't
  invent a guard test against a threat that doesn't exist.

## Step 4 — Tone

- Humble and deferential. **Propose, don't insist. Offer, don't presume.**
- Acknowledge it's unsolicited; thank them for their time and the project.
- Defer to their design authority explicitly ("I'd rather hear your take than
  presume").
- Never pressure. A "no" is a perfectly good outcome — respect it and move on.

## Respect their identity — don't impose yours

- **Do NOT run the [[repo-protections]] hygiene skill on a fork.** It adds MIT
  license / CODEOWNERS / default-branch rules that would clobber the upstream's
  license (e.g. GPL-3.0) and conventions. A fork keeps upstream's license and
  shape; apply your own conventions only to repos *you* own.
- Don't reformat, rename, or restructure beyond your change's scope.
- Use their templates and let *them* label — you usually can't anyway (below).

## Practical gotchas

- **`gh` can't upload images.** GitHub only accepts image attachments via web
  drag-drop (or a hosted URL). File the issue/PR text with a placeholder, then
  the user drags screenshots into the body/comment. A UI feature request without
  a before/after screenshot is far weaker — get the human to add one.
- **Non-collaborators can't set labels/assignees.** `gh issue create --label X`
  is silently dropped if you lack triage rights; the maintainers label it. Don't
  chase a missing label.
- **Target the integration branch.** Many projects merge into `develop`, not the
  default. Branch your PR head off theirs (`feat/x` off `develop`), and don't
  open the PR *from* `develop`/`master` if they forbid it.
- **PR title must be a conventional commit** if CI enforces it (e.g.
  `amannn/action-semantic-pull-request`).
- **DCO sign-off** (`git commit -s`) with a real name + current email if required.

## The workflow, condensed

1. Read `CONTRIBUTING` + issue/PR templates + `config.yml`. Note conventions.
2. Search prior art (issues + PRs, open + closed) — check raw `gh` output.
3. **Feature?** → file the issue (their template), state the use case, offer the
   tested fork impl, wait for interest. **Bug?** → check for an issue, then a
   focused PR with a repro.
4. Build on a fork branch off their integration branch; gates green; honest
   commit/PR text; DCO + conventional title.
5. Let the user attach screenshots (gh can't). Let maintainers label/triage.
6. Only push/PR what they've signaled they'd want. Respect a "no."

## Related

- [[repo-protections]] — the inverse: hygiene for repos you *own* (never on a fork).
- [[three-anchor-truthiness]] — the honesty discipline behind "don't overclaim."
