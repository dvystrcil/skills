---
name: three-anchor-truthiness
description: Use when verifying claims about system state — auditing docs for drift, confirming "X is stale/changed/unused", or reconciling two sources that disagree. Never settle a conflict between two sources by splitting the difference; bring in a third independent anchor and let the odd one out lose.
---

# Three-Anchor Truthiness

A claim verified against one source is an assumption. Two sources that
disagree leave a coin-flip — and the temptation to split the middle ground.
The fix is structural: check the claim against **three independent anchors**
and let majority rule.

## The three anchor classes

| Anchor | What it claims | Typical sources |
|---|---|---|
| **Declared intent** | what the system *should* be | docs, READMEs, architecture files, code comments, ADRs |
| **Work state** | what we *think we're doing* about it | issue trackers, project boards, open PRs, TODOs |
| **Observed reality** | what the system *is* | live system state, git history, runtime config, logs |

## Procedure

1. **Name the claim precisely.** Not "the doc is stale" but "the doc says
   `TASK_LLM=llama3.2:1b-small`; is that the deployed value?"
2. **Map the claim to its anchors.** For each of the three classes, identify
   where this claim could be checked. At least two must exist; usually all
   three do.
3. **Check at least two — preferably all three** before declaring anything
   stale, drifted, or wrong.
4. **Resolve by majority:**
   - **3 agree** → trust the claim; move on.
   - **2-vs-1** → the minority source has drifted. Fix *that source*, citing
     the two agreeing anchors as evidence.
   - **1-1-1 (all disagree)** → do NOT average, guess, or pick the most
     plausible. Escalate to the human with all three values and where each
     came from. Three-way disagreement means something structural is broken.

## The independence test

Two anchors only count as two if drift in one **cannot mechanically propagate
to the other**:

- A doc and a ConfigMap *generated from that doc* are ONE anchor.
- A board item created by copy-pasting the doc's claim is the same anchor as
  the doc.
- A doc and `kubectl` output are two anchors. Adding the git history of the
  manifest that produced the live state makes three.

## Worked example

A roles doc said the task model default was `1b-small`. The live ConfigMap
said `3b-small`. Two sources, one conflict — which drifted? The third anchor
(the manifest in the deploy repo, plus the PR that changed it) also said
`3b-small`, with a rationale in the PR title. Verdict: the doc was the odd
one out; fix the doc and cite the PR. Without the third anchor, "update the
doc to match live" would have been a guess — live state can drift from
intent too (a hotfix someone forgot to commit looks identical from two
anchors).

## Anti-patterns

- **Splitting the middle ground** — describing both values with "may be
  outdated" hedging instead of resolving which one is true.
- **"The doc is probably stale"** — recency bias. Sometimes live state is
  the drifted one (uncommitted hotfix, manual mutation, failed sync).
- **Two-anchor verdicts on high-stakes claims** — for anything feeding a
  destructive action (delete, overwrite, rollback), require all three.
- **Counting correlated sources twice** — see the independence test.
