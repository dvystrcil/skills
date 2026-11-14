#!/usr/bin/env python3
"""Tests for .github/workflows/skill-evals.yml, the skill-eval CI job (skills#120).

The job runs agents (a local model with a shell) on PR code, in a PUBLIC repo,
on a self-hosted runner. What keeps that safe is in the workflow file, so the
properties are pinned here rather than trusted to review:

  * it runs on PRs from this repo's own branches only, never a fork's
    (a fork PR would run a stranger's case.yaml scaffold on our runner);
  * the job token is read-only and checkout does not leave it in .git/config,
    where the agent's shell could read it;
  * no secret and no Anthropic credential is read, and the model is a local
    one (AC3/AC4: Claude runs on demand only, from a local run);
  * it runs on the dedicated arc-isolated eval runner, scoped to the touched
    skills, and applies the gate (AC1/AC2).
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WF = REPO / ".github" / "workflows" / "skill-evals.yml"


def load_runner():
    spec = importlib.util.spec_from_file_location("skill_evals", REPO / "bin" / "skill-evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SkillEvalsWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WF.read_text()
        cls.wf = yaml.safe_load(cls.text)
        # PyYAML reads the bare key `on` as boolean True.
        cls.on = cls.wf.get("on", cls.wf.get(True))
        cls.jobs = cls.wf["jobs"]

    def steps(self):
        for job in self.jobs.values():
            yield from job.get("steps", [])

    def test_triggers_on_skill_and_eval_paths_and_on_demand(self):
        self.assertEqual(sorted(self.on["pull_request"]["paths"]),
                         ["claude/*/SKILL.md", "claude/*/evals/**"])
        self.assertIn("workflow_dispatch", self.on)

    def test_never_pull_request_target(self):
        # pull_request_target runs with write token + secrets on fork code.
        self.assertNotIn("pull_request_target", self.on)

    def test_fork_prs_do_not_run(self):
        for name, job in self.jobs.items():
            cond = job.get("if", "")
            self.assertIn("github.event.pull_request.head.repo.full_name == github.repository",
                          cond, name)

    def test_token_is_read_only(self):
        self.assertEqual(self.wf.get("permissions"), {"contents": "read"})
        for name, job in self.jobs.items():
            self.assertNotIn("permissions", job, f"{name} must not widen permissions")

    def test_checkout_does_not_persist_the_token(self):
        checkouts = [s for s in self.steps() if str(s.get("uses", "")).startswith("actions/checkout@")]
        self.assertTrue(checkouts)
        for s in checkouts:
            self.assertIs((s.get("with") or {}).get("persist-credentials"), False)

    def test_no_secrets_and_no_anthropic_credential(self):
        self.assertNotRegex(self.text, r"secrets\.")
        self.assertNotIn("ANTHROPIC", self.text)

    def test_model_is_local(self):
        runner = load_runner()
        for name, job in self.jobs.items():
            model = (job.get("env") or {}).get("MODEL")
            self.assertIn(model, runner.MODELS, f"{name}: MODEL must be a local alias")
            self.assertIsNotNone(runner.MODELS[model][1], name)
        # No step may pass a model other than $MODEL.
        for s in self.steps():
            for m in re.findall(r"--model\s+(\S+)", s.get("run", "")):
                self.assertEqual(m, '"$MODEL"')

    def test_runs_on_the_isolated_eval_runner(self):
        for name, job in self.jobs.items():
            self.assertEqual(job["runs-on"], "skills-evals-runner", name)

    def test_runs_the_opencode_harness_scoped_and_gated(self):
        runs = " ".join(s.get("run", "") for s in self.steps())
        for flag in ("bin/skill-evals.py", "--harness opencode", "--gate", "--keep",
                     "--changed-from"):
            self.assertIn(flag, runs)

    def test_inputs_reach_the_shell_through_env_not_interpolation(self):
        # ${{ inputs.x }} inside run: is script injection.
        for s in self.steps():
            self.assertNotRegex(s.get("run", ""), r"\$\{\{\s*(inputs|github\.event)\.")

    def test_downloads_are_checksum_verified(self):
        runs = "\n".join(s.get("run", "") for s in self.steps())
        downloads = re.findall(r"curl [^\n]*-o ", runs)
        self.assertTrue(downloads)
        self.assertGreaterEqual(runs.count("sha256sum -c"), len(downloads))


if __name__ == "__main__":
    unittest.main()
