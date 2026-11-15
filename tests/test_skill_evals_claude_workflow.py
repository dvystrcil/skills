#!/usr/bin/env python3
"""Tests for .github/workflows/skill-evals-claude.yml (skills#120 AC4).

The on-demand Claude eval spends real money (an API key from Infisical, billed
per token; the owner's budget is $30 a month) and runs an agent on a
privileged build-tier runner. What keeps that bounded is in the workflow file,
so the properties are pinned here:

  * it runs only when someone with write access dispatches it: never on a PR,
    a push or a schedule (AC4);
  * one Infisical secret, ANTHROPIC_API_KEY, not the whole prod store;
  * a cost ceiling for the whole run, default $10, and a refusal above $30;
  * 3 runs per arm and one named skill by default;
  * the read-only token isn't persisted, and inputs reach the shell via env.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WF = REPO / ".github" / "workflows" / "skill-evals-claude.yml"


class ClaudeEvalWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WF.read_text()
        cls.wf = yaml.safe_load(cls.text)
        cls.on = cls.wf.get("on", cls.wf.get(True))
        cls.inputs = cls.on["workflow_dispatch"]["inputs"]
        (cls.job,) = cls.wf["jobs"].values()
        cls.steps = cls.job["steps"]
        cls.runs = "\n".join(s.get("run", "") for s in cls.steps)

    def test_dispatch_only(self):
        self.assertEqual(list(self.on), ["workflow_dispatch"])

    def test_runs_on_the_runner_that_can_reach_infisical_and_sandbox(self):
        self.assertEqual(self.job["runs-on"], "skills-runner")

    def test_permissions_are_read_plus_oidc_only(self):
        self.assertEqual(self.wf.get("permissions"), {"contents": "read", "id-token": "write"})
        self.assertNotIn("permissions", self.job)

    def test_only_the_anthropic_key_is_fetched(self):
        fetches = [s for s in self.steps if str(s.get("uses", "")).startswith("Infisical/")]
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0]["with"].get("secret-name"), "ANTHROPIC_API_KEY")
        # Pinned by SHA with its version comment (YAML drops comments: read the line).
        self.assertRegex(self.text, r"uses: Infisical/secrets-action@[0-9a-f]{40} # v")

    def test_defaults_are_cheap(self):
        self.assertEqual(str(self.inputs["runs"]["default"]), "3")
        self.assertEqual(str(self.inputs["max_cost_usd"]["default"]), "10")
        self.assertTrue(self.inputs["skill"]["required"])
        self.assertNotIn("default", self.inputs["skill"])

    def test_model_choices_are_claude(self):
        self.assertEqual(self.inputs["model"]["type"], "choice")
        for m in self.inputs["model"]["options"]:
            self.assertTrue(m.startswith("claude-"), m)

    def test_ceiling_is_passed_and_capped_at_the_monthly_budget(self):
        self.assertIn('--max-cost-usd "$MAX_COST_USD"', self.runs)
        guard = next(s for s in self.steps if "budget" in s.get("name", "").lower())
        self.assertIn("30", guard["run"])
        run_evals = next(i for i, s in enumerate(self.steps)
                         if "bin/skill-evals.py" in s.get("run", ""))
        self.assertLess(self.steps.index(guard), run_evals)

    def test_claude_code_is_pinned(self):
        version = self.job["env"]["CLAUDE_CODE_VERSION"]
        self.assertRegex(str(version), r"^\d+\.\d+\.\d+$")
        self.assertIn("@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}", self.runs)

    def test_checkout_does_not_persist_the_token(self):
        co = next(s for s in self.steps if str(s.get("uses", "")).startswith("actions/checkout@"))
        self.assertIs(co["with"]["persist-credentials"], False)

    def test_inputs_reach_the_shell_through_env_not_interpolation(self):
        for s in self.steps:
            self.assertNotRegex(s.get("run", ""), r"\$\{\{\s*(inputs|github\.event)\.")

    def test_never_a_local_alias(self):
        # The PR workflow is the local one; this one is Claude only.
        code = "\n".join(l for l in self.text.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("qwen", code)


if __name__ == "__main__":
    unittest.main()
