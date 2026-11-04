#!/usr/bin/env python3
"""Tests for archive-memory-lines.py — the Compact step of memory-maintenance.

Compaction moves whole index lines from MEMORY.md into MEMORY-ARCHIVE.md.
Every way it has been done by hand so far had the same failure modes, which
are what these tests pin:

  * a name matching more than one line (a prefix, a duplicate) silently
    archives the wrong entry, or two
  * a line or a link vanishes between the two files and nobody notices,
    because the check after compaction only measures size
  * the "N more hooks" pointer is hand-edited and drifts from what the
    archive actually holds
  * a half-written result is left behind when something goes wrong

Most tests drive the shipped script as a subprocess (the artifact, not a
transcription of it). The one fault that cannot be produced from outside —
a line lost *between* write and verify — uses the module's `after_write`
seam.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
SCRIPT = BIN / "archive-memory-lines.py"

_spec = importlib.util.spec_from_file_location("archive_memory_lines", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["archive_memory_lines"] = mod
_spec.loader.exec_module(mod)

POINTER = ("> {n} more hooks in [MEMORY-ARCHIVE.md](MEMORY-ARCHIVE.md) — files "
           "intact, recalled on relevance, not auto-loaded")

INDEX = """# Memory Index

- [alpha](feedback_alpha.md) — first hook
- [alpha-two](feedback_alpha_two.md) — shares a prefix with alpha
- [beta](project_beta.md) — second hook, with an em-dash — and ünïcode
- [gamma](user_gamma.md) — third hook
{pointer}
"""

ARCHIVE = """# Memory Archive (not auto-loaded)

## Archived 2026-11-01 — older
- [old](reference_old.md) — archived before
- [Zeta](reference_zeta.md) — differs from zeta only by case
"""

FILES = ["feedback_alpha.md", "feedback_alpha_two.md", "project_beta.md",
         "user_gamma.md", "reference_old.md", "reference_zeta.md",
         "reference_zeta_lower.md"]


class Fixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.mem = root / "memory"
        self.mem.mkdir()
        self.backups = root / "backups"
        for f in FILES:
            (self.mem / f).write_text("---\nname: x\n---\n", encoding="utf-8")
        self.write(INDEX.format(pointer=POINTER.format(n=2)), ARCHIVE)

    def tearDown(self):
        self._tmp.cleanup()

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

    def run_cli(self, *args, date="2026-11-04"):
        cmd = [sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
               "--backup-dir", str(self.backups), "--date", date, *args]
        return subprocess.run(cmd, capture_output=True, text=True,
                              env={**os.environ, "LC_ALL": "en_US.UTF-8"})


class MovesLinesVerbatimTest(Fixture):

    def test_moves_matching_lines_to_dated_section(self):
        r = self.run_cli("--section", "narrow gotchas", "alpha", "beta")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        alpha = "- [alpha](feedback_alpha.md) — first hook"
        beta = "- [beta](project_beta.md) — second hook, with an em-dash — and ünïcode"
        self.assertNotIn(alpha, self.index.splitlines())
        self.assertNotIn(beta, self.index.splitlines())
        self.assertIn("- [alpha-two](feedback_alpha_two.md) — shares a prefix with alpha",
                      self.index.splitlines())
        tail = self.archive.splitlines()[-3:]
        self.assertEqual(tail, ["## Archived 2026-11-04 — narrow gotchas", alpha, beta])

    def test_existing_archive_content_untouched(self):
        self.run_cli("--section", "s", "gamma")
        self.assertTrue(self.archive.startswith(ARCHIVE))

    def test_same_heading_twice_appends_to_that_section(self):
        self.assertEqual(self.run_cli("--section", "s", "alpha").returncode, 0)
        self.assertEqual(self.run_cli("--section", "s", "gamma").returncode, 0)
        lines = self.archive.splitlines()
        self.assertEqual(lines.count("## Archived 2026-11-04 — s"), 1)
        self.assertEqual(lines[-2:], ["- [alpha](feedback_alpha.md) — first hook",
                                      "- [gamma](user_gamma.md) — third hook"])

    def test_missing_archive_is_created(self):
        (self.mem / "MEMORY-ARCHIVE.md").unlink()
        r = self.run_cli("--section", "s", "gamma")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("- [gamma](user_gamma.md) — third hook", self.archive.splitlines())

    def test_dry_run_writes_nothing(self):
        before = (self.index, self.archive)
        r = self.run_cli("--dry-run", "--section", "s", "alpha")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("- [alpha](feedback_alpha.md) — first hook", r.stdout)
        self.assertEqual((self.index, self.archive), before)
        self.assertFalse(self.backups.exists())


class BackupTest(Fixture):

    def test_both_files_backed_up_byte_identical_before_change(self):
        before_i, before_a = self.index, self.archive
        r = self.run_cli("--section", "s", "alpha")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        snaps = list(self.backups.iterdir())
        self.assertEqual(len(snaps), 1)
        self.assertEqual((snaps[0] / "MEMORY.md").read_text(encoding="utf-8"), before_i)
        self.assertEqual((snaps[0] / "MEMORY-ARCHIVE.md").read_text(encoding="utf-8"),
                         before_a)

    def test_backup_dir_inside_memory_dir_refused(self):
        before = (self.index, self.archive)
        r = subprocess.run([sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
                            "--backup-dir", str(self.mem / "bak"),
                            "--section", "s", "alpha"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertEqual((self.index, self.archive), before)


class RefusesAmbiguityTest(Fixture):
    """Refusal happens before anything is written — including the backup."""

    def assertRefused(self, r, needle):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertEqual(self.index, INDEX.format(pointer=POINTER.format(n=2)))
        self.assertEqual(self.archive, ARCHIVE)
        self.assertFalse(self.backups.exists())

    def test_zero_matches(self):
        self.assertRefused(self.run_cli("--section", "s", "alpha", "nope"), "nope")

    def test_prefix_is_not_a_match(self):
        self.assertRefused(self.run_cli("--section", "s", "alph"), "alph")

    def test_more_than_one_match(self):
        dup = INDEX.format(pointer=POINTER.format(n=2)).replace(
            "- [gamma]", "- [beta](project_beta.md) — duplicate entry\n- [gamma]")
        self.write(dup, ARCHIVE)
        r = self.run_cli("--section", "s", "beta")
        self.assertEqual(r.returncode, 2)
        self.assertIn("2", r.stderr)
        self.assertEqual(self.index, dup)

    def test_name_given_twice(self):
        self.assertRefused(self.run_cli("--section", "s", "alpha", "alpha"), "alpha")

    def test_pointer_line_cannot_be_archived(self):
        self.assertRefused(self.run_cli("--section", "s", "MEMORY-ARCHIVE.md"),
                           "MEMORY-ARCHIVE.md")

    def test_name_only_in_archive_is_zero_matches(self):
        self.assertRefused(self.run_cli("--section", "s", "old"), "old")


class PointerRecountTest(Fixture):

    def pointer_count(self) -> int:
        [line] = [l for l in self.index.splitlines() if "more hooks in" in l]
        return int(line.split()[1])

    def test_recount_after_archive(self):
        self.run_cli("--section", "s", "alpha", "beta")
        self.assertEqual(self.pointer_count(), 4)
        self.assertIn(POINTER.format(n=4), self.index.splitlines())

    def test_stale_pointer_is_corrected_not_incremented(self):
        self.write(INDEX.format(pointer=POINTER.format(n=97)), ARCHIVE)
        self.run_cli("--section", "s", "alpha")
        self.assertEqual(self.pointer_count(), 3)

    def test_link_in_both_files_is_not_archived_only(self):
        self.write(INDEX.format(pointer=POINTER.format(n=2)),
                   ARCHIVE + "- [gamma](user_gamma.md) — older wording of gamma\n")
        self.run_cli("--section", "s", "alpha")
        # archive: old, zeta, gamma, alpha; gamma still indexed -> 3
        self.assertEqual(self.pointer_count(), 3)

    def test_case_variants_are_distinct_like_lc_all_c(self):
        # A collating `sort -u` can fold Zeta/zeta; LC_ALL=C (and this tool)
        # must not, or the count undercounts.
        self.write(INDEX.format(pointer=POINTER.format(n=2)),
                   ARCHIVE + "- [zeta](reference_Zeta.md) — upper-case file\n"
                             "- [zeta](reference_zeta.md) — same link twice\n")
        self.run_cli("--section", "s", "alpha")
        self.assertEqual(self.pointer_count(), 4)  # old, zeta, Zeta, alpha

    def test_matches_the_shell_pipeline(self):
        self.run_cli("--section", "s", "alpha", "gamma")
        pipe = ("grep -oE '\\]\\([^)]+\\.md\\)' MEMORY-ARCHIVE.md | sort -u > a; "
                "grep -oE '\\]\\([^)]+\\.md\\)' MEMORY.md | sort -u > i; "
                "comm -23 a i | wc -l")
        out = subprocess.run(["bash", "-c", pipe], cwd=self.mem, capture_output=True,
                             text=True, env={**os.environ, "LC_ALL": "C"}).stdout
        self.assertEqual(self.pointer_count(), int(out.strip()))

    def test_missing_pointer_is_appended(self):
        self.write(INDEX.format(pointer="").rstrip("\n") + "\n", ARCHIVE)
        r = self.run_cli("--section", "s", "alpha")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.index.splitlines()[-1], POINTER.format(n=3))


class VerifyAndRestoreTest(Fixture):

    def test_dangling_index_link_restores_originals(self):
        before = (self.index, self.archive)
        (self.mem / "user_gamma.md").unlink()
        r = self.run_cli("--section", "s", "alpha")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("user_gamma.md", r.stderr)
        self.assertEqual((self.index, self.archive), before)

    def test_line_lost_after_write_restores_originals(self):
        before = (self.index, self.archive)

        def lose_a_line(mem: Path):
            p = mem / "MEMORY-ARCHIVE.md"
            p.write_text(p.read_text(encoding="utf-8").replace(
                "- [old](reference_old.md) — archived before\n", ""), encoding="utf-8")

        rc = mod.main(["--memory-dir", str(self.mem), "--backup-dir", str(self.backups),
                       "--section", "s", "alpha"], after_write=lose_a_line)
        self.assertEqual(rc, 3)
        self.assertEqual((self.index, self.archive), before)

    def test_link_dropped_after_write_restores_originals(self):
        before = (self.index, self.archive)

        def reword_link(mem: Path):
            p = mem / "MEMORY-ARCHIVE.md"
            p.write_text(p.read_text(encoding="utf-8").replace(
                "](feedback_alpha.md)", "](feedback_alpha_renamed.md)"), encoding="utf-8")

        rc = mod.main(["--memory-dir", str(self.mem), "--backup-dir", str(self.backups),
                       "--section", "s", "alpha"], after_write=reword_link)
        self.assertEqual(rc, 3)
        self.assertEqual((self.index, self.archive), before)

    def test_verify_accepts_an_honest_move(self):
        old_i = INDEX.format(pointer=POINTER.format(n=2))
        line = "- [alpha](feedback_alpha.md) — first hook"
        new_i = old_i.replace(line + "\n", "").replace(POINTER.format(n=2), POINTER.format(n=3))
        new_a = ARCHIVE + "\n## Archived x — s\n" + line + "\n"
        self.assertEqual(mod.verify(old_i, ARCHIVE, new_i, new_a, self.mem, [line]), [])


class RunsIndexCheckTest(Fixture):

    def test_check_runs_and_passes(self):
        r = self.run_cli("--section", "s", "alpha")
        self.assertEqual(r.returncode, 0)
        self.assertIn("OK: the whole index loads", r.stdout)

    def test_check_failure_is_reported_but_archive_kept(self):
        long = "- [long](user_gamma.md) — " + "x" * 220
        self.write(INDEX.format(pointer=POINTER.format(n=2)) + long + "\n", ARCHIVE)
        r = self.run_cli("--section", "s", "alpha")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL", r.stdout)
        self.assertNotIn("- [alpha](feedback_alpha.md) — first hook",
                         self.index.splitlines())


if __name__ == "__main__":
    unittest.main()
