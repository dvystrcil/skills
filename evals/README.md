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

Without the skill, Opus failed in the same way each time:
- **batch-lane:** 2 of 3 runs never found the lane; the third ran FreeCAD in the session first.
- **file-issue:** none of the 3 runs used `draft-issue.py`.
- **change-validation:** all 3 checked only after the restart. A sonnet run even wrote a "Before | After"
  table from one unsaved pre-change `status` call.

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
| `three-anchor-truthiness/jvm-heap-on-a-go-service` | 1.00 → 1.00 | The base model reads the Dockerfile unprompted. **The skill never fired** |
| `three-anchor-truthiness/two-versus-one-drift` | 0.67 → 0.67 | **The skill never fired** in either case |
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
- **More cases toward 10–20 (AC2)**: 6 kept so far. Candidates by the pattern
  above (knowledge-carrying skills): `n8n-import-workflow`,
  `owui-import-pipeline`, `upgrade-validate`, `pgo-pre-upgrade-backup`. Each
  wraps a script that drives the prod cluster, so each needs its script stubbed
  in the eval home first. Their SKILL.md names absolute host paths, which the
  eval can read (see above), so a stub alone isn't enough. Also
  `three-anchor-truthiness`, once its description triggers on tasks (skills#72
  part 3).
