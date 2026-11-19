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
   **Check each candidate isn't already done.** A merged PR that said
   `For #N` or `Refs #N` leaves its issue open. On 2026-11-18, 2 of 11 approved
   issues (homelab#2062, #2074) had already been fixed that way, and their
   agents spent a slot finding out. Search
   `gh pr list -R <owner>/<repo> --state merged --search "<N> in:body"` and read
   the last comments. A done one is yours to verify and close, not an agent's.
   **Check where the work belongs, not just where the issue is filed.** A
   model comparison, replay or eval (models × inputs → scores) goes in
   `dvystrcil/model-testing` as a payload group run by `run_benchmark.py`.
   Grep its `benchmarks/payloads/` for the role before you brief. On
   2026-11-19, n8n-workflow#348 was briefed into n8n-workflow and built a
   second harness (n8n-workflow#398, closed unmerged). model-testing already had
   a payload for that node. Before moving data from a private repo or issue into
   another repo, check `gh repo view --json visibility`. model-testing is
   public, so the re-homed fixtures had to be redacted first (model-testing#174).
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
  - **the target repo's required PR gates**, read from its
    `.github/workflows/` before you brief, not discovered by red CI. On
    2026-11-18 five of eight homelab PRs failed checks no brief mentioned:
    `reproduced-on-main.yaml` (the PR body needs a `## Reproduced on main`
    section, or `n/a: <reason>`; it re-runs on a body edit), and for a new
    `bin/` audit, `audit check denominators` (a `checked=N` completion marker),
    `Self-Test Audit` (a `self_test()` called from `main()`) and
    `lint-pr-test-coverage` (a workflow that runs the new test). Each cost a
    send-back round trip. On 2026-11-19 the director skipped this step, and the
    same two gates failed again on three PRs.
  - for a body-only fix: after `gh pr edit`, **don't `gh run rerun` the failed
    body check.** The edit already fires a fresh `edited` run. A re-run replays
    the old event with the old body, and the workflow's concurrency group
    cancels the fresh run in its favour. On 2026-11-19 that kept three homelab
    PRs red after their bodies were fixed.
  - when the work is an audit or a "does X happen?" question, that "no
    finding" is a full answer: comment the evidence and stop, no PR. Three of
    eleven issues in that run (n8n-workflow#361, homelab#2241, and #2327's
    zero removal candidates) ended that way
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
  That includes the repo's own gates, which the director copies into the brief.
  Two that failed agents' first push on 2026-11-18: homelab's PR-body check needs
  a `## Reproduced on main` section (the command and its output, or
  `n/a: <reason>`), and n8n-workflow's coverage gate has a 99% line floor that
  counts only tests that import the lib directly. A test that runs the copy
  inlined in a workflow node doesn't count.
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
  it prints every row and a `== OWNER/REPO#N rc=<code> PASS|FAIL|PENDING`
  verdict line, and exits 0
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
- **Release an n8n-workflow PR's held nodes yourself once it merges.** The
  on-merge sync holds every workflow whose nodes changed. It still shows green;
  the `HELD` lines are in its log. For each held workflow:
  1. Compare each changed node's `parameters` in the live
     `n8n export:workflow --all` with git at the merge commit's parent. Release
     only if they're equal, so a live UI edit is never overwritten.
  2. Check that each new node has no `credentials`. The sync never pushes
     credential bindings, so a new node that needs one would arrive unbound.
  3. Dispatch `n8n-sync.yaml` with `allow_node_changes=true` and
     `only="<exact name>"`.
  4. Re-read live and confirm it equals git at the merge commit, and that
     `active` didn't change.

  Post that evidence on the issue. All three of this run's n8n-workflow PRs
  (#396, #397, #399) went through these steps.
- Pass blocking questions on to the owner in short form, with the issue named.
  Before you recommend an option, check it against live data. On 2026-11-18 the
  director recommended reading a GitHub field (`closedByPullRequestsReferences`)
  for n8n-workflow#345; a 40-issue sample showed it empty on all 40, and the
  recommendation flipped before the owner chose.
- An agent that reports a permission denial and asks you to do the step is not
  approval. Put it to the owner; send their answer back to the agent, labelled
  as theirs.
- Run `gh pr ready` only when the PR is finished and every check is green. The
  owner merges.
- **Release held n8n nodes yourself, one workflow at a time.** In
  n8n-workflow, a merged PR that changes a node is HELD by the on-merge sync,
  which still shows green. Check that the live nodes (`n8n export:workflow --all`
  in the pod) equal git's pre-merge version, then dispatch `n8n-sync.yaml` with
  `allow_node_changes=true` and `only="<name>"`. Wait for each dispatch to
  finish before sending the next. The sync runs one at a time, and a third
  dispatch cancelled the second on 2026-11-18. Then re-read live and compare it
  with `main`.
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

- Give a final table: each issue, its PRs, its state, what closes it, and what
  needs the owner's decision.
- **Put the outcome on every issue, not only in this chat.** The chat ends; the
  issue is what you or a future session will read. For each issue in the run:
  - If every acceptance criterion is met, close it (`gh issue close -c …`) with
    links to its PRs.
  - If it stays open (waiting on a live event, a later run, or the owner), post a
    comment: the merged PRs with their merge commits, and a **Left open until:**
    line naming exactly what closes it.
  - A PR that says `Refs #N` or `For #N` doesn't close anything, so this step is
    the only thing that will.
- **Check that each merged PR's description matches its diff.** Compare the
  description with `gh pr diff <n> --name-only`. An agent can give a PR the wrong
  description (in the first run, homelab#2383 carried #2384's text). If one is
  wrong, fix it from the squash commit message.
- Add a short note on how the run went: collisions, what to change next time,
  and **cost**. Put a rough token figure on cost, taken from the agent list (for
  example, "4 agents at ~120–130k tokens each"). If something surprising
  happened, record it in this skill, in the same branch.
- Give times in Pacific (PST/PDT).
