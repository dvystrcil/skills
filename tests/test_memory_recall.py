#!/usr/bin/env python3
"""Tests for memory-recall.py: archived memories that match a prompt (homelab#2002 AC5).

The MEMORY.md index is always loaded. MEMORY-ARCHIVE.md is not, by either
tool. A lesson archived to keep the index under its 25,000-char budget is only
useful if something brings it back when a prompt is about it. This script is
that something, shared by both tools:

  * Claude Code: a UserPromptSubmit hook (`--claude-hook`, JSON in/out)
  * opencode: a `prompt` hook plugin (plain text in/out)

It is deterministic keyword matching, not a model call. #1988 showed an LLM
consolidating memory invented reasons, and D-040 keeps small models out of
filter roles. A wrong recall costs a few lines of context. A missed one costs
what the archive costs today.
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
_spec = importlib.util.spec_from_file_location("memory_recall", BIN / "memory-recall.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules["memory_recall"] = mod
_spec.loader.exec_module(mod)

ARCHIVE = """# Memory Archive (not auto-loaded)
Intro text mentioning restic and postgres, which must not match: it is not an entry.
## Done / historical projects
- [vt350 = Voron Trident 350](project_vt350.md) — dvystrcil/vt350 is the Voron printer build repo
- [Vulkan evaluated, rejected](project_vulkan_evaluated_rejected.md) — llama.cpp Vulkan loses on long context and MoE
- [restic restore drill](project_restic_restore.md) — monthly restic restore test of the claude memory backup
- [harbor gc](reference_harbor_gc.md) — Harbor garbage collection runs Sunday; repository cleanup policy
- [gone](feedback_gone.md) — this file was deleted but the line stayed
- [restic restore drill](project_restic_restore.md) — duplicate line for the same file
- [c1](project_c1.md) — cluster node drain
- [c2](project_c2.md) — cluster node cordon
- [c3](project_c3.md) — cluster node taint
- [c4](project_c4.md) — cluster node label
"""

INDEX = """# Memory Index
- [harbor gc](reference_harbor_gc.md) — Harbor garbage collection runs Sunday
"""


def topic(desc: str) -> str:
    return f"---\nname: x\ndescription: {desc}\nmetadata:\n  type: project\n---\n\nbody\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.mem = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.mem)
        (self.mem / "MEMORY-ARCHIVE.md").write_text(ARCHIVE)
        (self.mem / "MEMORY.md").write_text(INDEX)
        (self.mem / "project_vt350.md").write_text(topic("Voron printer repo"))
        (self.mem / "project_vulkan_evaluated_rejected.md").write_text(topic("Vulkan backend for AMD GPUs rejected"))
        (self.mem / "project_restic_restore.md").write_text(topic("restore drill for restic snapshots"))
        (self.mem / "reference_harbor_gc.md").write_text(topic("harbor"))
        for i in range(1, 5):
            (self.mem / f"project_c{i}.md").write_text(topic("k8s"))

    def names(self, prompt: str, **kw) -> list[str]:
        return [h.file for h in mod.recall(self.mem, prompt, **kw)]


class MatchingTest(Base):
    def test_matching_prompt_returns_the_entry(self):
        self.assertEqual(self.names("can you do the monthly restic restore test?"), ["project_restic_restore.md"])

    def test_unrelated_prompt_returns_nothing(self):
        self.assertEqual(self.names("rename the variable in this function"), [])

    def test_one_shared_common_word_is_not_enough(self):
        # "test" alone appears in an entry; a single keyword is noise.
        self.assertEqual(self.names("write a test"), [])

    def test_two_common_words_are_not_enough(self):
        # "cluster" and "node" are each in 4 of 9 entries: matching both says
        # little about which one the prompt is about. Two RARE words are needed
        # (tuned on 120 real prompts: common-word pairs put a block on 18 of 30).
        self.assertEqual(self.names("the cluster node is slow"), [])
        self.assertEqual(self.names("drain the cluster node"), [])

    def test_long_prompt_is_skipped(self):
        # A paste or a continuation summary shares rare words with everything.
        long = "monthly restic restore " + " ".join(f"word{i}x" for i in range(60))
        self.assertEqual(self.names(long), [])

    def test_description_frontmatter_counts(self):
        # "AMD" and "backend" only appear in the topic file's description.
        self.assertEqual(self.names("should we try the vulkan backend on amd?"), ["project_vulkan_evaluated_rejected.md"])

    def test_case_and_plural_insensitive(self):
        self.assertEqual(self.names("RESTIC restores"), ["project_restic_restore.md"])

    def test_entries_already_in_the_index_are_skipped(self):
        # The index is loaded every session; repeating it wastes context.
        self.assertEqual(self.names("harbor garbage collection"), [])

    def test_missing_file_is_skipped(self):
        self.assertEqual(self.names("this file was deleted but the line stayed"), [])

    def test_duplicate_lines_give_one_hit(self):
        self.assertEqual(self.names("restic restore drill"), ["project_restic_restore.md"])

    def test_limit(self):
        self.assertEqual(len(self.names("restic restore vulkan llama.cpp voron printer", limit=2)), 2)

    def test_intro_prose_is_not_an_entry(self):
        self.assertEqual(self.names("postgres restic"), [])

    def test_no_archive_returns_nothing(self):
        (self.mem / "MEMORY-ARCHIVE.md").unlink()
        self.assertEqual(self.names("restic restore"), [])


class RareBoundaryTest(unittest.TestCase):
    def test_word_in_exactly_rare_min_df_entries_is_rare(self):
        mem = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, mem)
        lines = []
        for i in range(mod.RARE_MIN_DF):
            lines.append(f"- [a{i}](project_a{i}.md) — alpha bravo")
            (mem / f"project_a{i}.md").write_text(topic("x"))
        for i in range(10):
            lines.append(f"- [f{i}](project_f{i}.md) — filler{i} words")
            (mem / f"project_f{i}.md").write_text(topic("x"))
        (mem / "MEMORY-ARCHIVE.md").write_text("\n".join(lines) + "\n")
        self.assertEqual(len(mod.recall(mem, "alpha bravo", limit=10)), mod.RARE_MIN_DF)


class BodyTierTest(Base):
    """Second tier: BM25 over the whole topic file, gated by a high score.

    The first tier only sees the index line and `description:`, so a prompt
    that uses the file's own words ("ztunnel", "waypoint") finds nothing. On
    the real archive (373 entries), a whole-file BM25 match recalled 6 of 14
    hand-written prompts the first tier missed at score >= BODY_MIN_SCORE, and
    every stand-in prompt it fired on at that score was a relevant memory.
    The fixture corpus is tiny, so its scores are not on that scale: these
    tests set the threshold themselves.
    """

    BODY = ("---\nname: x\ndescription: mesh notes\nmetadata:\n  type: project\n---\n\n"
            "Pods enroll through ztunnel; a waypoint proxy handles L7. "
            "ztunnel restarts drop enrollment until the waypoint is redeployed.\n")

    def setUp(self):
        super().setUp()
        with (self.mem / "MEMORY-ARCHIVE.md").open("a") as f:
            f.write("- [mesh](project_mesh.md) — service mesh topology\n")
        (self.mem / "project_mesh.md").write_text(self.BODY)

    def threshold(self, value: float):
        old = mod.BODY_MIN_SCORE
        mod.BODY_MIN_SCORE = value
        self.addCleanup(setattr, mod, "BODY_MIN_SCORE", old)

    def test_body_words_recall_the_entry(self):
        # Neither word is in the index line or the description.
        self.threshold(0.1)
        self.assertEqual(self.names("why did ztunnel drop the waypoint"), ["project_mesh.md"])

    def test_body_match_below_threshold_returns_nothing(self):
        self.threshold(1e9)
        self.assertEqual(self.names("why did ztunnel drop the waypoint"), [])

    def test_default_threshold_keeps_weak_body_matches_out(self):
        # One shared body word scores far below the default gate.
        self.assertEqual(self.names("restart the ztunnel"), [])

    def test_first_tier_hits_come_first_and_are_not_repeated(self):
        self.threshold(0.1)
        hits = self.names("restic restore drill and the ztunnel waypoint", limit=5)
        self.assertEqual(hits[0], "project_restic_restore.md")
        self.assertIn("project_mesh.md", hits)
        self.assertEqual(len(hits), len(set(hits)))

    def test_long_prompt_skips_the_body_tier_too(self):
        self.threshold(0.1)
        long = "ztunnel waypoint " + " ".join(f"word{i}x" for i in range(60))
        self.assertEqual(self.names(long), [])

    def test_index_entries_are_not_body_matched(self):
        # The index is already loaded; its files must not come back via their body.
        self.threshold(0.1)
        (self.mem / "reference_harbor_gc.md").write_text(self.BODY.replace("mesh notes", "gc"))
        self.assertNotIn("reference_harbor_gc.md", self.names("ztunnel waypoint", limit=10))

    def test_ties_break_by_file_name(self):
        self.threshold(0.1)
        with (self.mem / "MEMORY-ARCHIVE.md").open("a") as f:
            f.write("- [mesh2](project_amesh.md) — service mesh topology\n")
        (self.mem / "project_amesh.md").write_text(self.BODY)
        self.assertEqual(self.names("ztunnel waypoint", limit=2), ["project_amesh.md", "project_mesh.md"])


class RenderTest(Base):
    def test_block_lists_absolute_paths_and_hooks(self):
        out = mod.render(mod.recall(self.mem, "restic restore test"))
        self.assertIn(str(self.mem / "project_restic_restore.md"), out)
        self.assertIn("monthly restic restore test", out)
        self.assertTrue(out.startswith("<memory-recall>"))

    def test_nothing_renders_empty(self):
        self.assertEqual(mod.render([]), "")


class CliTest(Base):
    def run_main(self, argv: list[str], stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out):
                rc = mod.main(argv)
        finally:
            sys.stdin = old
        return rc, out.getvalue()

    def test_plain_mode_reads_prompt_from_stdin(self):
        rc, out = self.run_main(["--memory-dir", str(self.mem)], "monthly restic restore")
        self.assertEqual(rc, 0)
        self.assertIn("project_restic_restore.md", out)

    def test_claude_hook_mode_emits_additional_context(self):
        rc, out = self.run_main(["--memory-dir", str(self.mem), "--claude-hook"],
                                json.dumps({"prompt": "monthly restic restore", "hook_event_name": "UserPromptSubmit"}))
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("project_restic_restore.md", doc["hookSpecificOutput"]["additionalContext"])

    def test_claude_hook_derives_memory_dir_from_transcript_path(self):
        proj = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, proj)
        shutil.copytree(self.mem, proj / "memory")
        rc, out = self.run_main(["--claude-hook"], json.dumps(
            {"prompt": "restic restore", "transcript_path": str(proj / "abc.jsonl")}))
        self.assertEqual(rc, 0)
        self.assertIn(str(proj / "memory" / "project_restic_restore.md"), out)

    def test_claude_hook_no_match_prints_nothing(self):
        rc, out = self.run_main(["--memory-dir", str(self.mem), "--claude-hook"], json.dumps({"prompt": "hello"}))
        self.assertEqual((rc, out), (0, ""))

    def test_never_blocks_a_prompt(self):
        # Bad input must not stop the user's prompt: exit 0, nothing printed.
        for argv, stdin in ((["--claude-hook"], "not json"),
                            (["--memory-dir", "/nonexistent/x"], "restic restore"),
                            (["--claude-hook"], json.dumps({"prompt": "restic"}))):
            rc, out = self.run_main(argv, stdin)
            self.assertEqual((rc, out), (0, ""), argv)


if __name__ == "__main__":
    unittest.main()
