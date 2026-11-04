#!/usr/bin/env python3
"""Tests for memory-audit.py, the report-only audit of a Claude Code memory dir.

It answers three questions no other tool answers (homelab#1928):

  * which topic files have no line in MEMORY.md or MEMORY-ARCHIVE.md, which
    lines point at a file that isn't there, and which files are stray
    (LIVE / ORPHAN / UNDECIDED)
  * which index entries no session has used in N days, read from the
    session transcripts, oldest first, named the way archive-memory-lines.py
    takes them
  * and it never writes to the memory dir

The transcript records come from tests/fixtures/memory_audit/*.jsonl. They are
hand-redacted copies of real records from ~/.claude/projects/*/*.jsonl
(claude-code 2.1.282). The key set and nesting are unchanged, and every value
is replaced. The tests change only `file_path`/`filename` and `timestamp`, so
the parser is tested against the shape the harness really writes, not against
a guessed shape.

The tests drive the shipped script as a subprocess: the artifact, not a
transcription of it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE.parent / "claude" / "memory-maintenance" / "bin"
SCRIPT = BIN / "memory-audit.py"
ARCHIVER = BIN / "archive-memory-lines.py"
FIX = HERE / "fixtures" / "memory_audit"

READ = json.loads((FIX / "read.jsonl").read_text(encoding="utf-8"))
ATTACH = json.loads((FIX / "compaction-attachment.jsonl").read_text(encoding="utf-8"))

NOW = "2026-11-04T12:00:00Z"
POINTER = ("> {n} more hooks in [MEMORY-ARCHIVE.md](MEMORY-ARCHIVE.md) — files "
           "intact, recalled on relevance, not auto-loaded")


def read_record(path: str, ts: str, tool: str = "Read", cwd: str | None = None) -> dict:
    r = copy.deepcopy(READ)
    use = r["message"]["content"][0]
    use["name"] = tool
    use["input"] = {"file_path": path}
    r["wireToolInputs"] = {use["id"]: {"file_path": path}}
    r["timestamp"] = ts
    if cwd is not None:
        r["cwd"] = cwd
    return r


def attach_record(path: str, ts: str) -> dict:
    r = copy.deepcopy(ATTACH)
    r["attachment"]["filename"] = path
    r["attachment"]["content"]["file"]["filePath"] = path
    r["timestamp"] = ts
    return r


def tree_digest(root: Path) -> dict[str, tuple[str, int]]:
    """Every file under root (.git included) → (sha256, mtime_ns)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (hashlib.sha256(p.read_bytes()).hexdigest(),
                                             st.st_mtime_ns)
        elif p.is_dir():
            out[str(p.relative_to(root)) + "/"] = ("dir", 0)
    return out


class Fixture(unittest.TestCase):
    """A projects dir with one project's memory and its transcripts."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.projects = self.root / "projects"
        self.proj = self.projects / "-home-user-Code"
        self.mem = self.proj / "memory"
        self.mem.mkdir(parents=True)
        self.transcript = self.proj / "00000000-0000-4000-8000-00000000aaaa.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def files(self, *names):
        for n in names:
            (self.mem / n).write_text(f"---\nname: {n}\n---\nbody\n", encoding="utf-8")

    def index(self, *lines, pointer: int | None = None):
        body = ["# Memory Index", "", *lines]
        if pointer is not None:
            body.append(POINTER.format(n=pointer))
        (self.mem / "MEMORY.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    def archive(self, *lines):
        body = ["# Memory Archive (not auto-loaded)", "", "## Archived 2026-11-01 — x", *lines]
        (self.mem / "MEMORY-ARCHIVE.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    def records(self, *recs, path: Path | None = None, raw: list[str] = ()):
        path = path or self.transcript
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for line in raw:
                f.write(line + "\n")
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def m(self, name: str) -> str:
        return str(self.mem / name)

    def run_cli(self, *args, now=NOW, days="30"):
        cmd = [sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
               "--projects-dir", str(self.projects), "--now", now, "--days", days, *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def report(self, *args, **kw) -> dict:
        r = self.run_cli("--json", *args, **kw)
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        return json.loads(r.stdout)

    def labels(self, rep: dict) -> dict[tuple[str, str], str]:
        """(kind, subject) → label. kind is file / index / archive."""
        return {(i["kind"], i["subject"]): i["label"] for i in rep["orphans"]}


# --------------------------------------------------------------------- AC1

class OrphanClassificationTest(Fixture):

    def setUp(self):
        super().setUp()
        self.files("feedback_live.md", "project_archived.md", "feedback_orphan.md",
                   "notes.md", "Feedback_Caps.md", "feedback-dash.md")
        (self.mem / "readme.txt").write_text("not markdown\n", encoding="utf-8")
        self.index("- [live](feedback_live.md) — hook",
                   "- [gone](feedback_gone.md) — file deleted",
                   "- [outside](../elsewhere/feedback_out.md) — outside the dir",
                   "- [sub](sub/feedback_sub.md) — in a subdir",
                   "- [notes](notes.md) — linked stray",
                   pointer=2)
        self.archive("- [archived](project_archived.md) — hook",
                     "- [arch-gone](reference_arch_gone.md) — gone from disk",
                     "- [live](feedback_live.md) — full original hook, still indexed")
        self.rep = self.report()
        self.lab = self.labels(self.rep)

    def test_file_linked_from_index_is_live(self):
        self.assertEqual(self.lab[("file", "feedback_live.md")], "LIVE")

    def test_file_linked_only_from_archive_is_live(self):
        self.assertEqual(self.lab[("file", "project_archived.md")], "LIVE")

    def test_file_with_no_line_is_orphan(self):
        self.assertEqual(self.lab[("file", "feedback_orphan.md")], "ORPHAN")

    def test_index_line_to_missing_file_is_orphan(self):
        self.assertEqual(self.lab[("index", "feedback_gone.md")], "ORPHAN")

    def test_archive_line_to_missing_file_is_orphan(self):
        self.assertEqual(self.lab[("archive", "reference_arch_gone.md")], "ORPHAN")

    def test_lines_to_existing_files_are_live(self):
        self.assertEqual(self.lab[("index", "feedback_live.md")], "LIVE")
        self.assertEqual(self.lab[("archive", "project_archived.md")], "LIVE")
        self.assertEqual(self.lab[("archive", "feedback_live.md")], "LIVE")

    def test_line_pointing_outside_the_dir_is_undecided(self):
        self.assertEqual(self.lab[("index", "../elsewhere/feedback_out.md")], "UNDECIDED")
        self.assertEqual(self.lab[("index", "sub/feedback_sub.md")], "UNDECIDED")

    def test_stray_md_outside_the_pattern_is_undecided(self):
        for stray in ("notes.md", "Feedback_Caps.md", "feedback-dash.md"):
            self.assertEqual(self.lab[("file", stray)], "UNDECIDED", stray)

    def test_stray_is_undecided_even_when_linked(self):
        self.assertEqual(self.lab[("file", "notes.md")], "UNDECIDED")

    def test_all_four_types_match_the_pattern(self):
        self.files("user_a.md", "reference_b.md", "project_c2.md")
        lab = self.labels(self.report())
        for n in ("user_a.md", "reference_b.md", "project_c2.md"):
            self.assertEqual(lab[("file", n)], "ORPHAN", n)

    def test_unknown_type_prefix_is_stray(self):
        self.files("diary_x.md")
        self.assertEqual(self.labels(self.report())[("file", "diary_x.md")], "UNDECIDED")

    def test_index_and_archive_and_non_md_are_not_classified_as_files(self):
        subjects = {s for k, s in self.lab if k == "file"}
        self.assertNotIn("MEMORY.md", subjects)
        self.assertNotIn("MEMORY-ARCHIVE.md", subjects)
        self.assertNotIn("readme.txt", subjects)

    def test_pointer_link_is_not_a_line_finding(self):
        self.assertNotIn(("index", "MEMORY-ARCHIVE.md"), self.lab)

    def test_git_dir_is_ignored(self):
        (self.mem / ".git").mkdir()
        (self.mem / ".git" / "feedback_in_git.md").write_text("x", encoding="utf-8")
        lab = self.labels(self.report())
        self.assertFalse(any("in_git" in s for _, s in lab))

    def test_every_item_carries_a_reason_and_line_number_for_lines(self):
        for item in self.rep["orphans"]:
            self.assertTrue(item["reason"], item)
            if item["kind"] in ("index", "archive"):
                self.assertIsInstance(item["line"], int, item)
        gone = next(i for i in self.rep["orphans"] if i["subject"] == "feedback_gone.md")
        self.assertEqual(gone["line"], 4)

    def test_counts_by_label(self):
        c = self.rep["counts"]
        want = {}
        for i in self.rep["orphans"]:
            want[i["label"]] = want.get(i["label"], 0) + 1
        self.assertEqual({k: c[k] for k in ("LIVE", "ORPHAN", "UNDECIDED")},
                         {k: want.get(k, 0) for k in ("LIVE", "ORPHAN", "UNDECIDED")})
        # files: live, archived | lines: live, notes, archived, live (archive)
        self.assertEqual(c["LIVE"], 6)
        # file feedback_orphan | lines feedback_gone, reference_arch_gone
        self.assertEqual(c["ORPHAN"], 3)
        # files notes, Feedback_Caps, feedback-dash | lines ../elsewhere, sub/
        self.assertEqual(c["UNDECIDED"], 5)

    def test_text_output_names_the_findings(self):
        out = self.run_cli().stdout
        self.assertIn("ORPHAN", out)
        self.assertIn("feedback_orphan.md", out)
        self.assertIn("UNDECIDED", out)

    def test_text_lists_only_non_live_items_with_their_place(self):
        lines = self.run_cli().stdout.splitlines()
        self.assertFalse([l for l in lines if l.lstrip().startswith("LIVE ")], lines)
        self.assertNotIn("None", "\n".join(lines))
        self.assertTrue(any("index:4" in l and "feedback_gone.md" in l for l in lines), lines)

    def test_reasons_say_where_a_live_file_is_linked(self):
        r = {(i["kind"], i["subject"]): i["reason"] for i in self.rep["orphans"]}
        self.assertEqual(r[("file", "feedback_live.md")], "in the index")
        self.assertEqual(r[("file", "project_archived.md")], "in the archive only")
        self.assertEqual(r[("file", "feedback_orphan.md")], "no line in the index or the archive")
        self.assertEqual(r[("file", "notes.md")], "stray: outside the type_name.md pattern, linked")
        self.assertEqual(r[("file", "feedback-dash.md")],
                         "stray: outside the type_name.md pattern, no line")
        self.assertEqual(r[("index", "feedback_gone.md")], "file does not exist")


# --------------------------------------------------------------------- AC2

class UnusedCandidatesTest(Fixture):

    def setUp(self):
        super().setUp()
        self.files("feedback_recent.md", "feedback_old.md", "feedback_never.md",
                   "project_archived.md", "feedback_also_never.md")
        self.index("- [recent](feedback_recent.md) — read 2 days ago",
                   "- [old](feedback_old.md) — read 40 days ago",
                   "- [never](feedback_never.md) — never read",
                   "- [also never](feedback_also_never.md) — name with a space",
                   pointer=1)
        self.archive("- [archived](project_archived.md) — not an index entry")

    def names(self, rep=None, **kw) -> list[str]:
        rep = rep or self.report(**kw)
        return [c["name"] for c in rep["unused"]]

    def test_read_within_n_days_is_not_a_candidate(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-02T00:00:00Z"))
        self.assertNotIn("recent", self.names())

    def test_read_before_n_days_is_a_candidate(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-09-25T00:00:00Z"))
        self.assertIn("old", self.names())

    def test_boundary_exactly_n_days_ago_counts_as_used(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-10-05T12:00:00Z"))
        self.assertNotIn("old", self.names())
        self.records(read_record(self.m("feedback_recent.md"), "2026-10-05T11:59:59Z"))
        self.assertIn("recent", self.names())

    def test_never_read_is_a_candidate(self):
        self.assertIn("never", self.names())

    def test_archived_entries_are_never_candidates(self):
        self.assertNotIn("archived", self.names())

    def test_oldest_first_never_read_before_read_long_ago(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-09-25T00:00:00Z"),
                     read_record(self.m("feedback_recent.md"), "2026-09-01T00:00:00Z"))
        self.assertEqual(self.names(), ["also never", "never", "recent", "old"])

    def test_latest_read_wins(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_old.md"), "2026-09-01T00:00:00Z"))
        self.assertNotIn("old", self.names())

    def test_days_is_configurable(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-10-25T00:00:00Z"))
        self.assertNotIn("old", self.names(days="30"))
        self.assertIn("old", self.names(days="7"))

    def test_candidate_carries_last_read_and_file(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-09-25T00:00:00Z"))
        rep = self.report()
        old = next(c for c in rep["unused"] if c["name"] == "old")
        self.assertEqual(old["file"], "feedback_old.md")
        self.assertEqual(old["last_used"], "2026-09-25T00:00:00Z")
        never = next(c for c in rep["unused"] if c["name"] == "never")
        self.assertIsNone(never["last_used"])

    def test_read_of_same_name_in_another_memory_dir_does_not_count(self):
        other = self.projects / "-other" / "memory" / "feedback_recent.md"
        self.records(read_record(str(other), "2026-11-03T00:00:00Z"))
        self.assertIn("recent", self.names())

    def test_relative_path_resolves_against_record_cwd(self):
        self.records(read_record("memory/feedback_recent.md", "2026-11-03T00:00:00Z",
                                 cwd=str(self.proj)))
        self.assertNotIn("recent", self.names())

    def test_compaction_reattachment_counts_as_use(self):
        self.records(attach_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z"))
        self.assertNotIn("recent", self.names())

    def test_write_and_edit_count_as_use(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z",
                                 tool="Write"),
                     read_record(self.m("feedback_old.md"), "2026-11-03T00:00:00Z",
                                 tool="Edit"))
        names = self.names()
        self.assertNotIn("recent", names)
        self.assertNotIn("old", names)

    def test_other_tools_do_not_count(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z",
                                 tool="Grep"))
        self.assertIn("recent", self.names())

    def test_other_attachment_types_do_not_count(self):
        rec = attach_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z")
        rec["attachment"]["type"] = "edited_text_file"
        self.records(rec)
        self.assertIn("recent", self.names())

    def test_subagent_transcripts_are_read(self):
        sub = self.proj / "00000000-0000-4000-8000-00000000aaaa" / "subagents" / "a.jsonl"
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z"),
                     path=sub)
        self.assertNotIn("recent", self.names())

    def test_other_projects_transcripts_are_read(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z"),
                     path=self.projects / "-home-user-Code-other" / "s.jsonl")
        self.assertNotIn("recent", self.names())

    def test_junk_lines_are_skipped_not_fatal(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z"),
                     raw=["not json", "[]", "{}", '{"type":"assistant"}',
                          '{"type":"assistant","message":{"content":"a string"}}',
                          '{"type":"assistant","message":{"content":[1,"x",{"type":"tool_use"}]}}',
                          '{"type":"assistant","timestamp":"2026-11-03T00:00:00Z",'
                          '"message":{"content":"a string"}}',
                          '{"type":"assistant","timestamp":"bad","message":{"content":'
                          '[{"type":"tool_use","name":"Read","input":{"file_path":"'
                          + self.m("feedback_recent.md") + '"}}]}}',
                          '{"type":"attachment","attachment":null}'])
        rep = self.report()
        self.assertNotIn("recent", self.names(rep))
        self.assertIn("old", self.names(rep))
        # "not json", "[]", and the Read whose timestamp won't parse
        self.assertEqual(rep["transcripts"]["skipped_lines"], 3)

    def test_record_without_timestamp_after_a_timed_one(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z"),
                     {"type": "user", "message": {"content": "no timestamp"}})
        rep = self.report()
        self.assertEqual(rep["transcripts"]["oldest"], "2026-11-03T00:00:00Z")
        self.assertEqual(rep["transcripts"]["skipped_lines"], 0)

    def test_naive_timestamp_is_read_as_utc(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00"),
                     read_record(self.m("feedback_old.md"), "2026-11-03T00:00:00Z"))
        rep = self.report()
        self.assertNotIn("recent", self.names(rep))
        self.assertEqual(rep["transcripts"]["oldest"], "2026-11-03T00:00:00Z")

    def test_relative_path_without_cwd_does_not_count(self):
        rec = read_record("feedback_recent.md", "2026-11-03T00:00:00Z")
        del rec["cwd"]
        self.records(rec)
        self.assertIn("recent", self.names())

    def test_attachment_key_on_a_non_attachment_record_does_not_count(self):
        rec = attach_record(self.m("feedback_recent.md"), "2026-11-03T00:00:00Z")
        rec["type"] = "user"
        self.records(rec)
        self.assertIn("recent", self.names())

    def test_index_entry_with_missing_file_is_an_orphan_not_a_candidate(self):
        (self.mem / "feedback_never.md").unlink()
        rep = self.report()
        self.assertNotIn("never", self.names(rep))
        self.assertEqual(self.labels(rep)[("index", "feedback_never.md")], "ORPHAN")

    def test_window_exactly_n_days_is_not_short(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-10-05T12:00:00Z"))
        self.assertFalse(self.report()["transcripts"]["window_short"])

    def test_json_keeps_unicode_readable(self):
        r = self.run_cli("--json")
        self.assertIn('"also never"', r.stdout)
        self.files("feedback_u.md")
        self.index("- [ünï](feedback_u.md) — x")
        self.assertIn('"ünï"', self.run_cli("--json").stdout)

    def test_window_reports_the_oldest_record(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-01T00:00:00Z"),
                     read_record(self.m("feedback_old.md"), "2026-10-20T06:00:00Z"))
        w = self.report()["transcripts"]
        self.assertEqual(w["files"], 1)
        self.assertEqual(w["oldest"], "2026-10-20T06:00:00Z")
        self.assertTrue(w["window_short"])

    def test_window_covering_n_days_is_not_short(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-09-01T00:00:00Z"))
        self.assertFalse(self.report()["transcripts"]["window_short"])

    def test_short_window_is_warned_in_text(self):
        self.records(read_record(self.m("feedback_recent.md"), "2026-11-01T00:00:00Z"))
        out = self.run_cli().stdout
        self.assertIn("WARN", out)

    def test_full_window_is_not_warned_in_text(self):
        self.records(read_record(self.m("feedback_old.md"), "2026-09-01T00:00:00Z"))
        self.assertNotIn("WARN", self.run_cli().stdout)

    def test_text_with_no_transcripts_says_none(self):
        self.assertIn("oldest record none", self.run_cli().stdout)

    def test_no_transcripts_is_a_short_window(self):
        rep = self.report()
        self.assertEqual(rep["transcripts"]["files"], 0)
        self.assertTrue(rep["transcripts"]["window_short"])


# --------------------------------------------------------------------- AC3

class FeedsTheArchiverTest(Fixture):

    def setUp(self):
        super().setUp()
        self.files("feedback_keep.md", "feedback_drop.md", "project_spaced.md",
                   "feedback_drop_two.md")
        self.index("- [keep](feedback_keep.md) — read yesterday",
                   "- [drop](feedback_drop.md) — never read",
                   "- [drop-two](feedback_drop_two.md) — shares a prefix",
                   "- [spaced ünïcode name](project_spaced.md) — never read",
                   pointer=0)
        self.archive()
        self.records(read_record(self.m("feedback_keep.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_drop_two.md"), "2026-09-01T00:00:00Z"))

    def test_names_only_prints_one_name_per_line(self):
        r = self.run_cli("--names-only")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["drop", "spaced ünïcode name", "drop-two"])

    def test_names_go_to_archiver_dry_run_unchanged(self):
        names = self.run_cli("--names-only").stdout.splitlines()
        r = subprocess.run([sys.executable, str(ARCHIVER), "--memory-dir", str(self.mem),
                            "--backup-dir", str(self.root / "b"), "--section", "unused",
                            "--dry-run", *names], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        moved = [l.strip() for l in r.stdout.splitlines() if l.startswith("  - [")]
        self.assertEqual(moved, ["- [drop](feedback_drop.md) — never read",
                                 "- [spaced ünïcode name](project_spaced.md) — never read",
                                 "- [drop-two](feedback_drop_two.md) — shares a prefix"])

    def test_text_output_prints_a_ready_dry_run_command(self):
        out = self.run_cli().stdout
        self.assertIn("archive-memory-lines.py", out)
        self.assertIn("--dry-run", out)
        self.assertIn("'spaced ünïcode name'", out)

    def test_names_only_with_no_candidates_prints_nothing(self):
        self.records(read_record(self.m("feedback_drop.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_drop_two.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("project_spaced.md"), "2026-11-03T00:00:00Z"))
        r = self.run_cli("--names-only")
        self.assertEqual(r.stdout, "")


# --------------------------------------------------------------------- AC4

class ReadOnlyTest(Fixture):

    def test_memory_dir_is_byte_identical_after_every_mode(self):
        self.files("feedback_a.md", "feedback_orphan.md", "notes.md")
        self.index("- [a](feedback_a.md) — x", "- [gone](feedback_gone.md) — y", pointer=0)
        self.archive("- [b](reference_b.md) — gone")
        (self.mem / ".git").mkdir()
        (self.mem / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.records(read_record(self.m("feedback_a.md"), "2026-11-03T00:00:00Z"))
        before = tree_digest(self.mem)
        for args in ((), ("--json",), ("--names-only",)):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(tree_digest(self.mem), before, args)

    def test_no_bytecode_or_temp_files_appear_in_projects(self):
        self.files("feedback_a.md")
        self.index("- [a](feedback_a.md) — x")
        before = tree_digest(self.projects)
        self.run_cli("--json")
        self.assertEqual(tree_digest(self.projects), before)


# ---------------------------------------------------------- exit codes, CLI

class ExitCodeTest(Fixture):

    def test_clean_is_zero(self):
        self.files("feedback_a.md")
        self.index("- [a](feedback_a.md) — x", pointer=0)
        self.archive()
        self.records(read_record(self.m("feedback_a.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_a.md"), "2026-09-01T00:00:00Z"))
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_cli("--json").returncode, 0)

    def test_orphan_alone_is_one(self):
        self.files("feedback_a.md", "feedback_b.md")
        self.index("- [a](feedback_a.md) — x")
        self.records(read_record(self.m("feedback_a.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_a.md"), "2026-09-01T00:00:00Z"))
        self.assertEqual(self.run_cli().returncode, 1)

    def test_undecided_alone_is_one(self):
        self.files("feedback_a.md", "notes.md")
        self.index("- [a](feedback_a.md) — x", "- [n](notes.md) — stray")
        self.records(read_record(self.m("feedback_a.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("notes.md"), "2026-11-03T00:00:00Z"),
                     read_record(self.m("feedback_a.md"), "2026-09-01T00:00:00Z"))
        self.assertEqual(self.run_cli().returncode, 1)

    def test_unused_alone_is_one(self):
        self.files("feedback_a.md")
        self.index("- [a](feedback_a.md) — x")
        self.records(read_record(self.m("feedback_a.md"), "2026-09-01T00:00:00Z"))
        self.assertEqual(self.run_cli().returncode, 1)

    def test_missing_index_is_two(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertIn("MEMORY.md not found", r.stderr)

    def test_missing_memory_dir_is_two(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--memory-dir",
                            str(self.root / "nope"), "--projects-dir", str(self.projects)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_memory_dir_is_required(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--memory-dir", r.stderr)

    def test_days_must_be_positive(self):
        self.index()
        self.assertEqual(self.run_cli(days="0").returncode, 2)

    def test_one_day_is_allowed(self):
        self.index()
        self.assertEqual(self.run_cli(days="1").returncode, 0)

    def test_runs_on_the_clock_without_now(self):
        self.index()
        cmd = [sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
               "--projects-dir", str(self.projects), "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["now"].startswith("20"))

    def test_bad_now_is_two(self):
        self.index()
        self.assertEqual(self.run_cli(now="yesterday").returncode, 2)

    def test_clean_text_has_no_archive_command(self):
        self.index()
        self.assertNotIn("archive-memory-lines.py", self.run_cli().stdout)

    def test_default_days_is_30(self):
        self.files("feedback_a.md")
        self.index("- [a](feedback_a.md) — x")
        self.records(read_record(self.m("feedback_a.md"), "2026-10-10T00:00:00Z"))
        cmd = [sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
               "--projects-dir", str(self.projects), "--now", NOW, "--json"]
        rep = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
        self.assertEqual(rep["days"], 30)
        self.assertEqual(rep["unused"], [])

    def test_projects_dir_defaults_from_claude_config_dir(self):
        self.files("feedback_a.md")
        self.index("- [a](feedback_a.md) — x")
        self.records(read_record(self.m("feedback_a.md"), "2026-11-03T00:00:00Z"))
        cmd = [sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
               "--now", NOW, "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_CONFIG_DIR": str(self.root)})
        rep = json.loads(r.stdout)
        self.assertEqual(rep["transcripts"]["files"], 1)
        self.assertEqual(rep["unused"], [])

    def test_json_top_level_shape(self):
        self.index()
        rep = self.report()
        self.assertEqual(set(rep), {"memory_dir", "now", "days", "counts", "orphans",
                                    "unused", "transcripts"})
        self.assertEqual(rep["now"], NOW)


class FixtureShapeTest(unittest.TestCase):
    """The fixtures must keep the real record shape the parser depends on."""

    def test_read_fixture_is_an_assistant_tool_use(self):
        self.assertEqual(READ["type"], "assistant")
        use = READ["message"]["content"][0]
        self.assertEqual((use["type"], use["name"]), ("tool_use", "Read"))
        self.assertIn("file_path", use["input"])
        self.assertIn("timestamp", READ)

    def test_attachment_fixture_is_a_file_attachment(self):
        self.assertEqual(ATTACH["type"], "attachment")
        self.assertEqual(ATTACH["attachment"]["type"], "file")
        self.assertIn("filename", ATTACH["attachment"])


if __name__ == "__main__":
    unittest.main()
