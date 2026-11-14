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
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

OLLAMA = "https://ollama.sirddail.net"

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
            "fired_grader": next(
                (g["name"] for g in spec.get("graders") or []
                 if g.get("type") == "tool_used" and g.get("tool") == "Skill"),
                None),
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


def run_case(c: dict, model_alias: str, runs: int | None, workdir: Path,
             keep: bool = False) -> dict:
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
           "turn_capped": {"with": 0, "without": 0}, "errors": [], "cost_usd": None,
           "fired": None, "failed_graders": {"with": {}, "without": {}}}
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
                        row["fired"] = (row["fired"] or []) + [bool(g.get("passed"))]
                err = r.get("error") or ""
                if "Reached maximum number of turns" in err:
                    # The model looped to the cap. The eval still graded the
                    # run, so it is a score, not a harness failure.
                    row["turn_capped"][arm] += 1
                elif err:
                    row["errors"].append(f"{arm}: {err[:200]}")
    return row


def run_case_opencode(c: dict, model_alias: str, runs: int | None, workdir: Path,
                      keep: bool = False) -> dict:
    """Same row shape as run_case, from the opencode harness."""
    import opencode_eval  # bin/ is sys.path[0] when this runs as a script

    model, base_url = MODELS.get(model_alias, (model_alias, OLLAMA))
    n = runs or int(c["spec"].get("runs") or 3)
    row = {"skill": c["skill"], "case": c["case"], "with": [], "without": [],
           "turn_capped": {"with": 0, "without": 0}, "errors": [], "cost_usd": None,
           "fired": None, "failed_graders": {"with": {}, "without": {}}}
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
                    row["fired"] = (row["fired"] or []) + [bool(g["passed"])]
            if r["capped"]:
                row["turn_capped"][arm] += 1
            elif r["error"]:
                # A timeout still left a workspace to grade, so it is scored;
                # it is also an error the table must show.
                row["errors"].append(f"{arm}: {r['error']}"[:200])
    return row


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def table(model: str, rows: list[dict]) -> str:
    lines = [f"### {model}", "",
             "| skill | case | with | without | Δ | fired | note |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["errors"]:
            err = r["errors"][0].replace("|", "/").replace("\n", " ")
            lines.append(f"| {r['skill']} | {r['case']} | — | — | — | — | ERROR: {err} |")
            continue
        w, wo = mean(r["with"]), mean(r["without"])
        d = w - wo
        note = "no skill effect: tests the base model (AC4)" if abs(d) < 0.01 else ""
        if d < -0.01:
            note = "skill makes it WORSE"
        tc = r.get("turn_capped") or {}
        if tc.get("with") or tc.get("without"):
            capped = (f"hit max_turns: with {tc.get('with', 0)}/{len(r['with'])}, "
                      f"without {tc.get('without', 0)}/{len(r['without'])}")
            note = f"{note}; {capped}" if note else capped
        fired = r.get("fired")
        fired_s = f"{sum(fired)}/{len(fired)}" if fired is not None else "—"
        if fired is not None and not any(fired):
            # The with arm was the base model too: the delta says nothing.
            never = "skill never fired"
            note = f"{never}; {note}" if note else never
        lines.append(f"| {r['skill']} | {r['case']} | {w:.2f} | {wo:.2f} | {d:+.2f} | {fired_s} | {note} |")
    scored = [r for r in rows if not r["errors"]]
    if scored:
        w = mean([mean(r["with"]) for r in scored])
        wo = mean([mean(r["without"]) for r in scored])
        lines += ["", f"Mean over {len(scored)} scored case(s): with {w:.2f}, "
                      f"without {wo:.2f}, Δ {w - wo:+.2f}. "
                      f"Errored: {len(rows) - len(scored)}."]
    return "\n".join(lines) + "\n"


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
    ap.add_argument("--keep", action="store_true",
                    help="keep raw eval JSON under <out>/raw/<model>/ and the "
                         "run sandboxes (traces) under the eval root")
    a = ap.parse_args(argv)

    cases = list(discover(a.repo, a.skill, a.case, a.tag))
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
        if a.keep:
            work = out / "raw" / slug
            work.mkdir(parents=True, exist_ok=True)
            rows = [runner(c, model, a.runs, work, keep=True) for c in cases]
        else:
            with tempfile.TemporaryDirectory(prefix="skill-evals-run-") as work:
                rows = [runner(c, model, a.runs, Path(work)) for c in cases]
        title = f"{model} (opencode)" if a.harness == "opencode" else model
        md = table(title, rows)
        (out / f"{slug}.md").write_text(md)
        (out / f"{slug}.json").write_text(json.dumps(
            {"model": model, "harness": a.harness, "cases": rows}, indent=1) + "\n")
        print(md)
        failed |= any(r["errors"] for r in rows)
    print(f"results: {out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
