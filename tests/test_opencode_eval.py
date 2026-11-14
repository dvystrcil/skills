#!/usr/bin/env python3
"""Tests for bin/opencode_eval.py: the opencode harness for skill evals (skills#121).

Under `claude plugin eval`, qwen3-coder-next looped to max_turns in most runs
and scored 0.00, while the same model on the same prompt under opencode wrote
the file in 1-2 calls (skills#121). opencode is the harness it is deployed in,
so `bin/skill-evals.py --harness opencode` runs the SAME case.yaml files there.

What can go wrong quietly, and what these tests pin down:

  * the graders are written against Claude Code's trace (tool names `Bash`,
    `Write`; input keys `file_path`, `new_string`; `"name":"Read","input":{`).
    opencode's events use `shell`, `write`, `path`, `newString`. Without
    normalising, every tool_used grader silently scores 0 (or every
    "never did X" grader silently passes);
  * the patterns are JavaScript regexes (variable-width lookbehind, `flags`).
    Python's `re` rejects some of them, so they are evaluated in node;
  * the without arm must not see the skill, and neither arm may see the case's
    own evals/ folder (the graders are in there);
  * the agent must not get tools the case didn't grant (Bash especially);
  * max_turns maps to opencode's agent steps, and hitting it must be reported
    as turn-capped, not as a skill failure or a pass.
"""
from __future__ import annotations

import importlib.util
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
MODULE = REPO / "bin" / "opencode_eval.py"
RUNNER = REPO / "bin" / "skill-evals.py"
# Graders run in node (JavaScript regexes). CI installs it (validate-skills.yml).
NEEDS_NODE = unittest.skipUnless(shutil.which("node"), "node not installed: graders NOT tested")


def load():
    spec = importlib.util.spec_from_file_location("opencode_eval", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ev_tool(tool, inp, output="ok", cid="c1", status="completed"):
    return {"type": "tool_use", "part": {
        "type": "tool", "tool": tool, "id": cid,
        "state": {"status": status, "input": inp, "output": output}}}


def ev_text(text):
    return {"type": "text", "part": {"type": "text", "text": text}}


def ev_step(reason=None):
    if reason is None:
        return {"type": "step_start", "part": {"type": "step-start"}}
    return {"type": "step_finish", "part": {"type": "step-finish", "reason": reason}}


class Normalise(unittest.TestCase):
    """opencode events -> Claude Code-shaped tool calls and trace."""

    def setUp(self):
        self.m = load()

    def test_tool_names_and_input_keys_map_to_claude_code(self):
        run = self.m.normalise([
            ev_step(), ev_tool("shell", {"command": "git fetch", "workdir": "/x"}),
            ev_step("tool-calls"), ev_step(),
            ev_tool("edit", {"path": "/c/a.yaml", "oldString": "a", "newString": "b"}, cid="c2"),
            ev_tool("write", {"path": "/c/b.yaml", "content": "x"}, cid="c3"),
            ev_tool("read", {"path": "/c/b.yaml"}, cid="c4"),
            ev_tool("skill", {"id": "git-workflow"}, cid="c5"),
            ev_step("tool-calls"),
        ])
        self.assertEqual(
            [(c["name"], c["input"]) for c in run["calls"]],
            [("Bash", {"command": "git fetch", "workdir": "/x"}),
             ("Edit", {"file_path": "/c/a.yaml", "old_string": "a", "new_string": "b"}),
             ("Write", {"file_path": "/c/b.yaml", "content": "x"}),
             ("Read", {"file_path": "/c/b.yaml"}),
             ("Skill", {"skill": "git-workflow"})])
        self.assertEqual(run["steps"], 2)

    def test_trace_has_claude_code_shape_and_tool_output(self):
        run = self.m.normalise([
            ev_step(), ev_tool("grep", {"pattern": "TASK_LLM", "path": "/h"},
                               output="/h/owui-deploy/base/configmap.yaml:3: TASK_LLM"),
            ev_step("tool-calls"), ev_step(), ev_text("All done."), ev_step("stop")])
        self.assertIn('"name":"Grep","input":{"pattern":"TASK_LLM","path":"/h"}', run["trace"])
        self.assertIn("owui-deploy/base/configmap.yaml:3:", run["trace"])
        self.assertEqual(run["final"], "All done.")
        self.assertFalse(run["capped"])

    def test_capped_when_steps_reach_max_and_last_step_wanted_more_tools(self):
        events = []
        for i in range(3):
            events += [ev_step(), ev_tool("glob", {"pattern": "**"}, cid=f"c{i}"),
                       ev_step("tool-calls")]
        self.assertTrue(self.m.normalise(events, max_turns=3)["capped"])
        self.assertFalse(self.m.normalise(events, max_turns=4)["capped"])

    def test_failed_tool_calls_still_count(self):
        # A call the harness rejected is still something the agent did: a
        # "never ran X" grader must see it.
        run = self.m.normalise([ev_step(), ev_tool(
            "shell", {"command": "gh issue create -t x"}, status="error", output=None),
            ev_step("tool-calls")])
        self.assertEqual(run["calls"][0]["name"], "Bash")

    def test_unknown_tool_keeps_its_name(self):
        run = self.m.normalise([ev_step(), ev_tool("run_shell", {"cmd": "ls"}),
                                ev_step("tool-calls")])
        self.assertEqual(run["calls"][0]["name"], "run_shell")


@NEEDS_NODE
class Grade(unittest.TestCase):
    """Graders evaluated the way the case.yaml files mean them."""

    def setUp(self):
        self.m = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_of(self, calls, final=""):
        events = [ev_step()]
        for i, (tool, inp) in enumerate(calls):
            events.append(ev_tool(tool, inp, cid=f"c{i}"))
        events += [ev_step("tool-calls"), ev_step(), ev_text(final), ev_step("stop")]
        return self.m.normalise(events)

    def grade(self, graders, run, arm="with"):
        return {g["name"]: g for g in self.m.grade(graders, arm, run, self.cwd)}

    def test_tool_used_matches_json_of_input_with_min_max(self):
        run = self.run_of([("shell", {"command": "git fetch origin"}),
                           ("shell", {"command": "git status"})])
        g = self.grade([
            {"name": "fetched", "type": "tool_used", "tool": "Bash",
             "input_match": "git (?:-[cC] \\S+ )*(?:fetch|pull)\\b"},
            {"name": "no-commit", "type": "tool_used", "tool": "Bash",
             "input_match": "git commit", "min": 0, "max": 0, "arm": "both"},
            {"name": "anchored-on-json", "type": "tool_used", "tool": "Bash",
             "input_match": '"command":"git status'},
            {"name": "at-most-one-bash", "type": "tool_used", "tool": "Bash", "max": 1},
        ], run)
        self.assertTrue(g["fetched"]["passed"])
        self.assertTrue(g["no-commit"]["passed"])
        self.assertTrue(g["anchored-on-json"]["passed"])
        self.assertFalse(g["at-most-one-bash"]["passed"])

    def test_js_only_regex_is_evaluated_in_node(self):
        # Variable-width lookbehind: Python's re raises on this pattern.
        run = self.run_of([("shell", {"command": "git diff --stat a b"}),
                           ("shell", {"command": "diff before.txt after.txt"})])
        g = self.grade([{"name": "outputs-diffed", "type": "tool_used", "tool": "Bash",
                         "input_match": "(?<!git\\s)(?<!git\\s-\\S\\s\\S{1,200}\\s)\\bdiff\\s+(?:-\\S+\\s+)*\\S"}],
                       run)
        self.assertTrue(g["outputs-diffed"]["passed"])
        run2 = self.run_of([("shell", {"command": "git diff --stat a b"})])
        g2 = self.grade([{"name": "outputs-diffed", "type": "tool_used", "tool": "Bash",
                          "input_match": "(?<!git\\s)(?<!git\\s-\\S\\s\\S{1,200}\\s)\\bdiff\\s+(?:-\\S+\\s+)*\\S"}],
                        run2)
        self.assertFalse(g2["outputs-diffed"]["passed"])

    def test_file_graders_read_the_cwd_with_flags(self):
        (self.cwd / "svc").mkdir()
        (self.cwd / "svc" / "config.env").write_text("A=1\nWORKERS=8\n")
        run = self.run_of([])
        g = self.grade([
            {"name": "exists", "type": "file_exists", "path": "svc/config.env"},
            {"name": "missing", "type": "file_exists", "path": "nope.yaml"},
            {"name": "multiline", "type": "regex", "pattern": "^WORKERS=8$", "flags": "m",
             "target": {"source": "file", "path": "svc/config.env"}},
            {"name": "not-contains", "type": "regex", "pattern": "WORKERS=4",
             "match": "not_contains", "target": {"source": "file", "path": "svc/config.env"}},
            {"name": "absent-file-never-passes", "type": "regex", "pattern": "x",
             "match": "not_contains", "target": {"source": "file", "path": "nope.yaml"}},
        ], run)
        self.assertTrue(g["exists"]["passed"])
        self.assertFalse(g["missing"]["passed"])
        self.assertTrue(g["multiline"]["passed"])
        self.assertTrue(g["not-contains"]["passed"])
        self.assertFalse(g["absent-file-never-passes"]["passed"])

    def test_file_grader_refuses_paths_outside_cwd(self):
        run = self.run_of([])
        g = self.grade([{"name": "escape", "type": "file_exists", "path": "../etc"}], run)
        self.assertFalse(g["escape"]["passed"])

    def test_trace_regex_sees_written_content(self):
        run = self.run_of([("write", {"path": "/c/s.yaml",
                                      "content": "kind: InfisicalSecret\n"})])
        g = self.grade([
            {"name": "never-written", "type": "regex", "target": "trace",
             "pattern": '"(content|new_string)":"[^"]*Tr0ub4dor', "match": "not_contains"},
            {"name": "uses-infisicalsecret", "type": "regex", "target": "trace",
             "pattern": "kind: ?InfisicalSecret"},
        ], run)
        self.assertTrue(g["never-written"]["passed"])
        self.assertTrue(g["uses-infisicalsecret"]["passed"])

    def test_tool_order(self):
        grader = {"name": "baseline-first", "type": "tool_order",
                  "before": {"tool": "Bash", "input_match": "status\\s*>"},
                  "after": {"tool": "Bash", "input_match": "restart"}}
        good = self.run_of([("shell", {"command": "svcctl status > pre.txt"}),
                            ("shell", {"command": "svcctl restart"})])
        bad = self.run_of([("shell", {"command": "svcctl restart"}),
                           ("shell", {"command": "svcctl status > post.txt"})])
        self.assertTrue(self.grade([grader], good)["baseline-first"]["passed"])
        self.assertFalse(self.grade([grader], bad)["baseline-first"]["passed"])

    def test_skill_grader_is_display_only_and_with_arm_only(self):
        run = self.run_of([("skill", {"id": "git-workflow"})])
        graders = [{"name": "skill-fired", "type": "tool_used", "tool": "Skill",
                    "input_match": "git-workflow"},
                   {"name": "with-only", "type": "file_exists", "path": "x", "arm": "with"}]
        w = self.grade(graders, run, "with")
        self.assertTrue(w["skill-fired"]["passed"])
        self.assertFalse(w["skill-fired"]["scored"])
        self.assertTrue(w["with-only"]["scored"])
        self.assertEqual(set(self.grade(graders, run, "without")), set())

    def test_score_is_fraction_of_scored_graders(self):
        gs = [{"name": "a", "scored": True, "passed": True},
              {"name": "b", "scored": True, "passed": False},
              {"name": "s", "scored": False, "passed": True}]
        self.assertEqual(self.m.score(gs), 0.5)

    def test_unknown_grader_type_is_an_error_not_a_pass(self):
        with self.assertRaises(ValueError):
            self.grade([{"name": "x", "type": "llm", "prompt": "?"}], self.run_of([]))


class Config(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_only_granted_tools_and_no_network_tools(self):
        c = self.m.opencode_config("qwen3-coder-next:latest", "https://o.example",
                                   ["Read", "Write", "Glob", "Grep", "Skill"], 12, None)
        self.assertIs(c["tools"]["shell"], False)
        for t in ("webfetch", "websearch", "question"):
            self.assertEqual(c["permission"][t], "deny")
        for t in ("execute", "subagent", "experimental_image_generate"):
            self.assertIs(c["tools"][t], False)
        self.assertNotIn("read", c["tools"])
        self.assertEqual(c["agent"]["build"]["steps"], 12)
        self.assertEqual(c["model"], "ollama/qwen3-coder-next:latest")
        self.assertEqual(c["provider"]["ollama"]["options"]["baseURL"], "https://o.example/v1")
        self.assertNotIn("mcp", c)
        self.assertNotIn("skills", c)

    def test_ungranted_shell_is_also_denied_by_permission(self):
        # Seen against real opencode 2.3.0: `permission: {bash: allow}`
        # re-enabled the shell that `tools: {shell: false}` had removed, and a
        # no-Bash case ran Bash. Both switches must say no.
        c = self.m.opencode_config("m", "https://o", ["Read", "Write"], 5, None)
        self.assertNotEqual(c["permission"].get("bash"), "allow")
        self.assertEqual(c["permission"]["shell"], "deny")
        self.assertEqual(c["permission"]["bash"], "deny")

    def test_bash_grant_keeps_shell(self):
        c = self.m.opencode_config("m", "https://o", ["Bash", "Read"], 5, None)
        self.assertNotIn("shell", c["tools"])
        self.assertEqual(c["permission"]["bash"], "allow")
        self.assertNotIn("shell", c["permission"])

    def test_sandbox_hides_skill_dirs_on_every_ancestor(self):
        # Seen against real opencode 2.3.0: it walks up from the cwd, and with
        # the run root under ~/.cache it listed ~/.agents/skills (find-skills,
        # tdd, ...) in BOTH arms. The without arm must see no user skills.
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            for d in ("a/.agents/skills", "a/b/.claude", "a/b/c/.opencode"):
                (t / d).mkdir(parents=True)
            root = t / "a" / "b" / "c" / "run"
            root.mkdir()
            args = self.m._bwrap(root, root / "home" / "cwd")
            hidden = {args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"}
            for d in ("a/.agents", "a/b/.claude", "a/b/c/.opencode"):
                self.assertIn(str(t / d), hidden)

    def test_with_arm_gets_skill_path(self):
        c = self.m.opencode_config("m", "https://o", ["Read"], 5, "/r/skills")
        self.assertEqual(c["skills"], {"paths": ["/r/skills"]})


def tree(home: Path) -> set[str]:
    """Files under home, minus git internals and the bare remote a scaffold makes."""
    out = set()
    for p in home.rglob("*"):
        rel = p.relative_to(home)
        if p.is_dir() or ".git" in rel.parts or "origin.git" in rel.parts:
            continue
        out.add(str(rel))
    return out


class ScaffoldLayouts(unittest.TestCase):
    """Every real scaffold builds the same fixture in both layouts.

    `claude plugin eval` makes $HOME the git root and the cwd a subdir. The
    opencode harness makes the cwd the git root, because with the root one
    level up qwen3-coder-next wrote `./x` relative to the root, outside the cwd,
    and scored 0.00-0.20; with cwd = root it scored 0.87 with the skill and
    0.60 without (skills#121). A scaffold that means "the eval home" must say
    $HOME, not `git rev-parse --show-toplevel`.
    """

    def setUp(self):
        self.m = load()

    def test_every_scaffold_builds_the_same_tree_in_both_layouts(self):
        import yaml
        cases = [p for p in sorted(REPO.glob("claude/*/evals/*/case.yaml"))
                 if (yaml.safe_load(p.read_text()).get("context") or {}).get("scaffold_script")]
        self.assertGreater(len(cases), 3)
        for path in cases:
            spec = yaml.safe_load(path.read_text())
            trees = {}
            for git_at in ("home", "cwd"):
                with self.subTest(case=path.parent.name, git_at=git_at), \
                        tempfile.TemporaryDirectory() as t:
                    home, cwd, _ = self.m._workspace(Path(t), path.parent, spec, git_at=git_at)
                    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                                         capture_output=True, text=True).stdout.strip()
                    self.assertEqual(Path(top), home if git_at == "home" else cwd)
                    trees[git_at] = tree(home)
            with self.subTest(case=path.parent.name):
                self.assertEqual(trees["home"] - {".scaffold-env"},
                                 trees["cwd"] - {".scaffold-env"})

    def test_harness_puts_the_git_root_at_the_cwd(self):
        with tempfile.TemporaryDirectory() as t:
            home, cwd, _ = self.m._workspace(Path(t), Path(t), {})
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                                 capture_output=True, text=True).stdout.strip()
            self.assertEqual(Path(top), cwd)
            self.assertEqual(cwd.parent, home)


STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    # Fake `opencode run`: record what it was given, act like a model that
    # follows the skill when (and only when) it can see one.
    import json, os, sys
    cfg = json.load(open(os.environ["OPENCODE_CONFIG"]))
    cwd = os.getcwd()
    skills = (cfg.get("skills") or {}).get("paths") or []
    seen = sorted(os.listdir(skills[0])) if skills else []
    evals_visible = any(os.path.isdir(os.path.join(skills[0], s, "evals")) for s in seen)
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": cwd, "home": os.environ.get("HOME"),
                            "skills": seen, "evals_visible": evals_visible,
                            "tools": cfg.get("tools"), "steps": cfg["agent"]["build"]["steps"],
                            "scaffolded": os.path.exists(os.path.join(cwd, "fixture.txt"))}) + "\n")
    def emit(e): print(json.dumps(e), flush=True)
    mode = os.environ.get("STUB_MODE", "follow")
    if mode == "loop":
        for i in range(cfg["agent"]["build"]["steps"]):
            emit({"type": "step_start", "part": {"type": "step-start"}})
            emit({"type": "tool_use", "part": {"type": "tool", "tool": "glob", "id": f"g{i}",
                  "state": {"status": "completed", "input": {"pattern": "**"}, "output": ""}}})
            emit({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls"}})
        sys.exit(0)
    emit({"type": "step_start", "part": {"type": "step-start"}})
    if seen:
        emit({"type": "tool_use", "part": {"type": "tool", "tool": "skill", "id": "s1",
              "state": {"status": "completed", "input": {"id": seen[0]}, "output": "..."}}})
    body = "good\n" if seen else "bad\n"
    path = os.path.join(cwd, "out.txt")
    open(path, "w").write(body)
    emit({"type": "tool_use", "part": {"type": "tool", "tool": "write", "id": "w1",
          "state": {"status": "completed", "input": {"path": path, "content": body}, "output": "ok"}}})
    emit({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls"}})
    emit({"type": "step_start", "part": {"type": "step-start"}})
    emit({"type": "text", "part": {"type": "text", "text": "done"}})
    emit({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}})
    """
).lstrip()


@NEEDS_NODE
class EndToEnd(unittest.TestCase):
    """bin/skill-evals.py --harness opencode, with a stub opencode on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.repo, self.bin, self.out = t / "repo", t / "bin", t / "out"
        self.bin.mkdir()
        stub = self.bin / "opencode"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.log = t / "stub.log"
        skill = self.repo / "claude" / "demo"
        case = skill / "evals" / "writes-good"
        case.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: x\n---\nWrite good.\n")
        (skill / "references").mkdir()
        (skill / "references" / "more.md").write_text("more\n")
        (case / "scaffold.sh").write_text(
            "set -euo pipefail\n"
            "git rev-parse --show-toplevel | grep -qx \"$PWD\"\n"
            "test \"$(git branch --show-current)\" = main\n"
            "echo fixture > fixture.txt\n")
        (case / "case.yaml").write_text(textwrap.dedent("""\
            schema_version: "1.0"
            name: writes-good
            tags: [default]
            context:
              scaffold_script: scaffold.sh
            execution:
              max_turns: 7
              timeout_seconds: 60
              allowed_tools: [Read, Write, Skill]
              prompt: write out.txt
            runs: 2
            graders:
              - name: good
                type: regex
                target: {source: file, path: out.txt}
                pattern: '^good$'
                flags: m
              - name: skill-fired
                type: tool_used
                tool: Skill
                input_match: demo
            """))

    def run_runner(self, *extra, mode="follow", extra_env=None):
        env = dict(os.environ)
        env.update({"PATH": f"{self.bin}:{env['PATH']}", "STUB_LOG": str(self.log),
                    "STUB_MODE": mode, "SKILL_EVALS_OPENCODE_SANDBOX": "0",
                    "SKILL_EVALS_PASSENV": "STUB_LOG,STUB_MODE",
                    "SKILL_EVALS_TMPDIR": str(Path(self.tmp.name) / "evalroot")})
        env.update(extra_env or {})
        return subprocess.run(
            [sys.executable, str(RUNNER), "--repo", str(self.repo), "--harness", "opencode",
             "--model", "qwen3-coder-next", "--out", str(self.out), *extra],
            env=env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_with_and_without_arms_scored_from_the_case_graders(self):
        p = self.run_runner()
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((self.out / "qwen3-coder-next.opencode.json").read_text())
        row = data["cases"][0]
        self.assertEqual(data["harness"], "opencode")
        self.assertEqual(row["with"], [1.0, 1.0])
        self.assertEqual(row["without"], [0.0, 0.0])
        self.assertEqual(row["fired"], [True, True])
        self.assertIn("| demo | writes-good | 1.00 | 0.00 | +1.00 | 2/2 |", p.stdout)

    def test_skill_only_in_with_arm_and_never_its_evals(self):
        self.run_runner("--runs", "1")
        c = self.calls()
        self.assertEqual(sorted(x["skills"] for x in c), [[], ["demo"]])
        self.assertFalse(any(x["evals_visible"] for x in c))

    def test_scaffold_ran_in_a_git_home_and_cwd_is_inside_it(self):
        self.run_runner("--runs", "1")
        for x in self.calls():
            self.assertTrue(x["scaffolded"])
            self.assertEqual(Path(x["cwd"]).parent, Path(x["home"]))

    def test_cwd_name_is_configurable(self):
        env = {"SKILL_EVALS_CWD_NAME": "work"}
        self.run_runner("--runs", "1", extra_env=env)
        for x in self.calls():
            self.assertEqual(Path(x["cwd"]).name, "work")
            self.assertTrue(x["scaffolded"])

    def test_case_limits_and_grants_reach_opencode(self):
        self.run_runner("--runs", "1")
        x = self.calls()[0]
        self.assertEqual(x["steps"], 7)
        self.assertIs(x["tools"]["shell"], False)
        self.assertEqual(x["argv"][0], "run")
        self.assertIn("--format", x["argv"])

    def test_turn_cap_is_reported(self):
        p = self.run_runner("--runs", "1", mode="loop")
        row = json.loads((self.out / "qwen3-coder-next.opencode.json").read_text())["cases"][0]
        self.assertEqual(row["turn_capped"], {"with": 1, "without": 1})
        self.assertIn("hit max_turns", p.stdout)

    def test_claude_models_are_refused(self):
        # An unknown alias goes to Ollama, so `--model claude-opus-5-5` would
        # otherwise quietly ask Ollama for a model it doesn't have.
        for model in ("claude-opus-5-5", "sonnet", "opus"):
            env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                       STUB_LOG=str(self.log), SKILL_EVALS_OPENCODE_SANDBOX="0")
            p = subprocess.run(
                [sys.executable, str(RUNNER), "--repo", str(self.repo), "--harness", "opencode",
                 "--model", model, "--out", str(self.out)], env=env, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, model)
            self.assertIn("local models only", p.stderr + p.stdout)
        self.assertFalse(self.log.exists())

    def test_keep_saves_events(self):
        self.run_runner("--runs", "1", "--keep")
        kept = list((self.out / "raw").rglob("events.jsonl"))
        self.assertEqual(len(kept), 2)


if __name__ == "__main__":
    unittest.main()
