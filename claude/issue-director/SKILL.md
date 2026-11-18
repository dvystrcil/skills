---
name: issue-director
description: "Pick several open GitHub issues and see them through to ready PRs by sending each to its own background agent (one worktree per issue) while you act as director: triage, brief, review, send fixes back, report. Use when the user asks to work through a batch of issues in parallel, to 'farm out' or 'fan out' issues to agents, or to direct several Claudes at once. Start it from ~/Code so every repo is in reach."
---

# Issue director

You stay the director. Background agents do the work, one issue each. The owner
approves the shortlist, you review every result, and the owner merges.

## Scope

- Any repo under `~/Code`, unless the owner names a narrower set.
- **Leave out work that can't run side by side.** Example: vt350 model passes form
  a chain (`lite-N` → `lite-(N+1)`) stored outside git, so worktrees can't isolate
  them.
- **Leave out issues that are waiting** on a date, a measurement window, a
  scheduled maintenance, or the owner's input. Check memory and the issue's last
  comments for this. If you're unsure about one, ask.

## Phase 1: triage (no agents yet)

1. List the open issues in each repo in scope (`gh issue list -R <owner/repo>`).
2. Propose up to 10 candidates. Give each one:
   - `repo#num` and a one-line goal
   - a size (S, M or L)
   - what "done" means (its acceptance criteria)
   - **parallel** or **collides with X** (same files, same service, or a merge
     order that matters)
3. Flag every candidate that touches live infrastructure (cluster, ArgoCD,
   secrets, DNS). Its brief needs a `change-validation` plan, not just a PR. If the
   owner asked for code and docs only, leave those issues out instead.
4. **Stop and show the shortlist.** Nothing launches until the owner approves or
   trims it.

## Phase 2: fan out

- Run **3 to 5 agents at a time**: background, `isolation: "worktree"`, one issue
  each. When one finishes, start the next issue in the queue.
- Run colliding issues one after another, in merge order.
- Every brief must stand on its own. Agents start cold and know nothing from this
  conversation. Each brief contains:
  - the issue URL and its acceptance criteria
  - which files and areas are in scope, and which are off limits
  - the rules below, copied in, not referenced
  - what to report at the end

### Rules every agent follows

- Load `git-workflow`. Work on a branch, open a **draft** PR, never push to main,
  never merge.
- Follow the repo's `AGENTS.md` / `CLAUDE.md` and the skills that apply
  (`homelab-secrets` / `secrets-hygiene`, `change-validation`, `tdd`, …).
- Change the live cluster only through GitOps. Take no destructive actions.
- When a judgment call blocks the work, stop and report the question. Don't guess.
- The final report gives the PR URL, what changed, the tests run with their
  results, and any open questions.

## Phase 3: direct

- As each result arrives, review the diff (`/code-review`) and check CI.
- Send fixes back to the agent that did the work (`SendMessage`) rather than
  redoing it yourself.
- Pass blocking questions on to the owner in short form, with the issue named.
- Run `gh pr ready` only when the PR is finished and every check is green. The
  owner merges.
- Close superseded PRs yourself (`gh pr close` with a comment giving the reason).
- Keep one status table (issue, agent, PR, CI, state). Show it when something
  changes, not on every notification.

## Wrap-up

- Give a final table: each issue, its PR, its state, and what needs the owner's
  decision.
- Add a short note on how the run went: cost, collisions, and what to change next
  time. If something surprising happened, record it in this skill, in the same
  branch.
- Give times in Pacific (PST/PDT).
