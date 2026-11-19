#!/usr/bin/env python3
"""Tests for merge-memory-lines.py — apply one merge proposal, losslessly.

A merge replaces several overlapping index lines with one line pointing at a
new merged topic file M. homelab#1929 sets the contract, the same as the
archiver's (archive-memory-lines.py):

  * every source's index line moves verbatim into the archive under
    `## Merged <date> → [name](M.md)`; source topic files stay on disk
  * M is written with `merged_from:` in its frontmatter
  * both index files are backed up, verified after writing, and restored
    (and M removed) when verification fails
  * a bad proposal is refused before anything is written, backup included

Most tests drive the shipped script as a subprocess. Faults that cannot be
produced from outside — damage between write and verify — use the module's
`after_write` seam.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
SCRIPT = BIN / "merge-memory-lines.py"

_spec = importlib.util.spec_from_file_location("merge_memory_lines", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["merge_memory_lines"] = mod
_spec.loader.exec_module(mod)

POINTER = ("> {n} more hooks in [MEMORY-ARCHIVE.md](MEMORY-ARCHIVE.md) — files "
           "intact, recalled on relevance, not auto-loaded")

ALPHA = "- [alpha](feedback_alpha.md) — retry the call, with an em-dash — and ünïcode"
BETA = "- [beta](feedback_beta.md) — retries need a backoff"
GAMMA = "- [gamma](user_gamma.md) — unrelated"
DELTA = "- [delta](feedback_delta.md) — retries must be bounded"

INDEX = "\n".join(["# Memory Index", "", ALPHA, BETA, GAMMA, DELTA, "{pointer}"]) + "\n"

ARCHIVE = """# Memory Archive (not auto-loaded)

## Archived 2026-11-01 — older
- [old](reference_old.md) — archived before
"""

FILES = ["feedback_alpha.md", "feedback_beta.md", "user_gamma.md",
         "feedback_delta.md", "reference_old.md"]

BODY = ("Merged from feedback_alpha.md, feedback_beta.md and feedback_delta.md.\n\n"
        "Retry a failed call, with backoff, a bounded number of times.\n\n"
        "**Why:** three separate lessons said one thing.\n\n"
        "**How to apply:** wrap the call; cap attempts at three.\n")

INDEX_LINE = "- [retries](feedback_retries.md) — retry with backoff, bounded (merged)"


def proposal(**over) -> dict:
    p = {
        "sources": ["feedback_alpha.md", "feedback_beta.md", "feedback_delta.md"],
        "name": "retries",
        "file": "feedback_retries.md",
        "type": "feedback",
        "description": "Retry failed calls with backoff, a bounded number of times",
        "body": BODY,
        "index_line": INDEX_LINE,
    }
    p.update(over)
    return {k: v for k, v in p.items() if v is not None}


class Fixture(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="merge-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.mem = self.root / "memory"
        self.mem.mkdir()
        self.backups = self.root / "backups"
        self.prop_path = self.root / "proposal.json"
        for f in FILES:
            (self.mem / f).write_text(f"---\nname: {f}\n---\nbody of {f}\n",
                                      encoding="utf-8")
        self.write(INDEX.format(pointer=POINTER.format(n=1)), ARCHIVE)

    def write(self, index: str, archive: str | None):
        (self.mem / "MEMORY.md").write_text(index, encoding="utf-8")
        if archive is not None:
            (self.mem / "MEMORY-ARCHIVE.md").write_text(archive, encoding="utf-8")

    @property
    def index(self) -> str:
        return (self.mem / "MEMORY.md").read_text(encoding="utf-8")

    @property
    def archive(self) -> str:
        return (self.mem / "MEMORY-ARCHIVE.md").read_text(encoding="utf-8")

    @property
    def merged(self) -> Path:
        return self.mem / "feedback_retries.md"

    def proposals(self, *props, raw: str | None = None):
        text = raw if raw is not None else json.dumps({"proposals": list(props)})
        self.prop_path.write_text(text, encoding="utf-8")

    def args(self, *extra, date="2026-11-04"):
        return ["--memory-dir", str(self.mem), "--backup-dir", str(self.backups),
                "--proposal", str(self.prop_path), "--date", date, *extra]

    def run_cli(self, *extra, **kw):
        return subprocess.run([sys.executable, str(SCRIPT), *self.args(*extra, **kw)],
                              capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "en_US.UTF-8",
                                   "PYTHONDONTWRITEBYTECODE": "1"})

    def snapshot(self):
        return {p.name: p.read_bytes() for p in sorted(self.mem.iterdir())}


# ------------------------------------------------------------------ AC1 apply

class AppliesMergeTest(Fixture):

    def setUp(self):
        super().setUp()
        self.proposals(proposal())

    def test_index_line_replaces_the_first_source_and_sources_leave(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.index.splitlines(),
                         ["# Memory Index", "", INDEX_LINE, GAMMA, POINTER.format(n=4)])

    def test_index_line_takes_the_first_source_place_not_the_second(self):
        self.proposals(proposal(sources=["feedback_alpha.md", "feedback_delta.md"],
                                body=BODY.replace("feedback_beta.md", "beta")))
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.index.splitlines()[2:5], [INDEX_LINE, BETA, GAMMA])

    def test_source_lines_move_verbatim_under_merged_heading(self):
        self.run_cli()
        self.assertTrue(self.archive.startswith(ARCHIVE))
        self.assertEqual(self.archive[len(ARCHIVE):].splitlines(), [
            "", "## Merged 2026-11-04 → [retries](feedback_retries.md)",
            ALPHA, BETA, DELTA])

    def test_merged_file_has_merged_from_frontmatter_and_body(self):
        self.run_cli()
        self.assertEqual(self.merged.read_text(encoding="utf-8"), (
            "---\n"
            "name: retries\n"
            "description: Retry failed calls with backoff, a bounded number of times\n"
            "metadata:\n"
            "  type: feedback\n"
            "merged_from:\n"
            "  - feedback_alpha.md\n"
            "  - feedback_beta.md\n"
            "  - feedback_delta.md\n"
            "---\n\n" + BODY))

    def test_body_without_trailing_newline_gets_one(self):
        self.proposals(proposal(body=BODY.rstrip("\n")))
        self.run_cli()
        self.assertTrue(self.merged.read_text(encoding="utf-8").endswith("three.\n"))

    def test_source_topic_files_stay_on_disk_unchanged(self):
        before = {f: (self.mem / f).read_bytes() for f in FILES}
        self.run_cli()
        self.assertEqual({f: (self.mem / f).read_bytes() for f in FILES}, before)

    def test_merged_file_passes_the_file_check(self):
        self.run_cli()
        r = subprocess.run([sys.executable, str(BIN / "check-memory-file.py"),
                            "--require-index", str(self.merged)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_existing_merged_heading_gets_a_second_merge_appended(self):
        self.run_cli()
        second = proposal(sources=["user_gamma.md", "feedback_retries.md"],
                          name="all", file="feedback_all.md",
                          body=BODY.replace("Merged from",
                                            "From user_gamma.md + feedback_retries.md;"),
                          index_line="- [all](feedback_all.md) — everything")
        self.proposals(second)
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archive.splitlines()[-3:], [
            "## Merged 2026-11-04 → [all](feedback_all.md)", INDEX_LINE, GAMMA])
        self.assertEqual(self.index.splitlines(),
                         ["# Memory Index", "", "- [all](feedback_all.md) — everything",
                          POINTER.format(n=6)])

    def test_missing_archive_is_created(self):
        (self.mem / "MEMORY-ARCHIVE.md").unlink()
        self.write(INDEX.format(pointer=POINTER.format(n=0)), None)
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archive.splitlines()[:3], [
            "# Memory Archive (not auto-loaded)", "",
            "## Merged 2026-11-04 → [retries](feedback_retries.md)"])
        self.assertIn(POINTER.format(n=3), self.index.splitlines())

    def test_missing_pointer_is_appended(self):
        self.write(INDEX.format(pointer="").rstrip("\n") + "\n", ARCHIVE)
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.index.splitlines()[-1], POINTER.format(n=4))

    def test_pick_selects_one_of_several(self):
        other = proposal(sources=["user_gamma.md", "feedback_delta.md"], name="x",
                         file="feedback_x.md", index_line="- [x](feedback_x.md) — x",
                         body=BODY + "user_gamma.md\n")
        self.proposals(other, proposal())
        r = self.run_cli("--pick", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.merged.is_file())
        self.assertFalse((self.mem / "feedback_x.md").exists())

    def test_reports_the_pointer_and_runs_the_index_check(self):
        r = self.run_cli()
        self.assertIn("verified: lossless; pointer = 4", r.stdout)
        self.assertIn("OK: the whole index loads", r.stdout)


class BackupTest(Fixture):

    def test_both_files_backed_up_before_change(self):
        self.proposals(proposal())
        before_i, before_a = self.index, self.archive
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [snap] = list(self.backups.iterdir())
        self.assertEqual((snap / "MEMORY.md").read_text(encoding="utf-8"), before_i)
        self.assertEqual((snap / "MEMORY-ARCHIVE.md").read_text(encoding="utf-8"), before_a)


class DryRunTest(Fixture):

    def test_prints_the_full_diff_and_writes_nothing(self):
        self.proposals(proposal())
        before = self.snapshot()
        r = self.run_cli("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.backups.exists())
        out = r.stdout.splitlines()
        self.assertIn("    - feedback_beta.md", out)        # new file, frontmatter
        self.assertIn("+" + INDEX_LINE, out)                # index line added
        for line in (ALPHA, BETA, DELTA):
            self.assertIn("-" + line, out)                  # removed from the index
            self.assertIn("+" + line, out)                  # added to the archive
        self.assertIn("+## Merged 2026-11-04 → [retries](feedback_retries.md)", out)
        self.assertIn("dry run: nothing written", out)


# ------------------------------------------------------------------ AC2 refuse

class RefusesTest(Fixture):
    """Every refusal: exit 2, a reason on stderr, nothing written, no backup."""

    def assertRefused(self, r, needle):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("REFUSED", r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse(self.backups.exists())

    def setUp(self):
        super().setUp()
        self.before = self.snapshot()

    def refuse(self, needle, *extra, **over):
        self.proposals(proposal(**over))
        self.assertRefused(self.run_cli(*extra), needle)

    def test_source_matches_no_index_line(self):
        (self.mem / "feedback_nope.md").write_text("x", encoding="utf-8")
        self.before = self.snapshot()
        self.refuse("feedback_nope.md",
                    sources=["feedback_alpha.md", "feedback_nope.md"],
                    body=BODY + "feedback_nope.md\n")
        r = self.run_cli()
        self.assertNotIn("archived only", r.stderr)

    def test_source_matches_two_index_lines(self):
        self.write(INDEX.format(pointer=POINTER.format(n=1)).replace(
            GAMMA, GAMMA + "\n- [alpha again](feedback_alpha.md) — duplicate"), ARCHIVE)
        self.before = self.snapshot()
        self.refuse("matches 2 index lines")

    def test_source_already_archived_only(self):
        self.refuse("archived",
                    sources=["feedback_alpha.md", "reference_old.md"],
                    body=BODY + "reference_old.md\n")

    def test_source_file_missing(self):
        (self.mem / "feedback_beta.md").unlink()
        self.before = self.snapshot()
        self.refuse("feedback_beta.md")

    def test_merged_file_already_exists(self):
        self.merged.write_text("x", encoding="utf-8")
        self.before = self.snapshot()
        self.refuse("feedback_retries.md")

    def test_merged_file_already_linked(self):
        self.write(INDEX.format(pointer=POINTER.format(n=1)),
                   ARCHIVE + "- [r](feedback_retries.md) — once\n")
        self.before = self.snapshot()
        self.refuse("feedback_retries.md")

    def test_merged_name_already_in_index(self):
        self.refuse("'gamma'", name="gamma",
                    index_line="- [gamma](feedback_retries.md) — clash")

    def test_merged_name_already_in_archive(self):
        self.refuse("'old'", name="old", index_line="- [old](feedback_retries.md) — clash")

    def test_fewer_than_two_sources(self):
        self.refuse("at least 2", sources=["feedback_alpha.md"])

    def test_source_given_twice(self):
        self.refuse("more than once", sources=["feedback_alpha.md", "feedback_alpha.md"])

    def test_body_does_not_name_every_source(self):
        self.refuse("feedback_delta.md", body=BODY.replace("feedback_delta.md", "the third"))

    def test_source_is_a_path_not_a_file_name(self):
        self.refuse("sources", sources=["feedback_alpha.md", "../feedback_beta.md"])

    def test_source_is_the_index_itself(self):
        self.refuse("MEMORY.md", sources=["feedback_alpha.md", "MEMORY.md"],
                    body=BODY + "MEMORY.md\n")

    # --- schema

    def test_missing_key(self):
        self.refuse("description", description=None)

    def test_unknown_key(self):
        self.refuse("surprise", surprise="x")

    def test_wrong_value_type(self):
        self.refuse("name", name=["retries"])

    def test_sources_not_a_list(self):
        self.refuse("sources", sources="feedback_alpha.md")

    def test_empty_body(self):
        self.refuse("body", body="  \n")

    def test_newline_in_description(self):
        self.refuse("description", description="two\nlines")

    def test_newline_in_name(self):
        self.refuse("name", name="re\ntries")

    def test_bracket_in_name(self):
        self.refuse("`name` must be", name="re]tries",
                    index_line="- [re]tries](feedback_retries.md) — x")

    def test_blank_name(self):
        self.refuse("`name` must be", name="  ", index_line="- [  ](feedback_retries.md) — x")

    def test_unknown_type(self):
        self.refuse("type", type="lesson")

    def test_file_name_not_type_prefixed(self):
        self.refuse("file", file="project_retries.md",
                    index_line="- [retries](project_retries.md) — x")

    def test_file_name_is_a_path(self):
        self.refuse("file", file="sub/feedback_retries.md",
                    index_line="- [retries](sub/feedback_retries.md) — x")

    def test_index_line_over_150_chars(self):
        self.refuse("150", index_line="- [retries](feedback_retries.md) — " + "x" * 120)

    def test_index_line_exactly_150_chars_is_accepted(self):
        line = "- [retries](feedback_retries.md) — "
        line += "x" * (150 - len(line))
        self.proposals(proposal(index_line=line))
        r = self.run_cli("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_index_line_not_in_entry_form(self):
        self.refuse("index_line", index_line="* [retries](feedback_retries.md) - hook")

    def test_index_line_without_hook(self):
        self.refuse("index_line", index_line="- [retries](feedback_retries.md) — ")

    def test_index_line_names_another_entry(self):
        self.refuse("index_line", index_line="- [other](feedback_retries.md) — hook")

    def test_index_line_links_another_file(self):
        self.refuse("index_line", index_line="- [retries](feedback_other.md) — hook")

    def test_merged_file_fails_the_shape_check(self):
        self.refuse("How to apply", body=BODY.replace("**How to apply:**", "Apply:"))

    def test_not_json(self):
        self.proposals(raw="{not json")
        self.assertRefused(self.run_cli(), "proposal")

    def test_top_level_not_an_object(self):
        self.proposals(raw="[]")
        self.assertRefused(self.run_cli(), "proposals")

    def test_proposals_not_a_list(self):
        self.proposals(raw='{"proposals": {}}')
        self.assertRefused(self.run_cli(), "proposals")

    def test_proposal_not_an_object(self):
        self.proposals(raw='{"proposals": ["x"]}')
        self.assertRefused(self.run_cli(), "object")

    def test_empty_proposals(self):
        self.proposals()
        self.assertRefused(self.run_cli(), "no proposals")

    def test_several_proposals_without_pick(self):
        self.proposals(proposal(), proposal())
        self.assertRefused(self.run_cli(), "--pick")

    def test_pick_out_of_range(self):
        self.proposals(proposal())
        self.assertRefused(self.run_cli("--pick", "1"), "out of range 0..0")

    def test_negative_pick(self):
        self.proposals(proposal())
        self.assertRefused(self.run_cli("--pick", "-1"), "--pick")

    def test_two_pointer_lines(self):
        self.write(INDEX.format(pointer=POINTER.format(n=1)) + POINTER.format(n=1) + "\n",
                   ARCHIVE)
        self.before = self.snapshot()
        self.refuse("pointer lines")

    def test_required_flags(self):
        for drop in ("--memory-dir", "--proposal"):
            argv = self.args()
            i = argv.index(drop)
            del argv[i:i + 2]
            r = subprocess.run([sys.executable, str(SCRIPT), *argv],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, drop)
            self.assertIn(drop, r.stderr)

    def test_proposal_file_missing(self):
        self.assertRefused(self.run_cli(), "proposal")

    def test_no_index(self):
        (self.mem / "MEMORY.md").unlink()
        self.before = self.snapshot()
        self.refuse("MEMORY.md")

    def test_backup_dir_inside_memory_dir(self):
        self.proposals(proposal())
        r = subprocess.run([sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
                            "--backup-dir", str(self.mem / "bak"),
                            "--proposal", str(self.prop_path)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("inside the memory dir", r.stderr)
        self.assertEqual(self.snapshot(), self.before)

    def test_reports_every_problem_at_once(self):
        self.proposals(proposal(type="lesson", index_line="nope"))
        r = self.run_cli()
        self.assertIn("type", r.stderr)
        self.assertIn("index_line", r.stderr)


class ValidateIsTheGuardTest(Fixture):
    """The proposer guards model output with this same function."""

    def test_valid_proposal_has_no_problems(self):
        self.assertEqual(mod.validate(proposal(), self.mem), [])

    def test_problems_are_listed(self):
        problems = mod.validate(proposal(sources=["feedback_alpha.md"]), self.mem)
        self.assertTrue(any("at least 2" in p for p in problems), problems)

    def test_validate_never_writes(self):
        before = self.snapshot()
        mod.validate(proposal(), self.mem)
        self.assertEqual(self.snapshot(), before)


# ------------------------------------------------------------ verify + restore

class VerifyAndRestoreTest(Fixture):

    def setUp(self):
        super().setUp()
        self.proposals(proposal())
        self.before = self.snapshot()

    def apply_with(self, damage):
        return mod.main(self.args(), after_write=damage)

    def assertRestored(self, rc):
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(), self.before)

    def test_line_lost_after_write_restores_and_removes_merged_file(self):
        def lose(mem: Path):
            p = mem / "MEMORY-ARCHIVE.md"
            p.write_text(p.read_text(encoding="utf-8").replace(BETA + "\n", ""),
                         encoding="utf-8")
        self.assertRestored(self.apply_with(lose))

    def test_link_dropped_after_write_restores(self):
        def reword(mem: Path):
            p = mem / "MEMORY-ARCHIVE.md"
            p.write_text(p.read_text(encoding="utf-8").replace(
                "](reference_old.md)", "](reference_gone.md)"), encoding="utf-8")
        self.assertRestored(self.apply_with(reword))

    def test_merged_file_changed_after_write_restores(self):
        def edit(mem: Path):
            p = mem / "feedback_retries.md"
            p.write_text(p.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
        self.assertRestored(self.apply_with(edit))

    def test_merged_file_removed_after_write_restores(self):
        self.assertRestored(self.apply_with(
            lambda mem: (mem / "feedback_retries.md").unlink()))

    def test_index_line_missing_after_write_restores(self):
        def drop(mem: Path):
            p = mem / "MEMORY.md"
            p.write_text(p.read_text(encoding="utf-8").replace(INDEX_LINE + "\n", ""),
                         encoding="utf-8")
        self.assertRestored(self.apply_with(drop))

    def test_index_line_doubled_after_write_restores(self):
        def double(mem: Path):
            p = mem / "MEMORY.md"
            p.write_text(p.read_text(encoding="utf-8") + INDEX_LINE + "\n",
                         encoding="utf-8")
        self.assertRestored(self.apply_with(double))

    def test_source_line_left_in_index_restores(self):
        def keep(mem: Path):
            p = mem / "MEMORY.md"
            p.write_text(p.read_text(encoding="utf-8") + BETA + "\n", encoding="utf-8")
        self.assertRestored(self.apply_with(keep))

    def test_dangling_index_link_restores(self):
        before_i, before_a = self.index, self.archive
        rc = self.apply_with(lambda mem: (mem / "user_gamma.md").unlink())
        self.assertEqual(rc, 3)
        self.assertEqual((self.index, self.archive), (before_i, before_a))
        self.assertFalse(self.merged.exists())

    def test_restore_without_prior_archive_removes_the_new_archive(self):
        (self.mem / "MEMORY-ARCHIVE.md").unlink()
        self.write(INDEX.format(pointer=POINTER.format(n=0)), None)
        self.before = self.snapshot()

        def lose(mem: Path):
            p = mem / "MEMORY.md"
            p.write_text(p.read_text(encoding="utf-8").replace(GAMMA + "\n", ""),
                         encoding="utf-8")
        self.assertRestored(self.apply_with(lose))

    def test_restore_prints_the_problems(self):
        r = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util,sys,pathlib;"
             f"s=importlib.util.spec_from_file_location('m',{str(SCRIPT)!r});"
             "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
             "sys.exit(m.main(sys.argv[1:],after_write=lambda d:(d/'feedback_retries.md').unlink()))",
             *self.args()], capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("VERIFY FAILED", r.stderr)
        self.assertIn("feedback_retries.md", r.stderr)


class RunsIndexCheckTest(Fixture):

    def test_check_failure_is_exit_1_and_the_merge_is_kept(self):
        long = "- [long](user_gamma.md) — " + "x" * 220
        self.write(INDEX.format(pointer=POINTER.format(n=1)) + long + "\n", ARCHIVE)
        self.proposals(proposal())
        r = self.run_cli()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL", r.stdout)
        self.assertIn(INDEX_LINE, self.index.splitlines())
        self.assertTrue(self.merged.is_file())


if __name__ == "__main__":
    unittest.main()
