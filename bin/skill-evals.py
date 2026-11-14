#!/usr/bin/env python3
"""Run the skill behaviour evals (claude/*/evals/*/case.yaml) per model.

Each case runs through `claude plugin eval`, which runs it once WITH the skill
loaded and once WITHOUT (its ablation arm) and grades both. This wrapper adds
what a model change needs: one command, every case, a with/without/delta table
per model, and a compact JSON you can commit and diff (skills#72).

    bin/skill-evals.py                                  # default tag, sonnet
    bin/skill-evals.py --model claude-opus-5-5 --model qwen3-coder-next --model qwen3635b
    bin/skill-evals.py --skill homelab-secrets --runs 1

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
            "case": name,
            "bash": "Bash" in (execution.get("allowed_tools") or []),
            "scaffold": bool((spec.get("context") or {}).get("scaffold_script")),
        }


def run_case(c: dict, model_alias: str, runs: int | None, workdir: Path) -> dict:
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
    cmd += ["--allow-tools", *BASE_GRANT, *(["Bash"] if c["bash"] else [])]

    env = dict(os.environ)
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = env.get("OLLAMA_API_KEY", "ollama")
        env.pop("ANTHROPIC_API_KEY", None)
    else:
        env.pop("ANTHROPIC_BASE_URL", None)

    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    row = {"skill": c["skill"], "case": c["case"], "with": [], "without": [],
           "turn_capped": {"with": 0, "without": 0}, "errors": [], "cost_usd": None}
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
                err = r.get("error") or ""
                if "Reached maximum number of turns" in err:
                    # The model looped to the cap. The eval still graded the
                    # run, so it is a score, not a harness failure.
                    row["turn_capped"][arm] += 1
                elif err:
                    row["errors"].append(f"{arm}: {err[:200]}")
    return row


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def table(model: str, rows: list[dict]) -> str:
    lines = [f"### {model}", "",
             "| skill | case | with | without | Δ | note |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        if r["errors"]:
            err = r["errors"][0].replace("|", "/").replace("\n", " ")
            lines.append(f"| {r['skill']} | {r['case']} | — | — | — | ERROR: {err} |")
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
        lines.append(f"| {r['skill']} | {r['case']} | {w:.2f} | {wo:.2f} | {d:+.2f} | {note} |")
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
    a = ap.parse_args(argv)

    cases = list(discover(a.repo, a.skill, a.case, a.tag))
    if not cases:
        print("no eval cases matched", file=sys.stderr)
        return 2
    out = a.out or Path(tempfile.mkdtemp(prefix="skill-evals-"))
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    for model in a.model or ["sonnet"]:
        slug = model.replace("/", "_").replace(":", "_")
        with tempfile.TemporaryDirectory(prefix="skill-evals-run-") as work:
            rows = [run_case(c, model, a.runs, Path(work)) for c in cases]
        md = table(model, rows)
        (out / f"{slug}.md").write_text(md)
        (out / f"{slug}.json").write_text(json.dumps(
            {"model": model, "cases": rows}, indent=1) + "\n")
        print(md)
        failed |= any(r["errors"] for r in rows)
    print(f"results: {out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
