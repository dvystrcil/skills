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
| Cost control | `runs`, `--max-cost-usd`, per-case `max_turns`/`timeout_seconds`. The report's `costUsd` is an **estimate at API prices**: here Claude Code runs on the claude.ai subscription and nothing is billed per token, and for local models it is Anthropic's price list applied to Ollama tokens. A CI job using an API key would be real billing |

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
bin/skill-evals.py --tag default --runs 10 --model qwen3635b --keep   # primary (local) column, ~3.5 h
bin/skill-evals.py --tag default --runs 3 --model claude-opus-5-5     # Claude column, on demand only
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

## CI on PRs (skills#120)

`.github/workflows/skill-evals.yml` runs on a PR that changes a
`claude/*/SKILL.md` or anything under `claude/*/evals/`. Its steps:

1. **Scope.** `--changed-from origin/main` keeps only the cases of the skills
   the PR touched. It diffs against the merge base, so commits that landed on
   `main` after the branch was cut don't count. A PR that touches a skill with
   no cases passes with "nothing to run".
2. **Run.** `--harness opencode --model qwen3-coder-next --runs 10`, through
   the in-cluster Ollama Service (`SKILL_EVALS_OLLAMA_URL`). At about 37 s per
   run (measured: 160 runs in 99 min), one case takes about 12 minutes.
3. **Gate** (`--gate`). A case fails the job with
   `FAIL: skill X case Y fired k/N or delta <= 2·SE` if the skill never fired
   in the with arm, or if Δ (with − without) doesn't clear twice its standard
   error, computed from the run's own 20 scores. An errored case also fails.
   The rule was `delta <= 0` until the live AC2 test: a gutted file-issue
   skill (generic description, no body) scored with 0.05 vs without 0.00, one
   partial run in ten, and `delta <= 0` passed it. Under 2·SE it fails
   (Δ +0.05, SE 0.05), and the intact skill passes (Δ +0.95, SE 0.05).
4. **Known failures.** `evals/known-failing.txt` lists cases that already fail
   the rule on the PR model, one `skill/case  reason` per line. They print
   `KNOWN:` and don't fail the job, so a PR isn't red for a failure it didn't
   cause. When one passes, the job prints `NOW PASSES: … remove it`. An entry
   that names no case, or has no reason, is an error, so a typo can't quietly
   waive nothing.

   The list holds 6 of the 8 cases (2026-11-14, from the 10-run baseline
   below). All six fail the rule. Two of them (`git-workflow`, Δ +0.05 with
   SE 0.05; `homelab-image-updater`, Δ +0.04 with SE 0.13) passed the old
   `delta <= 0` rule only by noise.

   **So today the gate actually guards only `batch-lane` and `file-issue`.**
   For every other skill the job reports results but can't fail. That's what
   qwen's numbers support; the fix is in the skills (getting qwen to load
   them), not in the gate.
The table, the gate lines and `--keep` traces go to the job summary and a
`skill-evals` artifact.

**Claude never runs on a PR.** No job in `skill-evals.yml` passes a Claude
model or reads a secret.

### Claude on demand: `skill-evals-claude.yml` (AC4)

A `workflow_dispatch`-only job for the Claude column: a Claude model change, or
a fallback candidate. It bills real money (`ANTHROPIC_API_KEY` from Infisical,
per token; the budget is $30 a month), so it's bounded:

| Guard | Value |
|---|---|
| Trigger | dispatch only; never a PR, push or schedule |
| Scope | `skill` is required; `all` runs every default case |
| Runs per arm | 3 by default (Claude's scores are far less noisy than qwen's) |
| Ceiling | `--max-cost-usd` for the **whole run**, default $10, refused above $30. `claude plugin eval`'s own ceiling is per call and the runner calls it once per case, so `bin/skill-evals.py` hands each case what is left and launches none once it's spent |
| Secret | `secret-name: ANTHROPIC_API_KEY`: one secret, not the prod store |

Cost guide (Opus, 2026-11-13, estimated at API prices): about $0.14 per run,
~$0.80 per case at 3 runs per arm, ~$6.50 for all 8 cases. The table's
`costUsd` column and the "Estimated cost" line report each run. Check the
first real run against the Anthropic console, since the figure is an estimate.

It runs on `skills-runner` (build tier), not the isolated eval runner: it has
to reach the in-cluster Infisical, which the egress lock blocks, and
`claude plugin eval` confines the agent's shell with bwrap, which needs user
namespaces the isolated tier doesn't allow.

### Where it runs, and why it's safe to

This job runs an agent with a shell on PR code, in a public repo, on our own
runner. The containment, and what pins each part:

| Layer | What | Pinned by |
|---|---|---|
| Who | PRs from this repo's branches only. A fork PR doesn't run: its `scaffold.sh` is arbitrary shell. To evaluate one, read it, push its branch here, and the PR from that branch runs | `tests/test_skill_evals_workflow.py` |
| Token | `contents: read`, and checkout doesn't persist the token into `.git/config` | same |
| Secrets | none; no Anthropic credential; the model is a local alias | same |
| Runner | `skills-evals-runner` in the `arc-isolated` tier: no RBAC, no SA token, non-root, all capabilities dropped. It is **not** `skills-runner`, the privileged build-tier runner the repo's other CI uses | https://github.com/dvystrcil/argocd-projects/pull/355 |
| Network | DNS, public internet, the Ollama pod on 11434. No other pod or Service, no apiserver, no LAN | https://github.com/dvystrcil/arc-runners/pull/28, with a kind test |
| Sandbox | bwrap is off (`SKILL_EVALS_OPENCODE_SANDBOX=0`): the pod is the sandbox, and it holds nothing for bwrap to hide | the workflow |

## Keep rule (decided 2026-11-14)

Decision: https://github.com/dvystrcil/skills/issues/72#issuecomment-6881730933

- **A case is kept if its skill fires and beats the no-skill arm on at least
  one model.** Results are reported per model, never as one pooled number.
- **A local model is the primary column**, at 10 runs per arm. Three runs per
  arm was noise for qwen (+0.31 one run, −0.13 the next, on the same cases).
  Ten runs cost hours of GPU time, not money.
- **Claude is tested on demand only**, from a local run or a
  `workflow_dispatch`, never on every PR. It is a candidate **fallback** for
  the tasks local fails. If local fails a case with the skill and Claude passes
  it, the case is a fallback candidate. If both fail, the skill or the case
  needs work.
- Parts 2 and 3 of skills#72 kept or dropped cases on Opus alone. Nobody
  decided that; it drifted in. The Opus ×3 numbers below are still valid as
  the Claude column. They just aren't the gate any more.

## Cases (AC2) and the with/without proof (AC4)

The pilot column is sonnet at 1 run per arm. The Claude column
(`claude-opus-5-5`, 3 runs per arm) was run on demand. Per-model results are in
"Per-model results" below and `evals/baselines/`.

| Case | Source (memory / incident) | Deterministic graders | Pilot (sonnet ×1) with → without; Claude column |
|---|---|---|---|
| `homelab-secrets/literal-password-in-manifest` | `feedback_secret_manifest_in_repo_is_not_hardening`, libreoffice#1→#2 | password never in a Write/Edit input; no literal in `deployment.yaml`; an `InfisicalSecret` written | 1.00 → 0.33 |
| `homelab-image-updater/filebrowser-stable-channel` | skill's silent-drop + pre-release gotchas; homepage#33→#34, homelab#1421 | `allowTags` under `commonUpdateSettings`; constraint `1.x-0`; no `spec.namespace` | 1.00 → 0.60 |
| `git-workflow/fetch-before-editing` | git-workflow rule 0 (2026-08-09: 7 of 8 "fix" PRs were no-ops); `feedback_check_repo_staleness_before_batch_fix` | ran `git fetch`/`pull`; made no commit (the fix was already on `origin/main`) | 0.50 → 0.00 (sonnet; with-skill runs vary, see baseline) |
| `batch-lane/vt350-refresh-goes-to-lane` | ways-of-working D-038; the skill's "submit, end the turn" | a non-dry-run `gpu-batch-submit.py chain vt350-refresh`; never ran FreeCAD or the local `refresh.sh`; no `sleep`/`kubectl get jobs`; at most one `status` | 1.00 → 0.75; **Claude (Opus ×3): 1.00 → 0.75** |
| `file-issue/follow-up-goes-to-draft-issue` | `project_issue_intake`; the skill's "never bare `gh issue create`" | `draft-issue.py` run (not `--help`/`--dry-run`); no `gh issue create` / `gh api …/issues` | 1.00 → 0.00; **Claude (Opus ×3): 1.00 → 0.50** |
| `change-validation/worker-bump-before-after` | the skill's "post-only checking" anti-pattern; `upgrade-validate` | checks written to a file before the restart (`tool_order`); a `diff` (not `git diff`) | 1.00 → 0.33; **Claude (Opus ×3): 1.00 → 0.33** |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | the skill's own recorded miss (a Go service called "JVM-based, set `-Xmx`"); `feedback_verify_source_claims` | no JVM setting (`-Xmx`, `JAVA_OPTS`, `JAVA_TOOL_OPTIONS`, …) on a non-comment line of `values.yaml`; read the image source in `~/Code/inventory-core` | 1.00 → 0.00, fired 1/1; **Claude (Opus ×3): 1.00 → 0.00, fired 3/3** |
| `three-anchor-truthiness/two-versus-one-drift` | the skill's "a hotfix someone forgot to commit looks identical from two anchors"; `feedback_read_the_authoritative_source_not_the_artifact` | consulted the deploy repo (`~/Code/owui-deploy`); doc still says `1b-small`; no Edit to the doc | 1.00 → 0.00, fired 1/1; **Claude (Opus ×3): 1.00 → 0.00, fired 3/3** |

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

These were dropped under the old, Opus/sonnet-only gate. Under the 2026-11-14
keep rule, a case can come back if a local model shows a skill effect on it.
None has been re-run on qwen yet. `yaml-edit-no-roundtrip` is the likeliest,
since the 2026-07 round-trips were local models.

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
| **Same, Opus ×3 (Claude column, on demand)** | **1.00 → 0.00, fired 3/3** | **1.00 → 0.00, fired 3/3** |

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

## Per-model results (AC6): 2026-11-14

Primary column: `qwen3.6:35b` (alias `qwen3635b`), all 8 cases, **10 runs
per arm** (`--tag default --runs 10 --keep`). The 160 runs took 3.45 h.
Files: `evals/baselines/2026-11-14/qwen3635b.{md,json}`. The Claude column is
`claude-opus-5-5` at 3 runs per arm, from the on-demand runs on 2026-11-13
(three cases are in `evals/baselines/2026-11-13/`, the other five in the case
table above). `qwen3-coder-next` is left out until
https://github.com/dvystrcil/skills/issues/121 is fixed, because it loops to
`max_turns` under this harness.

Mean score with the skill → without it, and how many with-skill runs loaded
the skill:

| Case | qwen3.6:35b ×10: with → without (Δ), fired | qwen with, split by fired / not fired | Opus ×3: with → without (Δ) | Kept? (fires and beats no-skill on ≥1 model) |
|---|---|---|---|---|
| `file-issue/follow-up-goes-to-draft-issue` | 0.85 → 0.15 (**+0.70**), 9/10 | 0.94 / 0.00 | 1.00 → 0.50 (+0.50) | **Yes, both models** |
| `homelab-image-updater/filebrowser-stable-channel` | 0.78 → 0.60 (+0.18), 7/10 | 0.86 / 0.60 | 1.00 → 0.60 (+0.40) | **Yes, both models** |
| `homelab-secrets/literal-password-in-manifest` | 0.43 → 0.20 (+0.23), 2/10 | 0.83 / 0.33 | 1.00 → 0.33 (+0.67) | **Yes, both models**; qwen seldom fires |
| `batch-lane/vt350-refresh-goes-to-lane` | 0.70 → 0.55 (+0.15), 3/10; timed out 5/10 → 4/10 | 0.92 / 0.61 | 1.00 → 0.75 (+0.25) | **Yes, both models**; qwen seldom fires |
| `git-workflow/fetch-before-editing` | 0.25 → 0.05 (+0.20), 1/10 | 1.00 / 0.17 | 1.00 → 1.00 (0) | **Yes, on qwen only**, and weakly: it fired once (that run scored 1.00) |
| `change-validation/worker-bump-before-after` | 0.47 → 0.47 (0), **0/10** | — / 0.47 | 1.00 → 0.33 (+0.67) | **Yes, on Opus only** |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 0.05 → 0.00 (+0.05), **0/10** | — / 0.05 | 1.00 → 0.00 (+1.00), fired 3/3 | **Yes, on Opus only** |
| `three-anchor-truthiness/two-versus-one-drift` | 0.13 → 0.33 (**−0.20**), 4/10; timed out 3/10 → 0/10 | 0.17 / 0.11 | 1.00 → 0.00 (+1.00), fired 3/3 | **Yes, on Opus only** |

All 8 cases are kept under the new rule. None was dropped.

**What qwen's column says:**

- **Its main failure is not loading the skill.** In 5 cases the runs that did
  load it scored 0.83–1.00, against 0.00–0.61 for the runs that didn't.
  change-validation and jvm-heap never loaded it in 10 runs. For a local
  model, the skill's `description` (what makes it fire) matters more than
  the body.
- **two-versus-one is the one case where loading the skill didn't help.**
  In a run that loaded it, qwen understood it had two anchors and needed a
  third, and left the doc alone. It then searched only the cwd and its git
  history, never `~/Code` where the deploy repo is, and spawned subagents in a
  chain until the 240 s timeout. `consulted-deploy-repo` failed in all 20
  runs.
- **Timeouts are graded, not errors.** A run that hits the case's
  `timeout_seconds` is scored on what it did before the cutoff, the same as a
  run that hits `max_turns`. The runner now counts both in the note column.
  Before this, 13 timed-out runs blanked 3 of the 8 cases to ERROR.
- **Mean over 8 cases: with 0.46, without 0.29, Δ +0.16.** At 10 runs per arm
  this replaces the 3-run qwen numbers below, which were noise.
- costUsd for the 160 runs: **$23.14 estimated at API prices**. That is
  Anthropic's price list applied to tokens that Ollama served. Nothing was
  billed.

### Fallback candidates (local fails with the skill)

This is input for https://github.com/dvystrcil/homelab/issues/2250. It lists
the cases where qwen3.6:35b scores below 0.5 *with* the skill, or misses the
case's core grader in most with-skill runs, while Opus scores 1.00:

| Case | qwen with | Why local fails | Opus with |
|---|---|---|---|
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 0.05 | never fired; wrote a JVM flag in 9/10 runs | 1.00 |
| `three-anchor-truthiness/two-versus-one-drift` | 0.13 | fired 4/10 but never reached the deploy repo; 3 timeouts | 1.00 |
| `git-workflow/fetch-before-editing` | 0.25 | fired 1/10; skipped `git fetch` in 9/10 | 1.00 (Opus also passes without the skill) |
| `homelab-secrets/literal-password-in-manifest` | 0.43 | fired 2/10; wrote the password in 7/10, no `InfisicalSecret` in 8/10 | 1.00 |
| `change-validation/worker-bump-before-after` | 0.47 | never fired; never diffed before/after (10/10) | 1.00 |
| `batch-lane/vt350-refresh-goes-to-lane` (borderline) | 0.70 | mean ≥ 0.5, but did not submit to the lane in 8/10 runs (the core grader); 5 timeouts | 1.00 |

No case fails on both models. Every failure above is a local one that Claude
passes. The cheaper fix to try first, before
escalating to Claude, is the description (firing). jvm-heap and
change-validation never fired, and in the cases that fired the skill mostly
worked. The exception is two-versus-one, where the skill would need to say
where to look (`~/Code`) for a local model to find the third anchor.

## Earlier baseline: 2026-11-13, `--tag default --runs 3`

Files: `evals/baselines/2026-11-13/<model>.{md,json}` (second run of the day,
the first to include the Bash case; the first run is in git history). Mean
score with the skill → without it:

| Model | image-updater | literal-password | fetch-before-editing | Mean Δ |
|---|---|---|---|---|
| `claude-opus-5-5` | 1.00 → 0.60 | 1.00 → 0.33 | 1.00 → 1.00 | **+0.36** (18 runs, est. $2.39 at API prices; not billed) |
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

## Baseline: 2026-11-14, `--harness opencode`, all 8 cases, `--runs 10`

`qwen3-coder-next`, 160 runs in 99 min (about 37 s per run). Files:
`evals/baselines/2026-11-14/x10/qwen3-coder-next.opencode.{md,json}`. 0 errored;
one run hit `max_turns` (file-issue, with arm). SE is the standard error of Δ.

| Case | with → without (Δ) | SE | fired | 3-run Δ (above) |
|---|---|---|---|---|
| `file-issue/follow-up-goes-to-draft-issue` | 1.00 → 0.00 (**+1.00**) | 0.00 | 10/10 | +1.00 |
| `batch-lane/vt350-refresh-goes-to-lane` | 0.95 → 0.65 (**+0.30**) | 0.06 | 6/10 | +0.25 |
| `homelab-secrets/literal-password-in-manifest` | 0.27 → 0.17 (+0.10) | 0.08 | 0/10 | +0.22 |
| `git-workflow/fetch-before-editing` | 0.05 → 0.00 (+0.05) | 0.05 | 1/10 | 0.00 |
| `homelab-image-updater/filebrowser-stable-channel` | 0.46 → 0.42 (+0.04) | 0.13 | 1/10 | +0.53 |
| `change-validation/worker-bump-before-after` | 0.33 → 0.33 (0) | 0.00 | 0/10 | 0.00 |
| `three-anchor-truthiness/two-versus-one-drift` | 0.07 → 0.07 (0) | 0.09 | 1/10 | 0.00 |
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 0.20 → 0.25 (−0.05) | 0.11 | 0/10 | +0.17 |

Mean with 0.42, without 0.24, Δ +0.18 (3 runs: +0.27). The 3-run numbers
were noise where the skill rarely fired: image-updater's +0.53 is +0.04 at 10
runs. Where qwen loads the skill (file-issue, batch-lane), the effect holds.

## Not done yet

- **`qwen3.6:35b` on the opencode harness at 10 runs per arm.** qwen3-coder-next
  has one (above); qwen3.6 has one only under `claude plugin eval`.
- **Skills qwen doesn't load under opencode** (10 runs per arm): change-validation
  and homelab-secrets 0/10, both three-anchor cases 0/10 and 1/10,
  git-workflow and image-updater 1/10. That is a description/triggering
  question per skill, and the way to shrink `evals/known-failing.txt`.
- **Runs per arm vs. noise.** At 10 runs, Δ's standard error is 0.05–0.13 per
  case. The 2·SE gate resolves the large effects (file-issue, batch-lane) at
  10 runs. A small one, like a Δ of 0.1 on image-updater, would need about 70
  runs per arm, more than a PR can wait for.
- **Cases that withhold Bash** measure in part how the model copes without a
  shell (qwen invents shell tools), not only the skill.
- **More cases toward 10–20 (AC2)**: 8 kept so far. Candidates by the pattern
  above (knowledge-carrying skills): `n8n-import-workflow`,
  `owui-import-pipeline`, `upgrade-validate`, `pgo-pre-upgrade-backup`. Each
  wraps a script that drives the prod cluster, so each needs its script stubbed
  in the eval home first. Their SKILL.md names absolute host paths, which the
  eval can read (see above), so a stub alone isn't enough.
- **A should-not-fire case for `three-anchor-truthiness`**, now that its
  description is wider (see above).
