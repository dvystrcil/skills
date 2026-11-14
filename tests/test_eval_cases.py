#!/usr/bin/env python3
"""Structural checks over every skill eval case, claude/*/evals/*/case.yaml (skills#72).

A broken case costs a paid run to find: `claude plugin eval` rejects it, or
worse, runs it and grades nothing useful. CI can't run the evals (no Claude
credential, no nested user namespaces on skills-runner), but it can catch the
mistakes that are visible without a model:

  * the case's `name` must match its folder, or `--case <name>` never finds it;
  * a scaffold script must exist, be executable, and parse (`bash -n`);
  * grader names must be unique, types must be ones the eval knows;
  * every grader regex must compile as a JavaScript RegExp, because the eval
    evaluates them in JS (lookbehinds of different widths are valid there and
    not in Python), so this uses node when it is installed;
  * a `tool: Skill` grader must name the skill the case lives in, or a copied
    case reports "skill fired" for the wrong skill.

`test_checker_rejects_broken_cases` feeds the checker known-bad cases, so the
guard has been seen to fail (tdd-artifacts, case 2).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
GRADER_TYPES = {"regex", "tool_order", "tool_used", "file_exists", "llm", "baseline"}
NODE = shutil.which("node")


def _regexes(grader: dict):
    """(label, pattern, flags) for every regex a grader carries."""
    t = grader.get("type")
    if t == "regex":
        yield "pattern", grader.get("pattern", ""), grader.get("flags", "")
    elif t == "tool_used" and grader.get("input_match"):
        yield "input_match", grader["input_match"], ""
    elif t == "tool_order":
        for side in ("before", "after"):
            v = grader.get(side)
            if isinstance(v, dict) and v.get("input_match"):
                yield f"{side}.input_match", v["input_match"], ""


def _js_regex_errors(items: list[tuple[str, str, str]]) -> list[str]:
    if not items or not NODE:
        return []
    script = (
        "const items=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "for(const [label,p,f] of items){try{new RegExp(p,f)}"
        "catch(e){console.log(label+': '+e.message)}}"
    )
    out = subprocess.run([NODE, "-e", script], input=json.dumps(items),
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def problems(case_path: Path) -> list[str]:
    errs: list[str] = []
    try:
        spec = yaml.safe_load(case_path.read_text())
    except yaml.YAMLError as e:
        return [f"not valid YAML: {e}"]
    if not isinstance(spec, dict):
        return ["not a mapping"]
    case_dir, skill = case_path.parent, case_path.parents[2].name

    for key in ("schema_version", "name"):
        if not spec.get(key):
            errs.append(f"missing {key}")
    if spec.get("name") and spec["name"] != case_dir.name:
        errs.append(f"name {spec['name']!r} != folder {case_dir.name!r}")
    if not (spec.get("execution") or {}).get("prompt"):
        errs.append("missing execution.prompt")

    scaffold = (spec.get("context") or {}).get("scaffold_script")
    if scaffold:
        sp = case_dir / scaffold
        if not sp.is_file():
            errs.append(f"scaffold {scaffold} missing")
        else:
            if not sp.stat().st_mode & stat.S_IXUSR:
                errs.append(f"scaffold {scaffold} not executable")
            r = subprocess.run(["bash", "-n", str(sp)], capture_output=True, text=True)
            if r.returncode:
                errs.append(f"scaffold {scaffold} does not parse: {r.stderr.strip()}")

    graders = spec.get("graders") or []
    if not graders:
        errs.append("no graders")
    names = [g.get("name") for g in graders]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        errs.append(f"duplicate grader names: {dupes}")
    regexes = []
    for g in graders:
        if g.get("type") not in GRADER_TYPES:
            errs.append(f"grader {g.get('name')!r}: unknown type {g.get('type')!r}")
        if g.get("type") == "tool_used" and g.get("tool") == "Skill" \
                and g.get("input_match") not in (None, skill):
            errs.append(f"grader {g.get('name')!r}: Skill grader names "
                        f"{g.get('input_match')!r}, case is in {skill!r}")
        regexes += [(f"grader {g.get('name')!r} {label}", p, f)
                    for label, p, f in _regexes(g)]
    errs += _js_regex_errors(regexes)
    return errs


def cases():
    return sorted(REPO.glob("claude/*/evals/*/case.yaml"))


class EvalCases(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertGreaterEqual(len(cases()), 1)

    def test_regex_compile_check_ran(self):
        # problems() skips the JS compile check without node; say so, don't hide it.
        if not NODE:
            self.skipTest("node not installed: grader regexes NOT compile-checked")

    def test_every_case_is_well_formed(self):
        for path in cases():
            with self.subTest(case=str(path.relative_to(REPO))):
                self.assertEqual(problems(path), [])

    def test_checker_rejects_broken_cases(self):
        good = {
            "schema_version": "1.0", "name": "demo",
            "context": {"scaffold_script": "scaffold.sh"},
            "execution": {"prompt": "do it"},
            "graders": [
                {"name": "ran", "type": "tool_used", "tool": "Bash",
                 "input_match": r"(?<!which |-v )\bfoo\b"},
                {"name": "skill-fired", "type": "tool_used", "tool": "Skill",
                 "input_match": "myskill"},
            ],
        }
        breakages = {
            "!= folder": lambda s: s.update(name="other"),
            "missing execution.prompt": lambda s: s.update(execution={}),
            "duplicate grader names": lambda s: s["graders"].append(dict(s["graders"][0])),
            "unknown type": lambda s: s["graders"].append({"name": "x", "type": "regexx"}),
            "Skill grader names": lambda s: s["graders"][1].update(input_match="otherskill"),
            "not executable": None,  # scaffold mode, below
            "does not parse": None,  # scaffold body, below
        }
        if NODE:
            breakages["Invalid regular expression"] = \
                lambda s: s["graders"][0].update(input_match="foo(")

        with tempfile.TemporaryDirectory() as tmp:
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

            def build(mutate=None, scaffold_body="true\n", mode=0o755):
                spec = json.loads(json.dumps(good))
                if mutate:
                    mutate(spec)
                d = Path(tmp) / "claude" / "myskill" / "evals" / "demo"
                if d.exists():
                    shutil.rmtree(d)
                d.mkdir(parents=True)
                (d / "case.yaml").write_text(yaml.safe_dump(spec))
                sc = d / "scaffold.sh"
                sc.write_text("#!/usr/bin/env bash\n" + scaffold_body)
                os.chmod(sc, mode)
                return d / "case.yaml"

            self.assertEqual(problems(build()), [], "the unbroken case must pass")
            for needle, mutate in breakages.items():
                if mutate is None:
                    continue
                with self.subTest(breakage=needle):
                    errs = problems(build(mutate))
                    self.assertTrue(any(needle in e for e in errs), errs)
            with self.subTest(breakage="not executable"):
                errs = problems(build(mode=0o644))
                self.assertTrue(any("not executable" in e for e in errs), errs)
            with self.subTest(breakage="does not parse"):
                errs = problems(build(scaffold_body="if then fi (\n"))
                self.assertTrue(any("does not parse" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
