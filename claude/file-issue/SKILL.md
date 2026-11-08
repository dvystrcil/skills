---
name: file-issue
description: File a homelab GitHub issue (idea, todo, follow-up, bug to track) by handing it to the local model with `bin/draft-issue.py` instead of researching and writing it yourself. Use whenever the user says "make/file/open an issue", "track this", "add a todo", or you are about to `gh issue create` a follow-up.
---

# file-issue

Writing an issue in Claude Code costs tokens for work that is mostly
gathering and formatting. `~/Code/homelab/bin/draft-issue.py` does it on the
local model in ~25-50 s and prints 2-3 lines. Design and eval:
`homelab/architecture/issue-intake.md`.

## Default: hand it off

```bash
~/Code/homelab/bin/draft-issue.py "<the idea, one or two sentences>" \
  --context "<facts you already have, each with its source>" \
  [--repo dvystrcil/<name>]      # if you know the owning repo
```

- **Put everything you already know in `--context`**: paths, errors, run
  URLs, numbers, related issue URLs. It goes in as trusted fact, so the
  issue carries your findings without you writing the prose. Related
  issue URLs only make it into the body if they appear here or in the
  script's own search.
- Several ideas means one call each. Don't batch them into one sentence.
- Run it in the background if you have other work. Don't poll it.

| exit | meaning | you do |
|---|---|---|
| 0 | filed: prints `[repo] title … lane=` and the URL | report the URL |
| 5 | `DUPLICATE <url>` + `reason:`: confirmed (the reason quotes the candidate and the titles share most keywords) | report the existing issue; comment on it if you have new facts |
| 2 | `POSSIBLE DUPLICATE <url>` + `reason:`: the model flagged it but the check didn't confirm it. (Rarely: a new candidate appeared between searches, listed by the gate) | `gh issue view <url>`. Same deliverable → report it, file nothing. Only related → re-run the same command with `--ack <url>` |
| 1 | draft failed validation twice | re-run with more `--context`, or use the fallback below |
| 3 | GitHub or Ollama error | say so. Do not silently write it yourself. |

**Don't read the filed issue back** just to admire it. The gate already
checked structure, links, paths and duplicates. Read it only if the user
asks or the one-line title looks wrong. Then fix it with
`gh issue edit --body-file`, not a rewrite from scratch.

## Fallback: you write the body, the gate still files it

Use this when the issue *is* the reasoning you already did: an incident
write-up, a decision with exact numbers, or ACs only you can state
precisely. Write the body to a file using the sections in
`homelab/.github/ISSUE_TEMPLATE/idea.md`, then:

```bash
~/Code/homelab/bin/new-issue.py --repo dvystrcil/<name> --title "..." \
  --body-file /tmp/issue.md --drafter "Claude Code"
# exit 2 lists duplicate candidates: check them, re-run with --ack <url> each
```

Never bare `gh issue create` for a homelab idea. The gate's duplicate search
and template check are the point.

## Lane

The body's `## Lane` says who works it: `opencode` (one repo, known files,
pattern to copy, no design decision) or `claude`. When picking up a
`lane: opencode` issue yourself, consider handing it to opencode instead.
