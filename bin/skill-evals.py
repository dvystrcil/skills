#!/usr/bin/env python3
"""Run the skill behaviour evals (claude/*/evals/*/case.yaml) per model.

Each case runs through `claude plugin eval`, which runs it once WITH the skill
loaded and once WITHOUT (its ablation arm) and grades both. This wrapper adds
what a model change needs: one command, every case, a with/without/delta table
per model, and a compact JSON you can commit and diff (skills#72).

    bin/skill-evals.py                                  # default tag, sonnet
    bin/skill-evals.py --model claude-opus-5-5 --model qwen3-coder-next --model qwen3635b
    bin/skill-evals.py --skill homelab-secrets --runs 1
    bin/skill-evals.py --harness opencode --model qwen3-coder-next   # skills#121

`--harness opencode` runs the same cases through `opencode run` instead (see
bin/opencode_eval.py): the harness the local models are deployed in. Under
`claude plugin eval`, qwen3-coder-next loops to max_turns and scores 0.00 for
reasons that have nothing to do with the skills (skills#121).

Run it OUTSIDE another sandbox. A case that uses Bash makes `claude plugin
eval` confine the shell with bubblewrap; inside Claude Code's own Bash sandbox,
or on Ubuntu with kernel.apparmor_restrict_unprivileged_userns=1 and no bwrap
AppArmor profile, the nested user namespace is refused and every Bash call in
the eval fails (see evals/README.md).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

# CI overrides this with the in-cluster Service (skills#120).
OLLAMA = os.environ.get("SKILL_EVALS_OLLAMA_URL") or "https://ollama.sirddail.net"

# alias -> (model id passed to --model, base URL or None for Anthropic)
MODELS = {
    "qwen3-coder-next": ("qwen3-coder-next:latest", OLLAMA),
    "qwen3635b": ("qwen3.6:35b", OLLAMA),
}

# Gated tools `claude plugin eval` needs an operator grant for. Bash is only
# granted to cases that list it: on a host that can't confine a shell, a Bash
# grant refuses the whole run before it starts.
BASE_GRANT = ["Write", "Edit"]


def discover(repo: Path, skill: str | None, case: str | None, tag: str | None):
    for path in sorted(repo.glob("claude/*/evals/*/case.yaml")):
        spec = yaml.safe_load(path.read_text())
        name = spec["name"]
        skill_name = path.parents[2].name
        if skill and skill_name != skill:
            continue
        if case and name != case:
            continue
        if tag and tag not in (spec.get("tags") or []):
            continue
        execution = spec.get("execution") or {}
        skill_grader = next(
            (g for g in spec.get("graders") or []
             if g.get("type") == "tool_used" and g.get("tool") == "Skill"), None)
        if skill_grader and skill_grader.get("max") == 0 and skill_grader.get("min", 1) != 0:
            # tool_used defaults min to 1: `max: 0` alone never passes, and
            # every run would read as a fire (skills#140's first live run).
            raise ValueError(f"{path}: Skill grader {skill_grader['name']!r} has max: 0 "
                             "but no min: 0, so it can never pass")
        yield {
            "skill": skill_name,
            "skill_dir": path.parents[2],
            "case_dir": path.parent,
            "spec": spec,
            "case": name,
            "bash": "Bash" in (execution.get("allowed_tools") or []),
            "scaffold": bool((spec.get("context") or {}).get("scaffold_script")),
            # Under ablation a `tool_used: Skill` grader is display-only, so
            # the score can't show whether the skill loaded. Read it here.
            "fired_grader": skill_grader["name"] if skill_grader else None,
            # A `max: 0` Skill grader passes when the skill did NOT run
            # (skills#141 reported that as "fired 10/10").
            "fired_inverted": bool(skill_grader) and skill_grader.get("max") == 0,
            # Judged on the fire rate alone, not Δ (skills#140).
            "should_not_fire": spec.get("should_not_fire") is True,
        }


def eval_root() -> Path:
    """Where `claude plugin eval` may create its per-run sandbox roots.

    It uses os.tmpdir(). Under /tmp its bubblewrap sandbox mounts the case cwd,
    $HOME (incl. the repo the agent commits to) and its own TMPDIR read-only,
    so every Bash write fails and both arms score alike. Measured 2026-11-13:
    a write probe got RO on all five paths under /tmp, OK on all five under
    ~/.cache. Override with SKILL_EVALS_TMPDIR.
    """
    override = os.environ.get("SKILL_EVALS_TMPDIR")
    if override:
        root = Path(override)
    else:
        cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        root = Path(cache) / "skill-evals" / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fired(c: dict, passed) -> bool:
    """Did the skill run, from its Skill grader's pass/fail."""
    return bool(passed) != c.get("fired_inverted", False)


def run_case(c: dict, model_alias: str, runs: int | None, workdir: Path,
             keep: bool = False, max_cost: float | None = None) -> dict:
    model, base_url = MODELS.get(model_alias, (model_alias, None))
    out_json = workdir / f"{c['skill']}--{c['case']}.json"
    cmd = ["claude", "plugin", "eval", str(c["skill_dir"]),
           "--case", c["case"], "--model", model,
           "--json", str(out_json), "--output-dir", str(workdir / c["case"]),
           "--no-publish", "--trust-plugin"]
    if c["scaffold"]:
        cmd.append("--scaffold")
    if runs:
        cmd += ["--runs", str(runs)]
    if keep:
        cmd.append("--keep-temp")
    if max_cost is not None:
        cmd += ["--max-cost-usd", f"{max_cost:.2f}"]
    cmd += ["--allow-tools", *BASE_GRANT, *(["Bash"] if c["bash"] else [])]

    env = dict(os.environ)
    env["TMPDIR"] = str(eval_root())
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = env.get("OLLAMA_API_KEY", "ollama")
        env.pop("ANTHROPIC_API_KEY", None)
    else:
        env.pop("ANTHROPIC_BASE_URL", None)

    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    row = {"skill": c["skill"], "case": c["case"], "with": [], "without": [],
           "turn_capped": {"with": 0, "without": 0},
           "timed_out": {"with": 0, "without": 0}, "errors": [], "cost_usd": None,
           "fired": None, "failed_graders": {"with": {}, "without": {}},
           "should_not_fire": c.get("should_not_fire", False)}
    if not out_json.exists():
        tail = (p.stderr or p.stdout).strip().splitlines()[-1:] or [f"exit {p.returncode}"]
        row["errors"].append(f"no result JSON: {tail[0][:200]}")
        return row
    data = json.loads(out_json.read_text())
    row["cost_usd"] = data.get("costUsd")
    for case in data.get("cases", []):
        for arm in ("with", "without"):
            for r in case.get("arms", {}).get(arm, []):
                row[arm].append(r["score"])
                for g in r.get("graders") or []:
                    if g.get("scored", True) and not g.get("passed"):
                        fg = row["failed_graders"][arm]
                        fg[g["name"]] = fg.get(g["name"], 0) + 1
                    if arm == "with" and g.get("name") == c.get("fired_grader"):
                        row["fired"] = (row["fired"] or []) + [fired(c, g.get("passed"))]
                err = r.get("error") or ""
                if "Reached maximum number of turns" in err:
                    # The model looped to the cap. The eval still graded the
                    # run, so it is a score, not a harness failure.
                    row["turn_capped"][arm] += 1
                elif err.startswith("timed out after"):
                    # The case's wall-clock cap: also graded, also behaviour
                    # (a slow local model), not a harness failure.
                    row["timed_out"][arm] += 1
                elif err:
                    row["errors"].append(f"{arm}: {err[:200]}")
    return row


def run_case_opencode(c: dict, model_alias: str, runs: int | None, workdir: Path,
                      keep: bool = False, max_cost: float | None = None) -> dict:
    """Same row shape as run_case, from the opencode harness. A local run
    costs nothing, so a cost ceiling has nothing to limit."""
    import opencode_eval  # bin/ is sys.path[0] when this runs as a script

    model, base_url = MODELS.get(model_alias, (model_alias, OLLAMA))
    n = runs or int(c["spec"].get("runs") or 3)
    row = {"skill": c["skill"], "case": c["case"], "with": [], "without": [],
           "turn_capped": {"with": 0, "without": 0}, "timed_out": {"with": 0, "without": 0},
           "errors": [], "cost_usd": None,
           "fired": None, "failed_graders": {"with": {}, "without": {}},
           "should_not_fire": c.get("should_not_fire", False)}
    for arm in ("with", "without"):
        for i in range(n):
            keep_dir = workdir / c["case"] / f"{arm}-{i + 1}" if keep else None
            try:
                r = opencode_eval.run_once(c["skill_dir"], c["case_dir"], c["spec"], arm,
                                           model, base_url, eval_root(), keep_dir)
            except (RuntimeError, ValueError, OSError) as exc:
                row["errors"].append(f"{arm}: {exc}"[:200])
                continue
            row[arm].append(r["score"])
            for g in r["graders"]:
                if g["scored"] and not g["passed"]:
                    fg = row["failed_graders"][arm]
                    fg[g["name"]] = fg.get(g["name"], 0) + 1
                if arm == "with" and g["name"] == c.get("fired_grader"):
                    row["fired"] = (row["fired"] or []) + [fired(c, g["passed"])]
            if r["capped"]:
                row["turn_capped"][arm] += 1
            elif r["error"] and r["error"].startswith("timed out after"):
                # A timeout still left a workspace to grade, so it is scored and
                # counted, like a max_turns run (skills#123); one slow run must
                # not blank the case (skills#120's first live CI run did).
                row["timed_out"][arm] += 1
            elif r["error"]:
                row["errors"].append(f"{arm}: {r['error']}"[:200])
    return row


KNOWN_FAILING = Path("evals") / "known-failing.txt"

# A local model's result per case becomes one `local-fallback/v1` event, so
# eval-time failures show on homelab's "Local model fallbacks" dashboard next
# to draft-issue (skills#126). One event per case per local model, pass or
# fail: the dashboard's fallback rate is escalated events / all events
# (homelab architecture/local-fallback-telemetry.md). The emitter is imported
# from a dvystrcil/homelab checkout, not copied, so the schema has one home;
# with no checkout (CI, another machine) nothing is recorded and nothing else
# changes. Claude runs never emit: they are the fallback, not the local try.
EVAL_GATE = "skill-evals.gate"
# Reason codes where the local model got the case wrong. eval_error is the
# harness or Ollama (infra), and no_skill_grader is the case's own fault, so
# neither is a fallback to Claude.
MODEL_FAILURES = ("never_fired", "no_effect", "fired_when_should_not")


def is_local(model_alias: str, harness: str) -> bool:
    """Same routing as the runners: opencode is local-only; under claude only
    an alias with an Ollama base URL is local."""
    return harness == "opencode" or (model_alias in MODELS
                                     and MODELS[model_alias][1] is not None)


def load_local_fallback():
    """homelab's bin/lib/local_fallback.py, or None. Never raises."""
    root = Path(os.environ.get("SKILL_EVALS_HOMELAB") or Path.home() / "Code" / "homelab")
    lib = root / "bin" / "lib" / "local_fallback.py"
    if not lib.is_file():
        print(f"local-fallback: no emitter at {lib}; no events recorded",
              file=sys.stderr)
        return None
    try:
        spec = importlib.util.spec_from_file_location("local_fallback", lib)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.new_event, mod.emit  # noqa: B018 - the two calls used here
        return mod
    except Exception as e:  # telemetry must not break the eval
        print(f"local-fallback: could not load {lib}: {e}", file=sys.stderr)
        return None


def fill_event(ev: dict, row: dict, duration_s: float, harness: str) -> dict:
    """Set the outcome fields of a local-fallback/v1 event from one row."""
    verdict, _, code = judge(row)
    ev["gate_outcome"] = verdict
    ev["failure_class"] = ("none" if verdict == "pass"
                           else "infra" if code == "eval_error" else "gate")
    ev["failure_reason"] = code
    # The gate's code first, then the with-arm graders that failed, most
    # often first: what the model actually got wrong with the skill loaded.
    graders = sorted(row["failed_graders"]["with"].items(), key=lambda kv: (-kv[1], kv[0]))
    ev["failure_reasons"] = [] if code == "none" else [code] + [g for g, _ in graders]
    ev["escalated_to"] = "claude-code" if code in MODEL_FAILURES else "none"
    # One gated attempt per case. The runs are samples of it, not retries,
    # so they must not count on the "passes the retry rescued" panel.
    ev["attempts"] = 1
    ev["duration_s"] = round(duration_s, 1)
    ev["skill"] = row["skill"]
    ev["harness"] = harness
    ev["runs"] = {"with": len(row["with"]), "without": len(row["without"])}
    return ev


def with_events(runner, lf, model_alias: str, harness: str):
    """Wrap a runner so each case it runs records one event. Never raises
    from the telemetry side: the row is returned untouched either way."""
    model = MODELS.get(model_alias, (model_alias,))[0]

    def run(c, *args, **kwargs):
        try:
            ev = lf.new_event(f"skill-eval-{c['case']}", model, EVAL_GATE)
        except Exception as e:
            print(f"local-fallback: could not start event: {e}", file=sys.stderr)
            ev = None
        t0 = time.monotonic()
        row = runner(c, *args, **kwargs)
        if ev is not None:
            try:
                lf.emit(fill_event(ev, row, time.monotonic() - t0, harness))
            except Exception as e:
                print(f"local-fallback: could not record event: {e}", file=sys.stderr)
        return row
    return run


def changed_skills(repo: Path, ref: str) -> set[str]:
    """Skills whose SKILL.md or evals/ the branch changed since it left REF.

    Three-dot diff: against the merge base, so commits that landed on REF after
    the branch was cut don't count as this branch's changes.
    """
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", f"{ref}...HEAD"],
                         check=True, capture_output=True, text=True).stdout
    skills = set()
    for path in out.splitlines():
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "claude" and (
                parts[2] == "SKILL.md" or (parts[2] == "evals" and len(parts) > 3)):
            skills.add(parts[1])
    return skills


def load_known_failing(repo: Path, all_cases: list[dict]) -> dict[str, str]:
    """`skill/case  reason` per line; # comments. Every entry must name a real
    case and give a reason, or a typo would quietly waive nothing."""
    f = repo / KNOWN_FAILING
    if not f.exists():
        return {}
    real = {f"{c['skill']}/{c['case']}" for c in all_cases}
    known, problems = {}, []
    for n, line in enumerate(f.read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, reason = line.partition(" ")
        if key not in real:
            problems.append(f"{KNOWN_FAILING}:{n}: {key} is not an eval case")
        elif not reason.strip():
            problems.append(f"{KNOWN_FAILING}:{n}: {key} needs a reason")
        else:
            known[key] = reason.strip()
    if problems:
        raise ValueError("\n".join(problems))
    return known


def judge(r: dict) -> tuple[str, str, str]:
    """One row's verdict under the gate rule: (verdict, why, reason code).

    verdict is pass, fail or error; the reason code is `none` on a pass and a
    stable code otherwise (never_fired, no_effect, fired_when_should_not,
    no_skill_grader, eval_error), for the local-fallback event (skills#126)."""
    name = f"skill {r['skill']} case {r['case']}"
    if r["errors"]:
        return "error", f"{name} errored: {r['errors'][0]}", "eval_error"
    if r.get("should_not_fire"):
        fired_ = r.get("fired")
        if fired_ is None:
            return "fail", (f"{name} should not fire, but has no "
                            "`tool_used: Skill` grader to tell"), "no_skill_grader"
        fired_s = f"{sum(fired_)}/{len(fired_)}"
        if any(fired_):
            return "fail", f"{name} should not fire but fired {fired_s}", "fired_when_should_not"
        return "pass", f"{name} (should not fire: fired {fired_s})", "none"
    d = mean(r["with"]) - mean(r["without"])
    se = delta_se(r["with"], r["without"])
    fired = r.get("fired")
    fired_s = f"{sum(fired)}/{len(fired)}" if fired is not None else "—"
    never = fired is not None and not any(fired)
    stats = f"fired {fired_s}, Δ {d:+.2f}, SE {se:.2f}"
    # Δ must clear twice its standard error: `delta <= 0` passed a
    # gutted skill on one partial run in ten (skills#120 AC2, live).
    if never or d <= 2 * se:
        return ("fail", f"{name} fired {fired_s} or delta <= 2·SE ({stats})",
                "never_fired" if never else "no_effect")
    return "pass", f"{name} ({stats})", "none"


def gate(rows: list[dict], known: dict[str, str]) -> tuple[list[str], bool]:
    """The PR rule (skills#120 AC2): a case fails if its skill never fired in
    the with arm, or Δ (with − without) does not clear twice its standard
    error, computed from the run's own scores. Known-failing cases are
    reported and don't fail; one that now passes says so.

    A `should_not_fire` case (skills#140) fails if the skill fired in any
    with-arm run. It has no with-vs-without effect to measure, so Δ is not
    judged."""
    lines, failed = [], False
    for r in rows:
        key = f"{r['skill']}/{r['case']}"
        verdict, why, _ = judge(r)
        if key in known and verdict != "pass":
            lines.append(f"KNOWN: {why} [{known[key]}]")
        elif key in known:
            lines.append(f"NOW PASSES: {why}: if it keeps passing, remove it from "
                         f"{KNOWN_FAILING} [{known[key]}]")
        elif verdict == "pass":
            lines.append(f"PASS: {why}")
        else:
            lines.append(f"FAIL: {why}")
            failed = True
    return lines, failed


def delta_se(with_scores: list[float], without_scores: list[float]) -> float:
    """Standard error of mean(with) − mean(without), arms independent."""
    def var_of_mean(xs):
        m = mean(xs)
        return sum((x - m) ** 2 for x in xs) / len(xs) / len(xs)
    return (var_of_mean(with_scores) + var_of_mean(without_scores)) ** 0.5


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def cost(row: dict) -> str:
    """Estimated cost at API prices (claude plugin eval's costUsd); — for a
    local run through opencode, which costs nothing (skills#120 AC1)."""
    c = row.get("cost_usd")
    return "—" if c is None else f"{c:.2f}"


def table(model: str, rows: list[dict]) -> str:
    lines = [f"### {model}", "",
             "| skill | case | with | without | Δ | fired | note | costUsd |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["errors"]:
            err = r["errors"][0].replace("|", "/").replace("\n", " ")
            lines.append(f"| {r['skill']} | {r['case']} | — | — | — | — | ERROR: {err} | {cost(r)} |")
            continue
        w, wo = mean(r["with"]), mean(r["without"])
        d = w - wo
        note = "no skill effect: tests the base model (AC4)" if abs(d) < 0.01 else ""
        if d < -0.01:
            note = "skill makes it WORSE"
        if r.get("should_not_fire"):
            note = "should not fire"
        tc = r.get("turn_capped") or {}
        if tc.get("with") or tc.get("without"):
            capped = (f"hit max_turns: with {tc.get('with', 0)}/{len(r['with'])}, "
                      f"without {tc.get('without', 0)}/{len(r['without'])}")
            note = f"{note}; {capped}" if note else capped
        to = r.get("timed_out") or {}
        if to.get("with") or to.get("without"):
            timed = (f"timed out: with {to.get('with', 0)}/{len(r['with'])}, "
                     f"without {to.get('without', 0)}/{len(r['without'])}")
            note = f"{note}; {timed}" if note else timed
        fired = r.get("fired")
        fired_s = f"{sum(fired)}/{len(fired)}" if fired is not None else "—"
        if fired is not None and not any(fired) and not r.get("should_not_fire"):
            # The with arm was the base model too: the delta says nothing.
            never = "skill never fired"
            note = f"{never}; {note}" if note else never
        lines.append(f"| {r['skill']} | {r['case']} | {w:.2f} | {wo:.2f} | {d:+.2f} | {fired_s} | {note} | {cost(r)} |")
    scored = [r for r in rows if not r["errors"]]
    if scored:
        w = mean([mean(r["with"]) for r in scored])
        wo = mean([mean(r["without"]) for r in scored])
        lines += ["", f"Mean over {len(scored)} scored case(s): with {w:.2f}, "
                      f"without {wo:.2f}, Δ {w - wo:+.2f}. "
                      f"Errored: {len(rows) - len(scored)}."]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    if costs:
        lines += ["", f"Estimated cost: ${sum(costs):.2f} at API prices."]
    return "\n".join(lines) + "\n"


def run_all(runner, cases, model, runs, work, keep, ceiling):
    """Run every case; with a ceiling, hand each case what is left of it."""
    rows, left = [], ceiling
    for c in cases:
        if left is None:
            rows.append(runner(c, model, runs, work, keep=keep))
            continue
        if left <= 0:
            rows.append({"skill": c["skill"], "case": c["case"], "with": [], "without": [],
                         "errors": [f"not run: cost ceiling ${ceiling:.2f} spent"],
                         "cost_usd": None, "fired": None})
            continue
        row = runner(c, model, runs, work, keep=keep, max_cost=left)
        left -= row.get("cost_usd") or 0
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", action="append",
                    help="model id or alias (qwen3-coder-next, qwen3635b); repeatable; default sonnet")
    ap.add_argument("--skill")
    ap.add_argument("--case")
    ap.add_argument("--tag", default=None,
                    help="only cases with this tag (e.g. default)")
    ap.add_argument("--runs", type=int, help="override per-case runs (default: case.runs, 3)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--out", type=Path, help="write <model>.md/.json here")
    ap.add_argument("--harness", choices=["claude", "opencode"], default="claude",
                    help="claude: `claude plugin eval` (default). opencode: `opencode run`, "
                         "local models only (skills#121)")
    ap.add_argument("--changed-from", metavar="REF",
                    help="only cases of skills whose SKILL.md or evals/ changed "
                         "since the branch left REF (CI on PRs, skills#120)")
    ap.add_argument("--gate", action="store_true",
                    help=f"exit 1 if a case's skill never fired or with <= without; "
                         f"cases in {KNOWN_FAILING} are reported, not failed")
    ap.add_argument("--max-cost-usd", type=float, metavar="USD",
                    help="ceiling for the whole invocation, at API prices (claude "
                         "harness): each case gets what is left, and no case "
                         "launches once it is spent (skills#120)")
    ap.add_argument("--keep", action="store_true",
                    help="keep raw eval JSON under <out>/raw/<model>/ and the "
                         "run sandboxes (traces) under the eval root")
    a = ap.parse_args(argv)

    try:
        cases = list(discover(a.repo, a.skill, a.case, a.tag))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    known = {}
    if a.gate:
        try:
            known = load_known_failing(a.repo, list(discover(a.repo, None, None, None)))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    if a.changed_from:
        touched = changed_skills(a.repo, a.changed_from)
        cases = [c for c in cases if c["skill"] in touched]
        if not cases:
            print(f"no eval cases for the changed skills ({', '.join(sorted(touched)) or 'none'}); "
                  "nothing to run")
            return 0
    if not cases:
        print("no eval cases matched", file=sys.stderr)
        return 2
    out = a.out or Path(tempfile.mkdtemp(prefix="skill-evals-"))
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    runner = run_case_opencode if a.harness == "opencode" else run_case
    if a.harness == "opencode":
        claude = [m for m in a.model or [] if m.startswith("claude")
                  or m in ("sonnet", "opus", "haiku", "fable")
                  or (m in MODELS and MODELS[m][1] is None)]
        if claude:
            ap.error(f"--harness opencode runs local models only (Ollama), not {', '.join(claude)}")
    for model in a.model or (["qwen3-coder-next"] if a.harness == "opencode" else ["sonnet"]):
        slug = model.replace("/", "_").replace(":", "_")
        if a.harness == "opencode":
            slug += ".opencode"
        run = runner
        if is_local(model, a.harness):
            lf = load_local_fallback()
            if lf is not None:
                run = with_events(runner, lf, model, a.harness)
        if a.keep:
            work = out / "raw" / slug
            work.mkdir(parents=True, exist_ok=True)
            rows = run_all(run, cases, model, a.runs, work, True, a.max_cost_usd)
        else:
            with tempfile.TemporaryDirectory(prefix="skill-evals-run-") as work:
                rows = run_all(run, cases, model, a.runs, Path(work), False,
                               a.max_cost_usd)
        title = f"{model} (opencode)" if a.harness == "opencode" else model
        md = table(title, rows)
        (out / f"{slug}.md").write_text(md)
        (out / f"{slug}.json").write_text(json.dumps(
            {"model": model, "harness": a.harness, "cases": rows}, indent=1) + "\n")
        print(md)
        failed |= any(r["errors"] for r in rows)
        if a.gate:
            lines, gate_failed = gate(rows, known)
            print(f"Gate ({title}):\n" + "\n".join(lines) + "\n")
            failed |= gate_failed
    print(f"results: {out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
