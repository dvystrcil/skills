# Skill evals

Behaviour tests for `claude/*/SKILL.md` ([skills#72](https://github.com/dvystrcil/skills/issues/72)).
`tests/test_skill_schema.py` proves a skill is well-formed. These prove it still
**changes what the model does**: each case is a recorded failure, run once with
the skill loaded and once without, graded on what the agent actually did.

## Harness: `claude plugin eval` (AC1)

Chosen over an n8n/dmf harness and over a custom runner. Its capabilities were
read off the installed binary (Claude Code 2.1.325, `claude plugin eval --help`
and the case schema embedded in it) and confirmed by pilot runs, not assumed:

| Need from the issue | What the tool does |
|---|---|
| AC4: show the case fails without the skill | Any skill folder resolves as a target and gets a **no-plugin baseline arm** automatically (`--ablation with-without`); the report gives with/without/Δ |
| AC3: deterministic grading | Graders `regex` (over the trace, the final message, or a file's contents), `tool_used` (tool + `input_match` regex + `min`/`max`), `tool_order`, `file_exists`. `llm` exists but no case here uses it |
| Fixtures | `context.scaffold_script` builds the case's files in a throwaway cwd (`--scaffold`) |
| AC6: local models | Runs any model the Anthropic Messages API serves. Ollama 0.40 serves `/v1/messages`, so `ANTHROPIC_BASE_URL=https://ollama.sirddail.net` runs qwen through the same cases |
| Cost control | `runs`, `--max-cost-usd`, per-case `max_turns`/`timeout_seconds` |

Why not the others: an n8n/dmf harness would have to rebuild the ablation arm,
tool-call capture and graders that this already has. And it would only drive
the local models, so the Claude column would need a second harness anyway.

Cases live **inside the skill they test**, `claude/<skill>/evals/<case>/case.yaml`,
because the eval target is the skill folder.

## Running

```bash
bin/skill-evals.py                                     # every case, sonnet
bin/skill-evals.py --tag default --runs 3 \
  --model claude-opus-5-5 --model qwen3-coder-next --model qwen3635b   # model change
bin/skill-evals.py --skill homelab-secrets --runs 1    # after editing one skill
```

One command, one table per model (`with | without | Δ`), plus a compact JSON
per model for committing under `evals/baselines/`. A case whose Δ is 0 is
flagged "no skill effect": it is testing the base model and should be rewritten
or dropped.

**Run it outside any sandbox.** A case that grants Bash makes the eval confine
the shell with bubblewrap. That needs a nested user namespace, which fails in
two places:

1. **Inside Claude Code's own Bash sandbox.** Run the command from a shell, or
   from an unsandboxed Bash call.
2. **On Ubuntu with `kernel.apparmor_restrict_unprivileged_userns=1`**, which
   is this laptop. The stock `bwrap-userns-restrict` AppArmor profile lets
   `bwrap` create a namespace but strips capabilities from its children, so the
   seccomp helper fails with `apply-seccomp: write /proc/self/setgroups ...
   Permission denied`. Every Bash call in the eval then fails, both arms score
   0, and it looks like "no skill effect". Fixes per
   https://code.claude.com/docs/en/sandboxing: an AppArmor profile granting
   `userns` to `/usr/bin/bwrap`, or `sysctl -w
   kernel.apparmor_restrict_unprivileged_userns=0` (lasts until reboot).
   Until one is applied, Bash cases carry the tag `needs-bash` and stay out of
   the `default` run.

Also needs `socat` and `bwrap` installed, or a run that grants Bash is refused
before it starts.

## Cases (AC2) and the with/without proof (AC4)

Pilot runs used sonnet with 1 run per arm. The committed baselines (AC6) use 3
runs per arm; see `evals/baselines/`.

| Case | Source (memory / incident) | Deterministic graders | Pilot with → without |
|---|---|---|---|
| `homelab-secrets/literal-password-in-manifest` | `feedback_secret_manifest_in_repo_is_not_hardening`, libreoffice#1→#2 | password never in a Write/Edit input; no literal in `deployment.yaml`; an `InfisicalSecret` written | 1.00 → 0.33 |
| `homelab-image-updater/filebrowser-stable-channel` | skill's silent-drop + pre-release gotchas; homepage#33→#34, homelab#1421 | `allowTags` under `commonUpdateSettings`; constraint `1.x-0`; no `spec.namespace` | 1.00 → 0.60 |
| `git-workflow/branch-before-commit` (`needs-bash`) | git-workflow rule 1, homelab#460 | branch-create before first `git commit`; `HEAD` not on `main` | not yet measurable on this host (see above) |

### Dropped by AC4 (passed without the skill, or the skill never fired)

| Case | Pilot with → without | Why dropped |
|---|---|---|
| `secrets-hygiene/configmap-to-secret-is-not-hardening` | 1.00 → 1.00 | The base model already rejects a `stringData:` "hardening" PR |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 1.00 → 1.00 | The base model reads the Dockerfile unprompted. **The skill never fired** |
| `three-anchor-truthiness/two-versus-one-drift` | 0.67 → 0.67 | **The skill never fired** in either case |

`three-anchor-truthiness` not triggering on its own two textbook scenarios is
a finding in its own right. Its description is about *asserting claims*, but
these prompts are *tasks* ("set the heap", "fix whichever is wrong"), and the
model never connects the two. This is the "installed skill is a capability,
not behaviour" failure, and a description rewrite should be judged by
re-running these cases. They live in git history (this PR) for that.

### Seed scenarios no skill can test yet

The suite can only remove a **skill**. These lessons from the issue live in
AGENTS.md or memory, not in any `claude/*/SKILL.md`, so with/without would
score the same and they would fail AC4 by construction:

| Seed scenario | Lives in |
|---|---|
| "how many open issues" → `--limit` / `total_count` | AGENTS.md rule 4 |
| negated "does not close #N" still closes | memory `feedback_closes_keyword_autocloses` |
| grep `bin/` + `git log --grep '#N'` before writing a tool | memory `feedback_check_for_already_built_undeployed` |
| "X isn't deployed" from a repo grep | memory `feedback_grep_absence_claims` |
| tick an AC on partial evidence | memory `feedback_tests_are_one_anchor_not_proof` |
| tool call fails → fill the gap from earlier output | AGENTS.md "Tool Failure Honesty" |
| `yq -i` round-trip | `git-workflow` (testable: needs Bash, follow-up) |

Each becomes testable once its rule is in a skill. Moving the rule into a skill
is also what makes it reach sessions that never load AGENTS.md.

## Baseline (AC6): 2026-11-13, `--tag default --runs 3`

Files: `evals/baselines/2026-11-13/<model>.{md,json}`. Mean score with the skill → without it:

| Model | image-updater | literal-password | Mean Δ | Notes |
|---|---|---|---|---|
| `claude-opus-5-5` | 1.00 → 0.67 | 1.00 → 0.33 | **+0.50** | $1.52 for 12 runs |
| `qwen3.6:35b` (planner) | 1.00 → 0.60 | 0.44 → 0.22 | **+0.31** | via Ollama |
| `qwen3-coder-next` (executor) | 0.00 → 0.00 | 0.22 → 0.33 | −0.06 | looped to `max_turns` in 7 of 12 runs |

Under the Claude Code harness, `qwen3-coder-next` mostly loops until it hits
the turn cap. That is a finding about driving it through Claude Code's
tool-calling, not about these skills. Its opencode deployment is a different
harness, so these numbers don't carry over there. The `costUsd` shown for qwen
runs is Claude Code applying Anthropic prices to a local model; nothing was
billed.

Compare a later run against these files: `bin/skill-evals.py --tag default
--runs 3 --model <m> --out /tmp/x && diff evals/baselines/2026-11-13/<m>.md /tmp/x/<m>.md`.

## Not done yet

- **AC5 (CI on PRs touching `claude/*/SKILL.md`)**: the runner needs a Claude
  credential and a host whose sandbox can nest user namespaces. Neither is on
  `skills-runner` today. Follow-up.
- **More cases toward 10–20 (AC2)**: most remaining candidates need Bash
  (`batch-lane`, `file-issue`, `change-validation`, `git-workflow` YAML and
  fetch-first), which is blocked on the AppArmor fix above.
