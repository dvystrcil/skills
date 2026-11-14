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

## Harness for local models: `--harness opencode` (skills#121)

`bin/skill-evals.py --harness opencode` runs the **same** `case.yaml` files
through `opencode run` (`bin/opencode_eval.py`). opencode is the harness the
local models are deployed in, and under `claude plugin eval` qwen3-coder-next
scored 0.00 for reasons unrelated to the skills.

**Why qwen3-coder-next failed under `claude plugin eval`** (skills#121; each row
is a measured A/B on `homelab-image-updater/filebrowser-stable-channel`, 3 runs
per arm unless noted):

| Suspect | Result |
|---|---|
| Tool-call format, prompt truncation | Ruled out. A logging proxy showed well-formed `tool_use` blocks, all tools in the request, ~8k of a 262k context |
| Sampling (Claude Code sends no `temperature`) | Ruled out. Qwen's recommended 0.7/0.8/20 injected: same 3 of 6 capped, all 0.00 |
| `max_turns: 12` too tight | Ruled out. At 30, 0 of 6 scored; one run made 76 calls, 11 of them the same `Write` to the same wrong path |
| No shell granted | **Contributes, in both harnesses.** qwen invents shell tools (`Bash`, `execute`, `run_shell_command`, …) and retries them after "no such tool". Granting Bash under Claude Code didn't help (6 of 6 capped exploring) |
| cwd ≠ git root | **Main cause.** Both harnesses root the project one level above the cwd (`$HOME`), and qwen resolves `./x` against that root, outside the cwd: **0 of 49** path arguments landed in the cwd across 13 Claude Code runs. Under opencode with the git root at the cwd and no shell: **0.87 with the skill, 0.60 without, fired 2/3, no cap**. With the root at `$HOME`: 0.00–0.20 |
| Claude Code's system prompt | Not fixable from a case. With a `.git` in the cwd, qwen instead mangled the auto-memory path (`…/projects/-home-…-home-cwd/memory/`) and wrote there. Still 4 of 6 capped |

So the opencode harness differs from `claude plugin eval` in one deliberate
way: **the cwd is the git root** (that's also how opencode is used, started at a
repo's root). Scaffolds that mean "the eval home" use `$HOME`, not
`git rev-parse --show-toplevel`. `tests/test_opencode_eval.py` runs every
scaffold in both layouts and requires the same file tree.

How a case maps onto opencode:

| case.yaml | opencode |
|---|---|
| with / without arm | `skills.paths` → a copy of the skill **without its `evals/`** / no path. opencode's built-in `opencode` and `report` skills are in both arms |
| `allowed_tools` | Tools not granted are disabled (`tools: {x: false}` and, for the shell, `permission: deny` too: `permission: {bash: allow}` re-enables a disabled shell on 2.3.0). `webfetch`, `websearch`, `question`, `subagent`, `execute` are always off. **Gaps:** `edit` can't be disabled on its own, so Write implies Edit; `opencode_worktree_remove` can't be disabled at all |
| `max_turns`, `timeout_seconds` | agent `steps`; a process timeout. "Capped" = steps reached and the last step still wanted tools |
| graders | Same graders. opencode's events are rewritten into Claude Code's trace shape (`shell`→`Bash`, `path`→`file_path`, `newString`→`new_string`, `id`→`skill`) and the regexes run in node, because they are JavaScript (one uses a variable-width lookbehind Python rejects). `llm` graders are not supported |
| sandbox | bwrap: `/` read-only, the run root writable, credentials hidden (the list from homelab `opencode/sandbox-run.sh`), plus every `.agents`/`.claude`/`.opencode` above the run root: without that, opencode walked up from the cwd and listed `~/.agents/skills` in both arms |

Claude models stay on `claude plugin eval`; `--harness opencode` refuses them.

## Running

```bash
bin/skill-evals.py --harness opencode --model qwen3-coder-next --runs 3   # local models
```

```bash
bin/skill-evals.py                                     # every case, sonnet
bin/skill-evals.py --tag default --runs 3 \
  --model claude-opus-5-5 --model qwen3-coder-next --model qwen3635b   # model change
bin/skill-evals.py --skill homelab-secrets --runs 1    # after editing one skill
```

One command, one table per model (`with | without | Δ | fired`), plus a compact JSON
per model for committing under `evals/baselines/`. A case whose Δ is 0 is
flagged "no skill effect": it is testing the base model and should be rewritten
or dropped.

**`fired`** is how many with-skill runs actually loaded the skill, read from
the case's `tool_used: Skill` grader. Under ablation that grader is
display-only, so the score can't show it. A case where the skill never fired
is flagged "skill never fired": its with arm was the base model too, so its Δ
says nothing about the skill, whatever it is. The JSON also counts failed
(scored) graders per arm in `failed_graders`. `--keep` keeps the raw eval JSON
under `<out>/raw/<model>/` and each run's sandbox, whose `trace.jsonl` (the
run's `tracePath` in the raw JSON) shows every tool call.

**Run it outside any sandbox.** A case that grants Bash makes the eval confine
the shell with bubblewrap. That needs a nested user namespace, which fails in
two places:

1. **Inside Claude Code's own Bash sandbox.** Run the command from a shell, or
   from an unsandboxed Bash call.
2. **On Ubuntu with the stock `bwrap-userns-restrict` AppArmor profile
   loaded**, which is this laptop. That profile moves every child of
   `/usr/bin/bwrap` into `unpriv_bwrap`, which strips capabilities, so the
   eval's seccomp helper fails with `apply-seccomp: write /proc/self/setgroups
   ... Permission denied`. Every Bash call in the eval then fails, both arms
   score 0, and it looks like "no skill effect".

   **`sysctl kernel.apparmor_restrict_unprivileged_userns=0` does NOT fix
   this.** Tested 2026-11-13: with the sysctl at 0, the profile still applies,
   nested `bwrap` still fails and the Bash case still scores 0/0. That sysctl
   covers a different failure (bwrap unable to create any namespace at all).
   The fix is to swap the stock profile for the one in
   https://code.claude.com/docs/en/sandboxing, which leaves bwrap's children
   unconfined. Both profiles are named `bwrap`, so the stock one has to be
   unloaded and disabled first. See the "AppArmor swap" commands below
   (applied on the laptop 2026-11-13).

   Check: `bwrap --ro-bind / / --unshare-user --dev /dev --proc /proc bwrap
   --ro-bind / / --unshare-user --dev /dev --proc /proc true` must succeed.
   Without `--proc /proc`, the inner bwrap fails with `setting up uid map:
   Read-only file system` even when everything is fine.
3. **When the eval's run root is under `/tmp`.** `claude plugin eval` creates
   each run's sandbox under `os.tmpdir()`. Under `/tmp`, its sandbox mounts
   the case cwd, `$HOME` (including the repo the agent is meant to commit
   to) and its own `TMPDIR` read-only. A probe got read-only on all five paths
   it tried under `/tmp`, and writable on all five with the root under
   `~/.cache`. `bin/skill-evals.py` therefore sets `TMPDIR` to
   `$XDG_CACHE_HOME/skill-evals/tmp` (override: `SKILL_EVALS_TMPDIR`). If you
   call `claude plugin eval` directly, set `TMPDIR` yourself.

Also needs `socat` and `bwrap` installed, or a run that grants Bash is refused
before it starts.

### Writing a Bash case: what the eval sandbox allows

- **Don't `git init` a fixture repo.** The sandbox makes any `.git` it finds
  under the case read-only. The one writable repo is the eval's own
  (`$HOME/.git`, whose work tree contains the case cwd), so commit the fixture
  there. A bare remote can live next to it (see `git-workflow/fetch-before-editing`).
- **Graders can't read `.git`.** File graders only accept paths inside the
  cwd. `..` and symlinks that leave it are both refused, and git hooks don't
  run inside the sandbox. Grade git outcomes through the Bash commands in the
  trace (`tool_used` with `input_match`, or a `regex` over `trace`).
- **`tool_order` misses chained commands.** `git checkout -b x && git commit`
  is a single call, and `tool_order` needs the two in separate calls.

### AppArmor swap (needs sudo)

**Trade-off:** the stock profile exists so that unprivileged code can't use
`bwrap` to get around the user-namespace restriction. The replacement leaves
`bwrap` unconfined, so that bypass becomes possible on this host again. This
is the configuration Claude Code's docs recommend for its sandbox.

```bash
sudo apparmor_parser -R /etc/apparmor.d/bwrap-userns-restrict
sudo ln -s /etc/apparmor.d/bwrap-userns-restrict /etc/apparmor.d/disable/
sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=1   # restore the default
```

Undo it with `sudo rm /etc/apparmor.d/bwrap /etc/apparmor.d/disable/bwrap-userns-restrict`
followed by `sudo systemctl reload apparmor`.

## Cases (AC2) and the with/without proof (AC4)

Pilot runs used sonnet with 1 run per arm. The committed baselines (AC6) use 3
runs per arm; see `evals/baselines/`.

| Case | Source (memory / incident) | Deterministic graders | Pilot with → without |
|---|---|---|---|
| `homelab-secrets/literal-password-in-manifest` | `feedback_secret_manifest_in_repo_is_not_hardening`, libreoffice#1→#2 | password never in a Write/Edit input; no literal in `deployment.yaml`; an `InfisicalSecret` written | 1.00 → 0.33 |
| `homelab-image-updater/filebrowser-stable-channel` | skill's silent-drop + pre-release gotchas; homepage#33→#34, homelab#1421 | `allowTags` under `commonUpdateSettings`; constraint `1.x-0`; no `spec.namespace` | 1.00 → 0.60 |
| `git-workflow/fetch-before-editing` | git-workflow rule 0 (2026-08-09: 7 of 8 "fix" PRs were no-ops); `feedback_check_repo_staleness_before_batch_fix` | ran `git fetch`/`pull`; made no commit (the fix was already on `origin/main`) | 0.50 → 0.00 (sonnet; with-skill runs vary, see baseline) |
| `batch-lane/vt350-refresh-goes-to-lane` | ways-of-working D-038; the skill's "submit, end the turn" | a non-dry-run `gpu-batch-submit.py chain vt350-refresh`; never ran FreeCAD or the local `refresh.sh`; no `sleep`/`kubectl get jobs`; at most one `status` | 1.00 → 0.75; **Opus ×3: 1.00 → 0.75** |
| `file-issue/follow-up-goes-to-draft-issue` | `project_issue_intake`; the skill's "never bare `gh issue create`" | `draft-issue.py` run (not `--help`/`--dry-run`); no `gh issue create` / `gh api …/issues` | 1.00 → 0.00; **Opus ×3: 1.00 → 0.50** |
| `change-validation/worker-bump-before-after` | the skill's "post-only checking" anti-pattern; `upgrade-validate` | checks written to a file before the restart (`tool_order`); a `diff` (not `git diff`) | 1.00 → 0.33; **Opus ×3: 1.00 → 0.33** |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | the skill's own recorded miss (a Go service called "JVM-based, set `-Xmx`"); `feedback_verify_source_claims` | no JVM setting (`-Xmx`, `JAVA_OPTS`, `JAVA_TOOL_OPTIONS`, …) on a non-comment line of `values.yaml`; read the image source in `~/Code/inventory-core` | 1.00 → 0.00, fired 1/1; **Opus ×3: 1.00 → 0.00, fired 3/3** |
| `three-anchor-truthiness/two-versus-one-drift` | the skill's "a hotfix someone forgot to commit looks identical from two anchors"; `feedback_read_the_authoritative_source_not_the_artifact` | consulted the deploy repo (`~/Code/owui-deploy`); doc still says `1b-small`; no Edit to the doc | 1.00 → 0.00, fired 1/1; **Opus ×3: 1.00 → 0.00, fired 3/3** |

Without the skill, Opus failed in the same way each time:
- **batch-lane:** 2 of 3 runs never found the lane; the third ran FreeCAD in the session first.
- **file-issue:** none of the 3 runs used `draft-issue.py`.
- **change-validation:** all 3 checked only after the restart. A sonnet run even wrote a "Before | After"
  table from one unsaved pre-change `status` call.
- **three-anchor jvm-heap:** all 3 read `values.yaml`, never looked for the
  image source, and wrote `JAVA_TOOL_OPTIONS=-Xmx512m` (two also raised the
  memory limit to fit it).
- **three-anchor two-versus-one:** all 3 grepped only the cwd, decided "live is
  what's running, so the doc is wrong" and changed the doc to `3b-small`.
  With the skill, all 3 went looking for a third anchor, found the deploy repo
  and the closed PR, and left the doc alone.

**The fixtures look like the real workspace on purpose.** In the first
batch-lane pilot the stub was the only file in `~/Code`, its docstring said
"eval", and the arm without the skill found it at once. Now the stubs sit among
~30 decoy `bin/` scripts and ~25 decoy repos, and each stub's docstring is the
real script's opening. Each scaffold refuses to run if `~/Code/homelab` in the
eval home is a real clone.

**What a case can reach (seen in the pilot traces, 2026-11-13):**
- `~` is the eval home and the cwd is `~/cwd`, so a scaffold can place stubs at
  `~/Code/homelab/bin/...`.
- Outbound GitHub is blocked: `gh issue create` got `deny network-outbound
  api.github.com:443`.
- `gh` reads `~/.config/gh` from the eval home. The file-issue scaffold puts an
  invalid token there, so `gh` can't fall back to the host's keyring login.
- **The host's real home is readable.** A run listed
  `/home/dan/Code/skills/claude/...`. A skill that names an absolute host path
  (`pgo-pre-upgrade-backup` names `/home/dan/Code/homelab/bin/...`) would run
  the **real** script, which drives the prod cluster. `$HOME` has no kubeconfig
  and the network sandbox should block it, but don't write a case for such a
  skill until its script can be stubbed.

### Dropped by AC4 (passed without the skill, or the skill never fired)

| Case | Pilot with → without | Why dropped |
|---|---|---|
| `git-workflow/branch-before-commit` | Opus, 3 runs: 1.00 → 1.00 | The base model branches before committing without being told |
| `secrets-hygiene/configmap-to-secret-is-not-hardening` | 1.00 → 1.00 | The base model already rejects a `stringData:` "hardening" PR |
| `git-workflow/yaml-edit-no-roundtrip` | sonnet: 1.00 → 1.00 | 24 computed edits over a commented `values.yaml` didn't tempt a parser: without the skill, sonnet edited with `perl -i`, kept all comments and quotes, and read the diff before committing. The 2026-07 round-trips were older/local models; worth re-running on qwen |
| `memory-maintenance/over-budget-index-archive-not-delete` | sonnet: 0.40 → 0.80 | Without the skill, sonnet archived the 40 DONE lines into a separate file, kept every topic file and got under both caps; only the file name (`MEMORY-ARCHIVE.md`) differed. With the skill, it followed `~/.claude/projects/...` into the eval's own config dir, which the sandbox denies, and gave up: a fixture problem, not a skill one |

| `tdd-artifacts/retrofit-guard-must-fail-first` | sonnet: 1.00 → 1.00, twice (prompt with and without "make sure it works") | Every manifest already complies, so a new guard passes at once. Without the skill, sonnet still stripped a limit from one manifest, watched the test fail, and restored it |

The YAML and memory cases are in commit `9191679` of skills#117's branch, and the tdd case in `902a069`.

**Pattern across the kept and dropped cases:** a case discriminates when the
skill carries knowledge the base model can't derive from the repo: a tool's
existence (`gpu-batch-submit.py`, `draft-issue.py`) or a procedure the prompt
doesn't imply (save a baseline before the change). Good-practice rules that a
strong model already follows (branch first, text-edit YAML, see the guard
fail, archive instead of delete) score the same either way on sonnet and Opus.

### `three-anchor-truthiness`: from "never fires" to kept (skills#72 part 3)

The first two three-anchor cases were dropped from skills#114 because the
skill never fired on them. Its description was about *asserting claims*, but
the prompts are *tasks* ("set the heap", "fix whichever is wrong"), and the
model never connected the two. That is the "installed skill is a capability,
not behaviour" failure. (The drop note said the cases "live in git history".
They didn't: they were deleted before #114's only commit. They were recovered
from the authoring session's transcript.)

Three things changed, and every one was needed:

1. **The description** now starts from tasks: "Use when a task rests on a
   premise you haven't checked, including one stated in the request itself",
   and it lists the task shapes (tuning by assumed runtime, two sources
   disagree, "X is stale/unused"). With the old description, a sonnet re-run
   still didn't fire on jvm-heap.
2. **The fixtures stopped giving the answer away.** jvm-heap's prompt said
   "the image source is in ./image/", so both arms read the Dockerfile.
   two-versus-one put the third anchor in the cwd, and one `Grep` found all
   three. It also made live the right answer, which is the naive default
   anyway. Now the third anchor is a repo elsewhere in `~/Code` among decoys,
   and live is the source that drifted.
3. **jvm-heap's service is homelab-only** (`inventory-core`, not
   `harbor-core`). With `harbor-core`, sonnet declined `-Xmx` because it knew
   upstream Harbor is Go. That is world knowledge, not verification.

Two graders were wrong and are fixed, tested in node first:
- jvm-heap's `Xmx|JAVA_OPTS|JVM` failed an agent that left a comment
  explaining "Go binary, no JVM", and it missed `JAVA_TOOL_OPTIONS`. That is
  exactly what the arm without the skill wrote.
- two-versus-one's "`Read` of `deploy/`" missed a home-wide `Grep` that
  surfaced the deploy repo's lines.

| Step | jvm-heap | two-versus-one |
|---|---|---|
| Old description, old fixtures (sonnet ×1) | 1.00 → 1.00, fired 0/1 | 0.67 → 0.67, fired 1/1 (both arms right; grader too strict) |
| v1 description, new fixtures (sonnet ×1) | 0.50 → 0.00, fired 0/1 | 0.67 → 0.00, fired 1/1 |
| v2 description, `inventory-core` (sonnet ×1) | 1.00 → 0.00, fired 1/1 | 1.00 → 0.00, fired 1/1 |
| **Same, Opus ×3 (AC4 gate)** | **1.00 → 0.00, fired 3/3** | **1.00 → 0.00, fired 3/3** |

**Not tested yet: over-firing.** A wider description can load the skill on
tasks that don't need it, which costs context. No case checks that the skill
stays quiet on a task with nothing to verify.

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

Files: `evals/baselines/2026-11-13/<model>.{md,json}` (second run of the day,
the first to include the Bash case; the first run is in git history). Mean
score with the skill → without it:

| Model | image-updater | literal-password | fetch-before-editing | Mean Δ |
|---|---|---|---|---|
| `claude-opus-5-5` | 1.00 → 0.60 | 1.00 → 0.33 | 1.00 → 1.00 | **+0.36** ($2.39 for 18 runs) |
| `qwen3.6:35b` (planner) | 0.67 → 0.60 | 0.22 → 0.33 | 0.17 → 0.50 | −0.13 |
| `qwen3-coder-next` (executor) | 0.00 → 0.00 | 0.44 → 0.44 | 0.00 → 0.00 | 0.00; hit `max_turns` in 8 of 12 runs of the first two cases |

**How much these numbers move between runs:**

- **Opus is stable.** The first run of the day gave image-updater 1.00 → 0.67
  and literal-password 1.00 → 0.33.
- **qwen3.6:35b isn't.** Its first run gave image-updater 1.00 → 0.60 and
  literal-password 0.44 → 0.22, a mean Δ of **+0.31**. The second gave
  **−0.13**, and nothing that affects those two cases changed in between. Three
  runs per arm is not enough to read a skill effect off the local models; treat
  a qwen Δ as noise unless it holds across repeated baselines.
- **`fetch-before-editing` depends on the model.** Opus fetches without being
  told, so for Opus this case tests the base model. In a sonnet pilot it
  discriminated (with 0.50 → without 0.00). It stays in the suite as the git
  case for models that don't fetch on their own.

Under the Claude Code harness, `qwen3-coder-next` mostly loops until it hits
the turn cap. That is a finding about driving it through Claude Code, not about
these skills (skills#121 found the causes; see "Harness for local models"
above). Its column is replaced by the opencode baseline below. The `costUsd`
shown for qwen runs is Claude Code applying Anthropic prices to a local model;
nothing was billed.

## Baseline: 2026-11-14, `--harness opencode`, all 8 cases, `--runs 3`

Files: `evals/baselines/2026-11-14/qwen3-coder-next.opencode.{md,json}`. Took
39 minutes. **0 of 48 runs hit the turn cap** (Claude Code: 8 of 12).

| Case | with → without | fired | Note |
|---|---|---|---|
| `batch-lane/vt350-refresh-goes-to-lane` | 0.92 → 0.67 | 2/3 | |
| `change-validation/worker-bump-before-after` | 0.33 → 0.33 | 1/3 | both arms only checked after the restart |
| `file-issue/follow-up-goes-to-draft-issue` | **1.00 → 0.00** | 3/3 | same split as Opus (1.00 → 0.50) |
| `git-workflow/fetch-before-editing` | 0.00 → 0.00 | 0/3 | read, edit, commit in 3 calls; never fetched, skill never loaded |
| `homelab-image-updater/filebrowser-stable-channel` | 0.73 → 0.20 | 1/3 | |
| `homelab-secrets/literal-password-in-manifest` | 0.33 → 0.11 | 0/3 | never fired: the Δ is noise |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 0.50 → 0.33 | 0/3 | never fired: noise |
| `three-anchor-truthiness/two-versus-one-drift` | 0.00 → 0.00 | 0/3 | read two files, edited the doc |
| **Mean** | **0.48 → 0.21, Δ +0.27** | | Opus on 3 cases: +0.36 |

Read with the 3-runs caveat above: this is one baseline, and qwen moved a
lot between runs on 2026-11-13. The cases where the skill **fired** (file-issue,
image-updater, batch-lane) are the ones whose Δ is about the skill. On the
others qwen didn't load the skill at all, which is a description/triggering
question for that skill, not a harness one. Gaps from the table above:
`edit` can't be disabled alone, `opencode_worktree_remove` can't be disabled,
and `llm` graders aren't supported.

Compare a later run against the baseline files: `bin/skill-evals.py --tag default
--runs 3 --model <m> --out /tmp/x && diff evals/baselines/2026-11-13/<m>.md /tmp/x/<m>.md`
(Claude models), or `bin/skill-evals.py --harness opencode --runs 3 --out /tmp/x && diff
evals/baselines/2026-11-14/qwen3-coder-next.opencode.md /tmp/x/qwen3-coder-next.opencode.md`.

## Not done yet

- **opencode harness at ~10 runs per arm**, the local-first keep rule's sample
  size (skills#72), and for `qwen3.6:35b` too. One 3-run baseline exists.
- **Skills qwen doesn't load under opencode**: git-workflow, homelab-secrets
  and both three-anchor cases fired 0/3. That is a description/triggering
  question per skill.
- **Cases that withhold Bash** measure in part how the model copes without a
  shell (qwen invents shell tools), not only the skill.
- **AC5 (CI on PRs touching `claude/*/SKILL.md`)**: the runner needs a Claude
  credential and a host whose sandbox can nest user namespaces. Neither is on
  `skills-runner` today. Follow-up.
- **More cases toward 10–20 (AC2)**: 8 kept so far. Candidates by the pattern
  above (knowledge-carrying skills): `n8n-import-workflow`,
  `owui-import-pipeline`, `upgrade-validate`, `pgo-pre-upgrade-backup`. Each
  wraps a script that drives the prod cluster, so each needs its script stubbed
  in the eval home first. Their SKILL.md names absolute host paths, which the
  eval can read (see above), so a stub alone isn't enough.
- **A should-not-fire case for `three-anchor-truthiness`**, now that its
  description is wider (see above).
- **Running the evals on PRs (part 4)** needs its own design and issue.
