---
name: three-anchor-truthiness
description: "Use before asserting ANY claim a reader could act on — don't pattern-match from memory. Technical/factual claims: check an authoritative source or label it unverified. System-state claims (drift, 'X is stale/changed/unused', two sources disagreeing): triangulate three independent anchors and let the odd one out lose. Continuity claims: check the established context."
---

# Three-Anchor Truthiness

Before you assert a claim someone could act on, ask one question: **have I
verified this, or am I pattern-matching from memory?** A confident, unchecked
assertion is the most dangerous kind — it reads as fact and gets acted on. The
discipline: **verify before asserting, or label it unverified.**

## First, what kind of claim is it?

**Technical / factual** — "harbor-core is a Java service", "library X defaults
to Y", "this image is built from Z". Checkable against an authoritative anchor.
Before asserting one — *especially inside a rationale or recommendation* — check
it: a tool call, the actual image/process, the upstream source. Can't check it
now? Say "I believe X (unverified)". Never dress an unchecked guess as fact. (A
real miss: confidently calling a Go service "JVM-based, set `-Xmx`" — verifiable
from the image in one tool call, asserted from a hunch instead.)

**System state** — "the deployed config is X", "Y is stale / changed / unused",
or two sources disagree. Use the three-anchor procedure below.

**Continuity / internal consistency** — "as we established", "the canon says",
"per the spec". Check the actual prior context or source; don't fabricate
continuity that feels right.

## The three anchors (for system-state claims)

| Anchor | What it claims | Typical sources |
|---|---|---|
| **Declared intent** | what the system *should* be | docs, READMEs, architecture files, code comments, ADRs |
| **Work state** | what we *think we're doing* about it | issue trackers, project boards, open PRs, TODOs |
| **Observed reality** | what the system *is* | live system state, git history, runtime config, logs |

### Procedure

1. **Name the claim precisely.** Not "the doc is stale" but "the doc says
   `TASK_LLM=llama3.2:1b-small`; is that the deployed value?"
2. **Map the claim to its anchors.** For each of the three classes, identify
   where this claim could be checked. At least two must exist; usually all three
   do.
3. **Check at least two — preferably all three** before declaring anything
   stale, drifted, or wrong.
4. **Resolve by majority:**
   - **3 agree** → trust the claim; move on.
   - **2-vs-1** → the minority source has drifted. Fix *that source*, citing the
     two agreeing anchors as evidence.
   - **1-1-1 (all disagree)** → do NOT average, guess, or pick the most
     plausible. Escalate to the human with all three values and where each came
     from. Three-way disagreement means something structural is broken.

### The independence test

Two anchors only count as two if drift in one **cannot mechanically propagate to
the other**:

- A doc and a ConfigMap *generated from that doc* are ONE anchor.
- A board item created by copy-pasting the doc's claim is the same anchor.
- A doc and `kubectl` output are two anchors. Adding the git history of the
  manifest that produced the live state makes three.

### Worked example

A roles doc said the task model default was `1b-small`. The live ConfigMap said
`3b-small`. Two sources, one conflict — which drifted? The third anchor (the
manifest in the deploy repo, plus the PR that changed it) also said `3b-small`,
with a rationale in the PR title. Verdict: the doc was the odd one out; fix the
doc and cite the PR. Without the third anchor, "update the doc to match live"
would have been a guess — live state can drift from intent too (a hotfix someone
forgot to commit looks identical from two anchors).

## The universal anti-pattern

**Asserting something you could have checked but didn't.** If a tool, a file, or
a source could confirm it, confirm it. If nothing can, label it a belief, not a
fact. Special cases:

- **Confident rationale from a hunch** — the justification *sounds* expert
  (`-Xmx`, "JVM heap") but rests on an unverified premise. The value might be
  fine; the reasoning is fabricated and a reader can't tell.
- **Splitting the middle ground** — hedging with "may be outdated" instead of
  resolving which value is true.
- **"The doc is probably stale"** — recency bias. Live state drifts too.
- **Two-anchor verdicts on high-stakes claims** — for anything feeding a
  destructive action (delete, overwrite, rollback), require all three.
