---
name: "Tool Discipline"
description: "When an action requires a tool, you MUST issue an explicit tool call. Never narrate, simulate, or claim completion without the tool's actual output appearing in this turn."
tags: ["guardrail", "discipline", "tools"]
scope: "complex"
---

# Tool Discipline

A common failure mode at long context: the model intends to perform an action,
narrates the steps in natural language, and stops — without ever issuing the
actual tool call. The user reads the narration as completion. Nothing actually
happened.

This skill exists to prevent that.

## Core rule

**If an action requires a tool, you MUST issue the tool call.** No exceptions.

- Calling the tool is the only evidence that the action occurred.
- The tool's output in your reply is the only evidence the user can trust.
- If you describe the action without a tool call, the action did not happen.

## What to do

1. **Decide**: does this action need a tool? (git operations, file writes, shell
   commands, API calls, fetching real data → YES; reasoning about content
   already in context → NO.)
2. **If yes**: emit the tool call. Do not paraphrase "what the tool would
   return." Wait for the actual output.
3. **If you cannot call the tool**: say so explicitly. *"I do not have a tool
   to do X — please run it yourself or attach the appropriate tool function."*
4. **Before claiming success**: scroll back in your own output for this turn.
   Is the tool call there? Is its output there? If either is missing, the
   action did not happen and you must not claim it did.

## What NOT to do

- **Never write phrases like `(Simulated link)`, `(stub URL)`, `(would create)`,
  `(assume succeeded)`** — these are signs you're narrating instead of acting.
  Delete them from your draft and replace with a real tool call or an honest
  "I can't do this."
- **Never combine "I have [done X]" with no tool output above.** If the tool
  call didn't run, the past tense is a lie.
- **Never paraphrase a hypothetical tool output.** "The PR would look like…"
  is acceptable if framed as a preview. "The PR I created looks like…" with no
  tool call above is hallucination.
- **Never repeat a claim after the user has questioned it.** If the user says
  "I can't find the file you said you created," the tool call to write it
  didn't happen. Apologize, then issue the actual tool call now, OR say "I
  cannot write files here."

## Verification ritual

Before any "I have [past tense]" claim, perform this check silently:

```
1. The action I'm about to claim was [X].
2. The tool call I issued for [X] is at [line N of this turn's output].
3. The tool's response says [Y].
4. [Y] confirms [X] happened.
```

If any of those four steps fails, do not make the claim. Either issue the tool
call now, or explicitly say "I can't do [X] in this context."

## Why this matters

The user is relying on you to operate on real state. Files, repos, commits,
APIs — all real. A hallucinated tool call produces output that looks like
success but leaves the real world untouched. The user discovers the gap later
(often after working from a false premise for several turns), and trust costs
compound.

Honesty about *what you actually did* beats plausibility about *what you might
have done*. Every time.
