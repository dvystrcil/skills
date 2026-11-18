---
name: issue-director
description: "Pick several open GitHub issues and see them through to ready PRs by sending each to its own background agent (one worktree per issue, made in the target repo) while you act as director: triage, brief, review, send fixes back, report. Use when the user asks to work through a batch of issues in parallel, to 'farm out' or 'fan out' issues to agents, or to direct several Claudes at once. Start it from ~/Code so every repo is in reach."
---

# Issue director

You stay the director. Background agents do the work, one issue each. The owner
approves the shortlist, you review every result, and the owner merges.

## Scope

- Every repo the owner has on GitHub, unless they name a narrower set ("only X and
  Y", "everything except Z"). Find issues on GitHub, not by walking `~/Code`. Some
  folders there are clones of other people's projects (FreeCAD, TinySearch), so
  they would pull in upstream issues. Others are extra worktrees of the same repo
  (`homelab-wt-*`, `vt350-*`). And some repos that have issues aren't cloned at
  all.
- **Leave out work that can't run side by side.** Example: vt350 model passes form
  a chain (`lite-N` → `lite-(N+1)`) stored outside git, so worktrees can't isolate
  them.
- **Leave out issues that are waiting** on a date, a measurement window, a
  scheduled maintenance, or the owner's input. Check memory and the issue's last
  comments for this. If you're unsure about one, ask.

## Phase 1: triage (no agents yet)

1. List the open issues with one search across the owner's repos:
   `gh search issues --owner <owner> --state open --limit 500 --json repository,number,title,labels,updatedAt`.
   Then filter it down to the repos in scope. Check first how many there are per
   repo: homelab alone can hold 100+, so read titles and labels to shortlist
   before you open any issue in full.
2. Propose up to 10 candidates. Give each one:
   - `repo#num` and a one-line goal
   - a size (S, M or L)
   - what "done" means (its acceptance criteria)
   - **parallel** or **collides with X** (same files, same service, or a merge
     order that matters)
3. **Size every candidate so one agent can finish it in one session.** An agent
   that runs long gets its context summarized, and after that it loses earlier
   decisions and redoes work. So:
   - S and M issues each go to one agent, in one PR.
   - Split every L issue, and every issue that would need more than one PR, into
     slices before you brief anyone. Each slice gets its own agent and PR, and
     the slices run one after another in merge order. Show the slices in the
     shortlist.
   - If an issue can't be split cleanly (it's unclear, design-heavy, or needs the
     owner throughout), leave it out of the run and say why. It suits a dedicated
     session better.
4. Flag every candidate that touches live infrastructure (cluster, ArgoCD,
   secrets, DNS). Its brief needs a `change-validation` plan, not just a PR. If the
   owner asked for code and docs only, leave those issues out instead.
5. **Stop and show the shortlist.** Nothing launches until the owner approves or
   trims it.

## Phase 2: fan out

- Run **3 to 5 agents at a time**, in the background, one issue each. When one
  finishes, start the next issue in the queue.
- **Don't use `isolation: "worktree"` when the session starts in `~/Code`.** It
  makes the worktree from the session's own repo, and `~/Code` isn't a repo. Each
  agent makes its own worktree in the target repo instead. Put these steps in
  every brief:
  1. If `~/Code/<repo>` doesn't exist, clone it there
     (`gh repo clone <owner>/<repo> ~/Code/<repo>`).
  2. `git -C ~/Code/<repo> fetch origin`, then
     `git -C ~/Code/<repo> worktree add ~/Code/<repo>-wt-<issue> -b <branch> origin/<default-branch>`.
  3. Work only inside `~/Code/<repo>-wt-<issue>`. Never change the main checkout,
     which may hold the owner's uncommitted work.
- Remove each worktree yourself, as director, once its PR is merged or closed
  (`git -C ~/Code/<repo> worktree remove …`, then delete the local branch).
- Two agents must never share a repo's worktree. Agents in the same repo each get
  their own.
- Run colliding issues one after another, in merge order.
- Every brief must stand on its own. Agents start cold and know nothing from this
  conversation. Each brief contains:
  - the issue URL and its acceptance criteria
  - which files and areas are in scope, and which are off limits
  - the files you expect it to change. This is its scope limit (see the rules).
  - the rules below, copied in, not referenced
  - what to report at the end

### Rules every agent follows

- Load `git-workflow`. Work on a branch, open a **draft** PR, never push to main,
  never merge.
- Follow the repo's `AGENTS.md` / `CLAUDE.md` and the skills that apply
  (`homelab-secrets` / `secrets-hygiene`, `change-validation`, `tdd`, …).
- Change the live cluster only through GitOps. Take no destructive actions.
- When a judgment call blocks the work, stop and report the question. Don't guess.
- **Stay within the scope limit.** If the work grows well beyond the files the
  brief expects, or your context has been summarized once, stop: commit what you
  have, push it to the draft PR, and report what's left. Don't push on. Work
  that's pushed survives a lost context.
- Commit and push at each working step, not only at the end.
- Run the checks you can run locally (tests, linters, `act`) **before** you push.
- **Don't wait on CI.** Your job ends when the work is pushed and the draft PR is
  open. Report and finish. Never poll `gh pr checks` or watch a run: the
  director watches CI, and if a check fails it sends the failure back to you to
  fix.
- Keep the final report to five lines or fewer: PR URL, what changed, tests and
  their results, open questions. Put the details in the PR description, not the
  report.

## Phase 3: direct

- As each result arrives, review the diff (`/code-review`).
- **Watch CI yourself, without polling.** Run the bundled script in a background
  shell. Pass it one PR or several:

  ```
  ~/.claude/skills/issue-director/bin/wait-pr-checks.sh OWNER/REPO#N [OWNER/REPO#N ...]
  ```

  It waits for each PR's checks to register, then blocks until they finish. Then
  it prints every row and a `== OWNER/REPO#N rc=…` verdict line, and exits 0
  only if every PR passed. It costs nothing while it waits, and you're notified
  when it exits.
- Don't write your own wait loop around `gh pr checks`. Piping it into
  `wc`/`tail`/`grep` trips the pr-checks-pipe-guard hook, which costs the owner a
  prompt, and can hide failing rows. Don't leave CI to the agents either: an
  agent that waits on CI spends tokens on every check and stays open the whole
  time.
- If a check fails, send the failing job's log excerpt to the agent that did the
  work (`SendMessage`). It picks up with its context intact.
- Send fixes back to the agent that did the work (`SendMessage`) rather than
  redoing it yourself.
- Pass blocking questions on to the owner in short form, with the issue named.
- Run `gh pr ready` only when the PR is finished and every check is green. The
  owner merges.
- Close superseded PRs yourself (`gh pr close` with a comment giving the reason).
- Keep one status table (issue, agent, PR, CI, state). Show it when something
  changes, not on every notification.
- When an agent stops at its scope limit, treat what's left as a new slice: brief
  a fresh agent from the PR and its report. Don't keep extending the old one.
- **Keep your own context lean.** Read PR diffs on demand rather than pasting
  them whole. If your session gets long, or has already been summarized, write a
  handoff to memory: the status table, the queue, the open questions, and the
  worktrees that still need removing. A fresh director session can then take over
  from it.

## Wrap-up

- Give a final table: each issue, its PR, its state, and what needs the owner's
  decision.
- Add a short note on how the run went: cost, collisions, and what to change next
  time. If something surprising happened, record it in this skill, in the same
  branch.
- Give times in Pacific (PST/PDT).
