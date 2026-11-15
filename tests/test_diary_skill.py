#!/usr/bin/env python3
"""Pins the diary skill's contract for an unresolvable DIARY_PATH.

On 2026-11-14 the diary had been silent for two weeks. The skill reads
DIARY_PATH from a ~/.claude/CLAUDE.md block and a settings fragment that only
claude-personal-config/install.sh writes, and the installer had never run on
that workstation. Nothing said so. The skill must make that state loud: say it
in the reply and name the fix, never skip the entry silently.

Text checks: these are properties of the instructions, not of code.
"""

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "claude" / "diary" / "SKILL.md"


class UnsetDiaryPathIsLoud(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text()
        m = re.search(r"^## If `DIARY_PATH` can't be resolved\n(.*?)(?=^## )", self.text, re.M | re.S)
        self.assertIsNotNone(m, "missing the unresolved-DIARY_PATH section")
        self.section = m.group(1)

    def test_section_comes_before_the_trigger(self):
        # Read before deciding to write, not discovered after.
        self.assertLess(self.text.index("## If `DIARY_PATH` can't be resolved"),
                        self.text.index("## When to write"))

    def test_forbids_skipping_silently(self):
        self.assertIn("never skip the entry silently", self.section)

    def test_says_it_in_the_reply_and_names_the_fix(self):
        self.assertIn("say so in your reply", self.section)
        self.assertIn("DIARY_PATH=<dir> ./install.sh", self.section)

    def test_does_not_guess_a_location(self):
        # A portable skill can't know a home path; a guess could land a
        # personal entry in work storage, or the reverse.
        self.assertIn("ask the user where", self.section)


if __name__ == "__main__":
    unittest.main()
