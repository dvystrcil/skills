#!/usr/bin/env python3
"""Tests for the memory-index load-budget gate (homelab#1800 AC3).

Claude Code loads only a prefix of `MEMORY.md`. Everything past the cut-off
is invisible to every session, and nothing says so except a warning in the
system prompt that the agent itself has to notice. On 2026-11-01 that was
79 of 233 lines — a third of the index — gone since whenever it crossed.

The limits were read off the shipped binary (claude-code 2.1.316) and
checked against the real file before any of this was written:

    FH = 200       lines
    ZJ = 25000     characters (JS string length, i.e. UTF-16 code units)

The file was 38,162 bytes but the warning said "36.7KB" = 37,588 chars / 1024,
and the observed cut-off (line 155) is exactly where cumulative characters
first pass 25,000 (24,813 through line 154, 25,008 through 155). In bytes
line 154 would already be over. So: characters, not bytes.

What is pinned here is mostly the ways the gate could be believed wrongly:

  * counting bytes instead of characters — every em-dash would fire the
    gate early and train people to raise the limit
  * passing a file that is within the line cap but over the char cap, which
    is the case that actually happened (233 lines, but cut at 155 by chars)
  * reporting a cut-off line that is not where the loader really cuts, so
    a compaction "fixes" the wrong tail
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
_spec = importlib.util.spec_from_file_location(
    "check_memory_index", BIN / "check-memory-index.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["check_memory_index"] = mod
_spec.loader.exec_module(mod)


def entry(i: int, width: int) -> str:
    """One index line of exactly `width` characters (no newline)."""
    head = f"- [e{i}](e{i}.md) — "
    return (head + "x" * width)[:width]


class LimitsMatchTheLoaderTest(unittest.TestCase):
    """The defaults ARE the claim. If they drift from the binary the gate
    passes files the loader truncates."""

    def test_defaults(self):
        self.assertEqual(mod.MAX_LINES, 200)
        self.assertEqual(mod.MAX_CHARS, 25000)
        self.assertEqual(mod.MAX_LINE_CHARS, 200)


class CharsNotBytesTest(unittest.TestCase):

    def test_em_dash_counts_as_one(self):
        self.assertEqual(mod.js_length("a—b"), 3)

    def test_astral_char_counts_as_two_like_js(self):
        # JS .length counts UTF-16 code units; an emoji is a surrogate pair.
        self.assertEqual(mod.js_length("🙂"), 2)

    def test_multibyte_file_under_char_cap_passes(self):
        # 150 lines of 160 chars with an em-dash each: ~24.2k chars but
        # ~24.5k+ bytes. Must pass.
        text = "\n".join(entry(i, 160) for i in range(150)) + "\n"
        self.assertLess(mod.js_length(text), 25000)
        self.assertGreater(len(text.encode()), mod.js_length(text))
        self.assertEqual(mod.check(text).violations, [])


class CutOffTest(unittest.TestCase):

    def test_reproduces_observed_shape(self):
        # The 2026-11-01 shape: 233 lines, under no single-line rule but
        # cut by characters well before the line cap.
        text = "\n".join(entry(i, 162) for i in range(233)) + "\n"
        r = mod.check(text)
        # 163 chars per line incl. newline -> 153 lines fit in 25000.
        self.assertEqual(r.first_hidden_line, 25000 // 163 + 1)
        self.assertEqual(r.hidden_lines, 233 - 25000 // 163)
        self.assertTrue(any("characters" in v for v in r.violations))

    def test_line_cap_alone(self):
        text = "\n".join(entry(i, 20) for i in range(205)) + "\n"
        r = mod.check(text)
        self.assertEqual(r.first_hidden_line, 201)
        self.assertEqual(r.hidden_lines, 5)
        self.assertTrue(any("lines" in v for v in r.violations))

    def test_exactly_at_limits_passes(self):
        # 125 lines * (199 + newline) = 25000 chars, 125 lines.
        text = "".join(entry(i, 199) + "\n" for i in range(125))
        self.assertEqual(mod.js_length(text), 25000)
        r = mod.check(text)
        self.assertEqual(r.violations, [])
        self.assertIsNone(r.first_hidden_line)
        self.assertEqual(r.hidden_lines, 0)

    def test_one_char_over_fails(self):
        text = "".join(entry(i, 199) + "\n" for i in range(125)) + "x"
        r = mod.check(text)
        self.assertNotEqual(r.violations, [])
        self.assertEqual(r.first_hidden_line, 126)


class LongLineTest(unittest.TestCase):

    def test_long_line_named_by_number(self):
        lines = [entry(i, 100) for i in range(10)]
        lines[6] = entry(6, 201)
        r = mod.check("\n".join(lines) + "\n")
        self.assertEqual(len(r.violations), 1)
        self.assertIn("line 7", r.violations[0])

    def test_200_is_allowed(self):
        r = mod.check(entry(0, 200) + "\n")
        self.assertEqual(r.violations, [])


class DiscoveryTest(unittest.TestCase):
    """Portable means no hardcoded project path. The project dir name is
    derived from the working directory (`-home-dan-Code` here, something else
    on the work workstation), so the gate must find every index itself."""

    def make_home(self, d: Path, projects: dict[str, str | None]) -> Path:
        for name, text in projects.items():
            mem = d / "projects" / name / "memory"
            mem.mkdir(parents=True)
            if text is not None:
                (mem / "MEMORY.md").write_text(text)
        return d

    def test_finds_every_project_index(self):
        with tempfile.TemporaryDirectory() as d:
            home = self.make_home(Path(d), {"-a": "x\n", "-b": "y\n", "-c": None})
            found = mod.discover(home)
            self.assertEqual([p.parent.parent.name for p in found], ["-a", "-b"])

    def test_claude_config_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            self.make_home(Path(d), {"-w": "x\n"})
            self.assertEqual(mod.claude_home({"CLAUDE_CONFIG_DIR": d}), Path(d))
            self.assertEqual(mod.claude_home({}), Path.home() / ".claude")


class MainTest(unittest.TestCase):
    """Exit code is the gate. A crash or a missing file must not read as
    pass — an absent index is not a compliant one."""

    def run_main(self, text: str | None) -> int:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "MEMORY.md"
            if text is not None:
                p.write_text(text)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mod.main([str(p)])
            self.out = buf.getvalue()
            return rc

    def test_pass(self):
        self.assertEqual(self.run_main("- [a](a.md) — hook\n"), 0)
        self.assertIn("OK", self.out)

    def test_fail(self):
        text = "\n".join(entry(i, 162) for i in range(233)) + "\n"
        self.assertEqual(self.run_main(text), 1)
        self.assertIn("FAIL", self.out)
        self.assertIn("starting at line 154", self.out)

    def test_missing_file_fails(self):
        self.assertEqual(self.run_main(None), 2)

    def test_no_args_checks_all_discovered_worst_wins(self):
        bad = "\n".join(entry(i, 162) for i in range(233)) + "\n"
        with tempfile.TemporaryDirectory() as d:
            for name, text in {"-ok": "- [a](a.md) — hook\n", "-bad": bad}.items():
                mem = Path(d) / "projects" / name / "memory"
                mem.mkdir(parents=True)
                (mem / "MEMORY.md").write_text(text)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = mod.main([], env={"CLAUDE_CONFIG_DIR": d})
        self.assertEqual(rc, 1)
        self.assertIn("-ok", buf.getvalue())
        self.assertIn("-bad", buf.getvalue())

    def test_no_index_anywhere_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as d:
            with redirect_stdout(io.StringIO()):
                rc = mod.main([], env={"CLAUDE_CONFIG_DIR": d})
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
