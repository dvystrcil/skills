#!/usr/bin/env python3
"""
SKILL.md schema linter for MCP-dispatchable skills (claude/*/SKILL.md).

Migrated from homelab/bin/tests/ in homelab#225 phase 2. The cluster-
resident MCP server's dispatcher reads the structured `args:` /
`subcommands:` frontmatter on each `claude/<skill>/SKILL.md` to derive
its MCP tool schema. Malformed input here breaks the dispatcher
silently — this lint runs at PR-time as the upstream gate.

Scope: lints only `claude/*/SKILL.md` (MCP-dispatchable skills).
Owui-side SKILL.md files at `owui/*/SKILL.md` use a different shape
(prompt-time content, no `script:`/`args:`) and are validated by the
sibling `validate-frontmatter` bash check in `.github/workflows/
validate-skills.yml`.

Required frontmatter keys (every skill):
  - name (string)
  - description (string)

Sentinel mode (NOT MCP-dispatchable):
  - script: null
  - args: []
  - no subcommands

Dispatchable mode (script is a string):
  - args: required list of arg specs
  - subcommands: optional; if present, args[0] must be an enum selector

Each arg spec requires:
  - name (string)
  - type (one of: string, integer, boolean, enum)
  - required (bool)
  - cli_position (positive int) OR cli_flag (string starting with --)
  - description (string)
  - For type=enum: values (list of strings)
  - Optional: default (any), conditional (bool)

Run with:
    python3 tests/test_skill_schema.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "ERROR: PyYAML not installed. Try: apt install python3-yaml OR pip install pyyaml\n"
    )
    sys.exit(2)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CLAUDE_DIR = REPO_ROOT / "claude"

VALID_TYPES = {"string", "integer", "boolean", "enum"}


def lint_arg(path: str, arg) -> list[str]:
    """Return a list of error strings (empty if arg is valid)."""
    errors = []
    if not isinstance(arg, dict):
        return [f"{path}: arg entry is not a mapping: {arg!r}"]

    for required in ("name", "type", "required", "description"):
        if required not in arg:
            errors.append(f"{path}: missing required key '{required}' in arg")

    t = arg.get("type")
    if t and t not in VALID_TYPES:
        errors.append(f"{path}: type must be one of {sorted(VALID_TYPES)}, got {t!r}")

    if t == "enum" and "values" not in arg:
        errors.append(f"{path}: type=enum requires 'values' list")
    elif t == "enum":
        vals = arg["values"]
        if not isinstance(vals, list) or not all(isinstance(v, str) for v in vals):
            errors.append(f"{path}: 'values' must be a list of strings, got {vals!r}")

    has_position = "cli_position" in arg
    has_flag = "cli_flag" in arg
    if has_position == has_flag:
        errors.append(
            f"{path}: arg must declare exactly one of 'cli_position' or 'cli_flag'"
        )
    if has_position:
        pos = arg["cli_position"]
        if not (isinstance(pos, int) and pos > 0):
            errors.append(f"{path}: cli_position must be a positive int, got {pos!r}")
    if has_flag:
        flag = arg["cli_flag"]
        if not (isinstance(flag, str) and flag.startswith("--")):
            errors.append(f"{path}: cli_flag must be a string starting with '--', got {flag!r}")

    return errors


def lint_args_list(path: str, args) -> list[str]:
    if not isinstance(args, list):
        return [f"{path}: 'args' must be a list, got {type(args).__name__}"]
    errors = []
    positions_seen = set()
    for i, a in enumerate(args):
        errs = lint_arg(f"{path}[{i}]", a)
        errors.extend(errs)
        if isinstance(a, dict) and "cli_position" in a:
            pos = a["cli_position"]
            if pos in positions_seen:
                errors.append(f"{path}[{i}]: cli_position {pos} duplicated")
            positions_seen.add(pos)
    return errors


def lint_subcommand(path: str, name: str, sub) -> list[str]:
    errors = []
    if not isinstance(sub, dict):
        return [f"{path}: subcommand '{name}' is not a mapping"]
    if "description" not in sub:
        errors.append(f"{path}: subcommand '{name}' missing description")
    sub_args = sub.get("args", [])
    errors.extend(lint_args_list(f"{path}.subcommands.{name}.args", sub_args))
    if "stdin" in sub:
        s = sub["stdin"]
        if not isinstance(s, dict):
            errors.append(f"{path}: subcommand '{name}' stdin must be a mapping")
        else:
            for k in ("name", "type", "required", "description"):
                if k not in s:
                    errors.append(f"{path}: subcommand '{name}' stdin missing key '{k}'")
    return errors


def lint_skill_md(skill_md_path: Path) -> list[str]:
    """Return list of errors for one SKILL.md (empty if clean)."""
    rel = skill_md_path.relative_to(REPO_ROOT)
    text = skill_md_path.read_text()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [f"{rel}: no YAML frontmatter found"]
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        return [f"{rel}: invalid YAML: {e}"]
    if not isinstance(fm, dict):
        return [f"{rel}: frontmatter is not a mapping"]

    errors = []
    for k in ("name", "description"):
        if k not in fm:
            errors.append(f"{rel}: missing required key '{k}'")

    script = fm.get("script")
    args = fm.get("args")
    subs = fm.get("subcommands")

    # Sentinel mode: script: null + args: [] + no subcommands
    if script is None:
        if args is not None and args != []:
            errors.append(f"{rel}: script is null (sentinel mode) but args is not [] (got {args!r})")
        if subs:
            errors.append(f"{rel}: script is null (sentinel mode) cannot have subcommands")
        return errors

    # Dispatchable: script is a string, args required (possibly with subcommands)
    if not isinstance(script, str):
        errors.append(f"{rel}: script must be a string path or null, got {type(script).__name__}")

    if args is None:
        errors.append(f"{rel}: dispatchable skill (script is set) must have 'args' key")
    else:
        errors.extend(lint_args_list(f"{rel}.args", args))

    if subs is not None:
        if not isinstance(subs, dict):
            errors.append(f"{rel}: 'subcommands' must be a mapping")
        else:
            selector = None
            if args and isinstance(args, list) and args:
                first = args[0]
                if isinstance(first, dict) and first.get("type") == "enum":
                    selector = first
            if not selector:
                errors.append(
                    f"{rel}: subcommands present but top-level args[0] is not an enum selector"
                )
            else:
                declared = set(selector.get("values") or [])
                actual = set(subs.keys())
                missing = declared - actual
                extra = actual - declared
                if missing:
                    errors.append(
                        f"{rel}: subcommands missing entries declared in selector enum: {sorted(missing)}"
                    )
                if extra:
                    errors.append(
                        f"{rel}: subcommand entries not declared in selector enum: {sorted(extra)}"
                    )
            for name, sub in subs.items():
                errors.extend(lint_subcommand(f"{rel}", name, sub))

    return errors


class TestClaudeSkillSchema(unittest.TestCase):
    """Lint every claude/*/SKILL.md. One subTest per file."""

    def test_every_claude_skill_md_lints_clean(self):
        if not CLAUDE_DIR.exists():
            self.skipTest(f"no claude/ directory at {CLAUDE_DIR}")

        skill_files = sorted(CLAUDE_DIR.glob("*/SKILL.md"))
        self.assertGreater(
            len(skill_files), 0,
            f"expected at least one claude/<skill>/SKILL.md under {CLAUDE_DIR}",
        )

        for f in skill_files:
            with self.subTest(skill=f.parent.name):
                errors = lint_skill_md(f)
                self.assertEqual(
                    errors, [],
                    f"\n  ".join([f"{f.parent.name} has schema errors:"] + errors),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
