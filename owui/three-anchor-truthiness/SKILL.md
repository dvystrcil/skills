---
name: "Three-Anchor Truthiness"
description: "When verifying a claim about system state, or when two sources disagree, never split the difference — check a third independent anchor and let the odd one out lose."
tags: ["guardrail", "verification", "audit"]
scope: "complex"
---

# Three-Anchor Truthiness

A claim verified against one source is an assumption. Two sources that
disagree leave a coin-flip — and the temptation to split the middle ground.
The fix is structural: check the claim against **three independent anchors**
and let majority rule.

## The three anchor classes

| Anchor | What it claims | Typical sources |
|---|---|---|
| **Declared intent** | what the system *should* be | docs, READMEs, architecture files, code comments |
| **Work state** | what we *think we're doing* about it | issue trackers, project boards, open PRs, TODOs |
| **Observed reality** | what the system *is* | live system state (tool calls!), git history, runtime config |

## Procedure

1. **Name the claim precisely.** Not "the doc is stale" but "the doc says
   `TASK_LLM=llama3.2:1b-small`; is that the deployed value?"
2. **Map the claim to its anchors.** For each class, identify where this
   claim could be checked. At least two must exist; usually all three do.
3. **Check at least two — preferably all three** before declaring anything
   stale, drifted, or wrong. Checking means a real tool call or quoted
   source, not memory.
4. **Resolve by majority:**
   - **3 agree** → trust the claim.
   - **2-vs-1** → the minority source has drifted. Fix *that source*, citing
     the two agreeing anchors as evidence.
   - **1-1-1 (all disagree)** → do NOT average, guess, or pick the most
     plausible. Report all three values and where each came from, and ask
     the user to decide. Three-way disagreement means something structural
     is broken.

## The independence test

Two anchors only count as two if drift in one **cannot mechanically propagate
to the other**:

- A doc and a ConfigMap *generated from that doc* are ONE anchor.
- A board item created by copy-pasting the doc's claim is the same anchor as
  the doc.
- A doc and live cluster output are two anchors. The git history of the
  manifest that produced the live state makes three.

## Anti-patterns

- **Splitting the middle ground** — describing both values with "may be
  outdated" hedging instead of resolving which one is true.
- **"The doc is probably stale"** — recency bias. Sometimes live state is
  the drifted one (uncommitted hotfix, manual mutation, failed sync).
- **Two-anchor verdicts on high-stakes claims** — for anything feeding a
  destructive action (delete, overwrite, rollback), require all three.
- **Counting correlated sources twice** — see the independence test.
