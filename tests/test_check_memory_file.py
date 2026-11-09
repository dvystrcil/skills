#!/usr/bin/env python3
"""Tests for check-memory-file.py, the format gate for one memory file (homelab#2002 AC3).

Claude Code and opencode now write into the same memory dir. A file only helps
the next session if it has the shape both tools expect: frontmatter with name,
description and a type, a `type_name.md` file name that matches the type, and
for feedback/project memories the `**Why:**` and `**How to apply:**` lines.
Those lines are why the store exists. homelab#1988 found that memory keeps the
"why" only when an agent writes it on purpose.

The gate is for files being written, not the legacy store. On 2026-11-09, 67
feedback and 45 project files had no `**Why:**` line. They predate the rule,
and a gate that fails on all of them would just get ignored.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
_spec = importlib.util.spec_from_file_location("check_memory_file", BIN / "check-memory-file.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check_memory_file"] = mod
_spec.loader.exec_module(mod)

GOOD_FEEDBACK = """---
name: never-git-add-all
description: Never `git add -A`; stage explicit paths
metadata:
  type: feedback
---

Stage explicit paths only.

**Why:** a stray plaintext secret file was swept into a commit.
**How to apply:** `git add path/a path/b`, never `-A` or `.`.
"""

LEGACY_TOP_LEVEL_TYPE = """---
name: dns-gotcha
description: something about DNS
type: reference
---

Body.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(text)
        return p

    def problems(self, name: str, text: str, index: str | None = None) -> list[str]:
        if index is not None:
            (self.dir / "MEMORY.md").write_text(index)
        return mod.check_file(self.write(name, text), require_index=index is not None)


class GoodFilesPassTest(Base):
    def test_feedback_with_why_and_how(self):
        self.assertEqual(self.problems("feedback_never_git_add_all.md", GOOD_FEEDBACK), [])

    def test_reference_needs_no_why(self):
        text = GOOD_FEEDBACK.replace("type: feedback", "type: reference")
        self.assertEqual(self.problems("reference_never_git_add_all.md", text), [])

    def test_legacy_top_level_type_is_accepted(self):
        # 90 live files use `type:` at the top level instead of under metadata.
        self.assertEqual(self.problems("reference_dns_gotcha.md", LEGACY_TOP_LEVEL_TYPE), [])

    def test_indexed_in_archive_counts(self):
        (self.dir / "MEMORY-ARCHIVE.md").write_text(
            "- [x](feedback_never_git_add_all.md) — hook\n")
        self.assertEqual(self.problems("feedback_never_git_add_all.md", GOOD_FEEDBACK, index="# Memory Index\n"), [])


class BadFilesFailTest(Base):
    def assertProblem(self, problems: list[str], needle: str):
        self.assertTrue(any(needle in p for p in problems), f"{needle!r} not in {problems}")

    def test_no_frontmatter(self):
        self.assertProblem(self.problems("feedback_x.md", "**Why:** a\n**How to apply:** b\n"), "frontmatter")

    def test_missing_description(self):
        text = GOOD_FEEDBACK.replace("description: Never `git add -A`; stage explicit paths\n", "")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "description")

    def test_empty_name(self):
        text = GOOD_FEEDBACK.replace("name: never-git-add-all", "name: ")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "name")

    def test_unknown_type(self):
        text = GOOD_FEEDBACK.replace("type: feedback", "type: lesson")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "type")

    def test_missing_type(self):
        text = GOOD_FEEDBACK.replace("metadata:\n  type: feedback\n", "")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "type")

    def test_filename_prefix_must_match_type(self):
        self.assertProblem(self.problems("project_never_git_add_all.md", GOOD_FEEDBACK), "prefix")

    def test_filename_pattern(self):
        self.assertProblem(self.problems("feedback-Never Add.md", GOOD_FEEDBACK), "file name")

    def test_feedback_without_why(self):
        text = GOOD_FEEDBACK.replace("**Why:** a stray plaintext secret file was swept into a commit.\n", "")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "**Why:**")

    def test_project_without_how(self):
        text = GOOD_FEEDBACK.replace("type: feedback", "type: project").replace(
            "**How to apply:** `git add path/a path/b`, never `-A` or `.`.\n", "")
        self.assertProblem(self.problems("project_never_git_add_all.md", text), "**How to apply:**")

    def test_why_inside_frontmatter_does_not_count(self):
        # Marker lines that start a line, but inside the frontmatter (a block-scalar description).
        text = GOOD_FEEDBACK.replace("description: Never", "description: >\n  **Why:** in frontmatter\n  **How to apply:** in frontmatter\n  Never")
        text = text.replace("**Why:** a stray", "Because a stray").replace("**How to apply:** `git", "Use `git")
        problems = self.problems("feedback_never_git_add_all.md", text)
        self.assertProblem(problems, "**Why:**")
        self.assertProblem(problems, "**How to apply:**")

    def test_empty_why(self):
        text = GOOD_FEEDBACK.replace("**Why:** a stray plaintext secret file was swept into a commit.", "**Why:**")
        self.assertProblem(self.problems("feedback_never_git_add_all.md", text), "**Why:**")

    def test_not_in_index(self):
        self.assertProblem(
            self.problems("feedback_never_git_add_all.md", GOOD_FEEDBACK, index="# Memory Index\n- [y](feedback_y.md) — h\n"),
            "index")

    def test_in_index(self):
        self.assertEqual(self.problems(
            "feedback_never_git_add_all.md", GOOD_FEEDBACK,
            index="- [never-git-add-all](feedback_never_git_add_all.md) — stage explicit paths\n"), [])


class CliTest(Base):
    def run_main(self, *argv: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = mod.main(list(argv))
        return rc, out.getvalue() + err.getvalue()

    def test_exit_0_on_good(self):
        p = self.write("feedback_never_git_add_all.md", GOOD_FEEDBACK)
        rc, _ = self.run_main(str(p))
        self.assertEqual(rc, 0)

    def test_exit_1_names_the_file_and_problem(self):
        p = self.write("feedback_never_git_add_all.md", GOOD_FEEDBACK.replace("**Why:**", "Why:"))
        rc, out = self.run_main(str(p))
        self.assertEqual(rc, 1)
        self.assertIn("feedback_never_git_add_all.md", out)
        self.assertIn("**Why:**", out)

    def test_exit_2_on_missing_file(self):
        rc, _ = self.run_main(str(self.dir / "feedback_nope.md"))
        self.assertEqual(rc, 2)

    def test_index_flag(self):
        (self.dir / "MEMORY.md").write_text("# Memory Index\n")
        p = self.write("feedback_never_git_add_all.md", GOOD_FEEDBACK)
        rc, out = self.run_main("--require-index", str(p))
        self.assertEqual(rc, 1)
        self.assertIn("index", out)

    def test_index_files_themselves_are_refused(self):
        p = self.write("MEMORY.md", "# Memory Index\n")
        rc, _ = self.run_main(str(p))
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
