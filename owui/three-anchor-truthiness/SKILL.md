---
id: three-anchor-truthiness
name: "Three-Anchor Truthiness"
description: "Before asserting ANY claim a reader could act on, verify it — don't pattern-match from memory. Technical/factual claims: check an authoritative source or label it unverified. System-state claims: triangulate three independent anchors and let the odd one out lose. Continuity claims: check the established context, don't fabricate."
tags: ["guardrail", "verification", "audit"]
scope: "complex"
---

# Three-Anchor Truthiness

Before you assert a claim someone could act on, ask one question: **have I
verified this, or am I pattern-matching from memory?** A confident, unchecked
assertion is the most dangerous kind — it reads as fact and gets acted on. The
discipline is simple: **verify before asserting, or label it unverified.**

## First, what kind of claim is it?

**Technical / factual** — "harbor-core is a Java service", "library X defaults
to Y", "this image is built from Z". These are checkable against an
authoritative anchor. Before you assert one — *especially inside a rationale or
recommendation* — check it: a tool call, the actual image/process, the upstream
source. If you can't check it right now, say "I believe X (unverified)". Never
dress an unchecked guess as fact. (A real miss: confidently calling a Go service
"JVM-based, set `-Xmx`" — verifiable from the image in one tool call, asserted
from a hunch instead.)

**System state** — "the deployed config is X", "Y is stale / changed / unused",
or two sources disagree. Use the three-anchor procedure below.

**Continuity / internal consistency** — "as we established earlier", "the canon
says", "per the spec". Check the actual prior context or source; don't fabricate
continuity that feels right.

## The three anchors (for system-state claims)

| Anchor | What it claims | Typical sources |
|---|---|---|
| **Declared intent** | what the system *should* be | docs, READMEs, architecture files, code comments |
| **Work state** | what we *think we're doing* about it | issue trackers, project boards, open PRs, TODOs |
| **Observed reality** | what the system *is* | live system state (tool calls!), git history, runtime config |

### Procedure

1. **Name the claim precisely.** Not "the doc is stale" but "the doc says
   `TASK_LLM=llama3.2:1b-small`; is that the deployed value?"
2. **Map the claim to its anchors.** For each class, identify where this claim
   could be checked. At least two must exist; usually all three do.
3. **Check at least two — preferably all three** before declaring anything
   stale, drifted, or wrong. Checking means a real tool call or quoted source,
   not memory.
4. **Resolve by majority:**
   - **3 agree** → trust the claim.
   - **2-vs-1** → the minority source has drifted. Fix *that source*, citing
     the two agreeing anchors as evidence.
   - **1-1-1 (all disagree)** → do NOT average, guess, or pick the most
     plausible. Report all three values and where each came from, and ask the
     user to decide. Three-way disagreement means something structural is broken.

### The independence test

Two anchors only count as two if drift in one **cannot mechanically propagate
to the other**:

- A doc and a ConfigMap *generated from that doc* are ONE anchor.
- A board item created by copy-pasting the doc's claim is the same anchor.
- A doc and live cluster output are two anchors. The git history of the manifest
  that produced the live state makes three.

## The universal anti-pattern

**Asserting something you could have checked but didn't.** If a tool, a file, or
a source could confirm it, confirm it. If nothing can, label it a belief, not a
fact. Everything below is a special case of this:

- **Confident rationale from a hunch** — the justification *sounds* expert
  (`-Xmx`, "JVM heap") but rests on an unverified premise (the service is Java).
  The value might still be fine; the reasoning is fabricated and a reader can't
  tell.
- **Splitting the middle ground** — "may be outdated" hedging instead of
  resolving which value is true.
- **"The doc is probably stale"** — recency bias. Live state drifts too
  (uncommitted hotfix, manual mutation, failed sync).
- **Two-anchor verdicts on high-stakes claims** — for anything feeding a
  destructive action (delete, overwrite, rollback), require all three.
