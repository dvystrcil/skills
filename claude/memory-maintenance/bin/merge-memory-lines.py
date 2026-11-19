#!/usr/bin/env python3
"""Merge overlapping MEMORY.md entries into one, losslessly (homelab#1929).

    merge-memory-lines.py --memory-dir M --proposal P.json [--pick N] --dry-run
    merge-memory-lines.py --memory-dir M --proposal P.json [--pick N]

P.json is `{"proposals": [ {...}, ... ]}`, as propose-memory-merges.py prints
it. `--pick N` chooses one (needed when there is more than one). A proposal:

    sources      ≥ 2 distinct topic file names, each with exactly 1 index line
    name         link text of the new entry (no `]`, no newline, not taken)
    file         `<type>_<snake_case>.md`, not on disk, not linked anywhere
    type         user | feedback | project | reference
    description  one line, for the new file's frontmatter
    body         the merged text; it must name every source file
    index_line   `- [name](file) — hook`, ≤ 150 chars
    rationale    optional, ignored

Steps, the archiver's contract (archive-memory-lines.py, whose helpers this
reuses):

1. Refuse (exit 2, nothing written, no backup) a proposal that fails any of
   the above, or whose new file fails check-memory-file.py's shape check.
2. Back up MEMORY.md and MEMORY-ARCHIVE.md to a timestamped dir.
3. Write the new file M, frontmatter + `merged_from: [sources]` + body.
   Source topic files stay on disk.
4. Move every source's index line verbatim to
   `## Merged <date> → [name](file)` at the end of the archive; the new
   index line takes the first source's place. Recount the pointer.
5. Re-read and verify: the archiver's checks (no line lost, no link dropped,
   moved lines out of the index and in the archive, every index link
   resolves, pointer right), plus M holds exactly what was written and the
   new index line is in the index once. On failure both files are restored
   and M is removed (exit 3).
6. Run check-memory-index.py (exit 1 if it still fails; the merge is kept).

`--dry-run` prints M and unified diffs of both index files, and writes nothing.
`validate()` is also the guard propose-memory-merges.py puts model drafts
through, so a proposal the proposer emits is one this script accepts.

Exit: 0 merged + index check passes; 1 merged, index check fails;
2 refused, nothing written; 3 verification failed, files restored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


arc = _load("archive_memory_lines", "archive-memory-lines.py")
cmf = _load("check_memory_file", "check-memory-file.py")

INDEX, ARCHIVE, Refused = arc.INDEX, arc.ARCHIVE, arc.Refused
EXIT_OK, EXIT_CHECK_FAILED, EXIT_REFUSED, EXIT_RESTORED = 0, 1, 2, 3
MAX_INDEX_LINE = 150
REQUIRED = {"sources": list, "name": str, "file": str, "type": str,
            "description": str, "body": str, "index_line": str}
OPTIONAL = {"rationale": str}
BARE_MD = re.compile(r"^[^/\\]+\.md$")
HOOKED = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<target>[^)]+)\) — \S")


def entries(text: str) -> list[tuple[str, str, str]]:
    """(name, target, line) for every `- [name](target)` line."""
    return [(m.group("name"), m.group("target"), l) for l in arc.lines_of(text)
            if (m := arc.ENTRY.match(l))]


def schema_problems(p) -> list[str]:
    if not isinstance(p, dict):
        return ["a proposal must be a JSON object"]
    problems = [f"unknown key `{k}`" for k in sorted(set(p) - set(REQUIRED) - set(OPTIONAL))]
    for k, t in {**REQUIRED, **OPTIONAL}.items():
        if k not in p:
            if k in REQUIRED:
                problems.append(f"missing key `{k}`")
        elif not isinstance(p[k], t):
            problems.append(f"`{k}` must be a {t.__name__}")
    if problems:
        return problems
    for k in ("name", "description", "index_line"):
        if "\n" in p[k]:
            problems.append(f"`{k}` must be one line")
    if not p["body"].strip():
        problems.append("`body` is empty")
    if not p["description"].strip():
        problems.append("`description` is empty")
    if not p["name"].strip() or "]" in p["name"]:
        problems.append("`name` must be non-empty link text with no `]`")
    if not all(isinstance(s, str) and BARE_MD.match(s) for s in p["sources"]):
        problems.append("`sources` must be bare `.md` file names in the memory dir")
    if p["type"] not in cmf.TYPES:
        problems.append(f"`type` must be one of {', '.join(cmf.TYPES)}")
    m = cmf.FILE_NAME.match(p["file"])
    if not m or m.group("type") != p["type"]:
        problems.append(f"`file` must be `{p['type']}_<snake_case>.md`, got {p['file']!r}")
    line = p["index_line"]
    if len(line) > MAX_INDEX_LINE:
        problems.append(f"`index_line` is {len(line)} chars, max {MAX_INDEX_LINE}")
    h = HOOKED.match(line)
    if not h:
        problems.append("`index_line` must be `- [name](file.md) — hook`")
    elif (h.group("name"), h.group("target")) != (p["name"], p["file"]):
        problems.append(f"`index_line` links [{h.group('name')}]({h.group('target')}), "
                        f"the proposal is [{p['name']}]({p['file']})")
    return problems


def compose(p: dict) -> str:
    """The merged topic file's text."""
    fm = ["---", f"name: {p['name']}", f"description: {p['description']}",
          "metadata:", f"  type: {p['type']}", "merged_from:",
          *(f"  - {s}" for s in p["sources"]), "---"]
    return "\n".join(fm) + "\n\n" + p["body"].rstrip("\n") + "\n"


def validate(p, mem: Path) -> list[str]:
    """Every reason to refuse proposal `p` against memory dir `mem`. Never writes there."""
    problems = schema_problems(p)
    if problems:
        return problems
    srcs = p["sources"]
    if len(srcs) < 2:
        problems.append(f"need at least 2 sources, got {len(srcs)}")
    dupes = sorted({s for s in srcs if srcs.count(s) > 1})
    if dupes:
        problems.append(f"source(s) given more than once: {', '.join(dupes)}")
    index = (mem / INDEX).read_text(encoding="utf-8")
    ap = mem / ARCHIVE
    archive = ap.read_text(encoding="utf-8") if ap.is_file() else ""
    idx, arcs = entries(index), entries(archive)
    for s in dict.fromkeys(srcs):
        hits = [l for _, t, l in idx if t == s]
        if len(hits) != 1:
            why = (" (it is archived only)" if not hits and any(t == s for _, t, _ in arcs)
                   else "")
            problems.append(f"source {s} matches {len(hits)} index lines, need exactly 1{why}")
        if s in (INDEX, ARCHIVE) or not (mem / s).is_file():
            problems.append(f"source file {s} is missing")
        if s not in p["body"]:
            problems.append(f"`body` does not name source {s}")
    if any(n == p["name"] for n, _, _ in idx + arcs):
        problems.append(f"name {p['name']!r} is already an entry")
    if (mem / p["file"]).exists() or p["file"] in arc.links(index + archive):
        problems.append(f"file {p['file']} already exists or is linked")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / p["file"]
        f.write_text(compose(p), encoding="utf-8")
        problems += [f"merged file: {x}" for x in cmf.check_file(f)]
    return problems


def load_proposal(path: Path, pick: int | None) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read proposal {path}: {e}")
    props = doc.get("proposals") if isinstance(doc, dict) else None
    if not isinstance(props, list):
        raise Refused("proposal file must be an object with a `proposals` list")
    if not props:
        raise Refused("no proposals in the file")
    if pick is None:
        if len(props) > 1:
            raise Refused(f"{len(props)} proposals in the file: choose one with --pick")
        pick = 0
    if not 0 <= pick < len(props):
        raise Refused(f"--pick {pick} is out of range 0..{len(props) - 1}")
    return props[pick]


def build(old_index: str, old_archive: str | None, p: dict, heading: str,
          ) -> tuple[str, str, list[str]]:
    moved = [l for _, t, l in entries(old_index) if t in p["sources"]]
    new_archive = arc.append_section(old_archive, heading, moved)
    idx = []
    for l in arc.lines_of(old_index):
        if l == moved[0]:
            idx.append(p["index_line"])
        elif l not in moved:
            idx.append(l)
    return arc.set_pointer(idx, new_archive), new_archive, moved


def diff(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{name}", f"b/{name}"))


def main(argv: list[str] | None = None, after_write=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--memory-dir", type=Path, required=True)
    ap.add_argument("--proposal", type=Path, required=True)
    ap.add_argument("--pick", type=int, help="which proposal in the file (0-based)")
    ap.add_argument("--backup-dir", type=Path, default=arc.default_backup_root(),
                    help="a timestamped subdir is created here (default %(default)s)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    mem = a.memory_dir.resolve()
    ip, apath = mem / INDEX, mem / ARCHIVE
    try:
        if not ip.is_file():
            raise Refused(f"{ip} not found")
        broot = a.backup_dir.resolve()
        arc.check_backup_root(broot, mem)
        p = load_proposal(a.proposal, a.pick)
        problems = validate(p, mem)
        if problems:
            raise Refused("bad proposal:\n  - " + "\n  - ".join(problems))
        heading = f"## Merged {a.date} → [{p['name']}]({p['file']})"
        old_index = ip.read_text(encoding="utf-8")
        old_archive = apath.read_text(encoding="utf-8") if apath.is_file() else None
        new_index, new_archive, moved = build(old_index, old_archive, p, heading)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return EXIT_REFUSED

    merged, mpath = compose(p), mem / p["file"]
    print(f"new file {p['file']}:")
    print("".join(f"  {l}" for l in merged.splitlines(True)), end="")
    print(diff(old_index, new_index, INDEX), end="")
    print(diff(old_archive or "", new_archive, ARCHIVE), end="")
    if a.dry_run:
        print("dry run: nothing written")
        return EXIT_OK

    snap = arc.backup(broot, mem)
    print(f"backup: {snap}")
    # New file, then archive, then index: a crash part-way duplicates, never loses.
    arc.write_atomic(mpath, merged)
    arc.write_atomic(apath, new_archive)
    arc.write_atomic(ip, new_index)
    if after_write:
        after_write(mem)

    got_index = ip.read_text(encoding="utf-8")
    problems = arc.verify(old_index, old_archive, got_index,
                          apath.read_text(encoding="utf-8"), mem, moved)
    if not mpath.is_file() or mpath.read_text(encoding="utf-8") != merged:
        problems.append(f"{p['file']} does not hold what was written")
    n = arc.lines_of(got_index).count(p["index_line"])
    if n != 1:
        problems.append(f"new index line is in {INDEX} {n} times, expected 1")
    if problems:
        arc.restore(snap, mem)
        mpath.unlink(missing_ok=True)
        print("VERIFY FAILED — both files restored from backup, "
              f"{p['file']} removed:", file=sys.stderr)
        for x in problems:
            print(f"  - {x}", file=sys.stderr)
        return EXIT_RESTORED

    print(f"verified: lossless; pointer = {arc.archived_only(new_index, new_archive)}")
    sys.stdout.flush()
    rc = subprocess.run([sys.executable, str(arc.CHECK), str(ip)]).returncode
    return EXIT_OK if rc == 0 else EXIT_CHECK_FAILED


if __name__ == "__main__":
    sys.exit(main())
