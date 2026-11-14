#!/usr/bin/env python3
"""Tests for bin/skill-evals.py, the per-model runner for skill evals (skills#72).

`claude plugin eval` does the real work: it runs each case once with the skill
loaded and once without (the ablation arm), and grades both. The runner's job
is the part around it, and that is what can go wrong quietly:

  * a case that needs Bash must get `--allow-tools Bash`, and a case that does
    not must NOT, because on a host whose sandbox cannot nest user namespaces
    a Bash grant makes every run in that invocation fail before it starts;
  * a local model (qwen via Ollama) must be routed to the Ollama endpoint, and
    a Claude model must not be, or the "qwen" column silently measures Claude;
  * the table has to report the with/without delta, because a case that scores
    the same in both arms is testing the base model, not the skill (AC4);
  * a run that errored is not a pass or a fail of the skill, and must say so.

The `claude` binary is replaced by a stub on PATH that records its argv and
environment and writes a canned result JSON, so this runs the shipped script
end to end without spending anything.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "bin" / "skill-evals.py"

STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import json, os, sys
    args = sys.argv[1:]
    log = os.environ["STUB_LOG"]
    with open(log, "a") as f:
        f.write(json.dumps({
            "argv": args,
            "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
        }) + "\n")
    out = args[args.index("--json") + 1]
    case = args[args.index("--case") + 1]
    canned = json.load(open(os.environ["STUB_RESULTS"]))[case]
    with open(out, "w") as f:
        json.dump(canned, f)
    sys.exit(0 if canned["aggregates"]["casesPassed"] else 1)
    """
).lstrip()


def result(case: str, with_scores, without_scores, error=None, cost=0.1):
    def run(score):
        return {"score": score, "passed": score == 1, "turns": 3,
                "error": error, "graders": []}
    return {
        "costUsd": cost,
        "cases": [{"name": case, "arms": {
            "with": [run(s) for s in with_scores],
            "without": [run(s) for s in without_scores],
        }}],
        "aggregates": {"casesPassed": int(all(s == 1 for s in with_scores))},
    }


def write_case(root: Path, skill: str, case: str, tools: list[str]) -> None:
    d = root / "claude" / skill / "evals" / case
    d.mkdir(parents=True)
    (root / "claude" / skill / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: x\n---\n")
    (d / "case.yaml").write_text(textwrap.dedent(f"""\
        schema_version: "1.0"
        name: {case}
        tags: [default]
        execution:
          allowed_tools: {json.dumps(tools)}
          prompt: hi
        graders:
          - {{name: g, type: file_exists, path: x}}
        """))


class SkillEvalsRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-evals-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bindir = self.tmp / "stubbin"
        bindir.mkdir()
        stub = bindir / "claude"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.log = self.tmp / "calls.jsonl"
        self.results = self.tmp / "results.json"
        self.repo = self.tmp / "repo"
        write_case(self.repo, "git-workflow", "needs-bash", ["Bash", "Read"])
        write_case(self.repo, "homelab-secrets", "no-bash", ["Read", "Write"])
        self.results.write_text(json.dumps({
            "needs-bash": result("needs-bash", [1, 1, 1], [0, 0, 0.5]),
            "no-bash": result("no-bash", [1, 1, 1], [1, 1, 1]),
        }))
        self.env = {**os.environ,
                    "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "STUB_LOG": str(self.log),
                    "STUB_RESULTS": str(self.results)}
        self.env.pop("ANTHROPIC_BASE_URL", None)

    def run_runner(self, *args):
        out = self.tmp / "out"
        p = subprocess.run(
            [sys.executable, str(RUNNER), "--repo", str(self.repo),
             "--out", str(out), *args],
            env=self.env, capture_output=True, text=True)
        calls = [json.loads(l) for l in self.log.read_text().splitlines()] \
            if self.log.exists() else []
        return p, calls, out

    def test_bash_granted_only_to_cases_that_use_it(self):
        p, calls, _ = self.run_runner("--model", "sonnet")
        self.assertEqual(p.returncode, 0, p.stderr)
        by_case = {c["argv"][c["argv"].index("--case") + 1]: c["argv"]
                   for c in calls}
        grant = lambda argv: argv[argv.index("--allow-tools") + 1:]
        self.assertIn("Bash", grant(by_case["needs-bash"]))
        self.assertNotIn("Bash", grant(by_case["no-bash"]))

    def test_qwen_alias_routes_to_ollama_and_claude_does_not(self):
        _, calls, _ = self.run_runner(
            "--model", "sonnet", "--model", "qwen3-coder-next")
        routed = {(c["argv"][c["argv"].index("--model") + 1], c["base_url"])
                  for c in calls}
        self.assertIn(("sonnet", None), routed)
        self.assertIn(("qwen3-coder-next:latest",
                       "https://ollama.sirddail.net"), routed)

    def test_table_reports_delta_and_flags_base_model_cases(self):
        p, _, out = self.run_runner("--model", "sonnet")
        table = (out / "sonnet.md").read_text()
        # needs-bash: with 1.00, without mean 0.17 -> delta +0.83
        self.assertRegex(table, r"needs-bash \| 1\.00 \| 0\.17 \| \+0\.83")
        # no-bash scores the same with and without: not testing the skill.
        self.assertRegex(table, r"no-bash \| 1\.00 \| 1\.00 \| \+0\.00 \| .*no skill effect")
        self.assertIn(table, p.stdout)

    def test_errored_run_is_reported_not_scored(self):
        self.results.write_text(json.dumps({
            "needs-bash": result("needs-bash", [0], [0],
                                 error="exit 1: sandbox required but unavailable"),
            "no-bash": result("no-bash", [1], [0]),
        }))
        _, _, out = self.run_runner("--model", "sonnet")
        table = (out / "sonnet.md").read_text()
        self.assertRegex(table, r"needs-bash \| .*ERROR.*sandbox required")
        self.assertNotRegex(table, r"needs-bash \| 0\.00 \| 0\.00 \| \+0\.00")

    def test_turn_capped_runs_are_scored_and_counted(self):
        # Hitting max_turns is the model's behaviour (looping), not a broken
        # harness: the eval still grades the run. Seen on the first baseline,
        # qwen3-coder-next looped to the cap on every with-skill run of the
        # image-updater case. Hiding that behind ERROR loses the finding.
        capped = result("needs-bash", [0, 0, 0], [0, 0.6, 0],
                        error="exit 1: Reached maximum number of turns (12)")
        capped["cases"][0]["arms"]["without"][1]["error"] = None
        self.results.write_text(json.dumps({
            "needs-bash": capped,
            "no-bash": result("no-bash", [1], [0]),
        }))
        _, _, out = self.run_runner("--model", "sonnet")
        table = (out / "sonnet.md").read_text()
        self.assertRegex(table, r"needs-bash \| 0\.00 \| 0\.20 \| -0\.20 \| .*hit max_turns: with 3/3, without 2/3")
        self.assertNotRegex(table, r"needs-bash \|.*ERROR")

    def test_case_filter_and_compact_json_written(self):
        _, calls, out = self.run_runner("--model", "sonnet", "--case", "no-bash")
        self.assertEqual(len(calls), 1)
        data = json.loads((out / "sonnet.json").read_text())
        self.assertEqual([c["case"] for c in data["cases"]], ["no-bash"])
        self.assertEqual(data["cases"][0]["with"], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
