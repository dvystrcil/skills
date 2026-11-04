#!/usr/bin/env python3
"""Archive MEMORY.md index lines into MEMORY-ARCHIVE.md, losslessly.

    archive-memory-lines.py --section "narrow gotchas" NAME [NAME ...]
    archive-memory-lines.py --dry-run --section "..." NAME ...

NAME is a memory's link text in the index: the `name` in `- [name](file.md) — hook`.
Each must match exactly one index line, or nothing is touched.

Steps, in order:

1. Refuse (exit 2, nothing written) if a NAME matches 0 or >1 index lines, is
   given twice, or the backup dir is inside the memory dir.
2. Copy MEMORY.md and MEMORY-ARCHIVE.md to a fresh timestamped backup dir.
3. Move the matched lines verbatim to `## Archived <date> — <section>` at the
   end of the archive (appended to that section if the heading already exists).
4. Recount the `> N more hooks in [MEMORY-ARCHIVE.md](...)` pointer: distinct
   `](x.md)` link targets in the archive that are not in the index, compared
   byte-exact — the same number as
       LC_ALL=C; grep -oE '\\]\\([^)]+\\.md\\)' F | sort -u   (per file) | comm -23
   A collating locale's `sort -u` can fold distinct links together and
   undercount; the pointer is appended if the index has none.
5. Re-read both files from disk and verify: every pre-change line of both files
   (except the old pointer) is still present verbatim, no `.md` link was
   dropped, the moved lines are in the archive and not the index, every index
   link resolves to a file, and the pointer equals the recount. On any failure
   both files are restored from the backup (exit 3).
6. Run check-memory-index.py on the new index (exit 1 if it still fails — the
   archive is kept; archive more).

--memory-dir is required, never guessed: the project dir name is derived from
the working directory and differs per machine (e.g.
~/.claude/projects/-home-dan-Code/memory).

Exit: 0 archived + index check passes; 1 archived but the index check still
fails; 2 refused, nothing written; 3 verification failed, both files restored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

INDEX = "MEMORY.md"
ARCHIVE = "MEMORY-ARCHIVE.md"
ENTRY = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<target>[^)]+)\)")
LINK = re.compile(r"\]\(([^)]+\.md)\)")
POINTER = re.compile(r"^> (\d+)( more hooks in \[MEMORY-ARCHIVE\.md\]\(MEMORY-ARCHIVE\.md\).*)$")
POINTER_DEFAULT = (" more hooks in [MEMORY-ARCHIVE.md](MEMORY-ARCHIVE.md) — files "
                   "intact, recalled on relevance, not auto-loaded")
ARCHIVE_HEADER = "# Memory Archive (not auto-loaded)"
CHECK = Path(__file__).resolve().parent / "check-memory-index.py"

EXIT_OK, EXIT_CHECK_FAILED, EXIT_REFUSED, EXIT_RESTORED = 0, 1, 2, 3


class Refused(Exception):
    pass


def lines_of(text: str) -> list[str]:
    """Lines without the final empty element a trailing newline produces."""
    ls = text.split("\n")
    return ls[:-1] if ls and ls[-1] == "" else ls


def join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def links(text: str) -> set[str]:
    return set(LINK.findall(text))


def archived_only(index: str, archive: str) -> int:
    # Python str comparison is code-point exact: the LC_ALL=C semantics.
    return len(links(archive) - links(index))


def find_matches(index_lines: list[str], names: list[str]) -> list[str]:
    dupes = sorted(n for n, c in Counter(names).items() if c > 1)
    if dupes:
        raise Refused(f"name(s) given more than once: {', '.join(dupes)}")
    picked, errors = [], []
    for name in names:
        hits = [l for l in index_lines
                if (m := ENTRY.match(l)) and m.group("name") == name]
        if len(hits) != 1:
            extra = " (the archive pointer is not an entry)" if name == ARCHIVE else ""
            errors.append(f"{name!r} matches {len(hits)} index lines, need exactly 1{extra}"
                          + "".join(f"\n    {h}" for h in hits))
        else:
            picked.append(hits[0])
    if errors:
        raise Refused("\n  ".join(errors))
    return picked


def build(old_index: str, old_archive: str | None, moved: list[str],
          heading: str) -> tuple[str, str]:
    idx = [l for l in lines_of(old_index) if l not in moved]

    arc = lines_of(old_archive) if old_archive is not None else [ARCHIVE_HEADER]
    if heading in arc:
        start = arc.index(heading)
        end = next((i for i in range(start + 1, len(arc)) if arc[i].startswith("## ")),
                   len(arc))
        while end - 1 > start and arc[end - 1].strip() == "":
            end -= 1
        arc[end:end] = moved
    else:
        if arc and arc[-1].strip() != "":
            arc.append("")
        arc += [heading, *moved]
    new_archive = join(arc)

    ptr = [i for i, l in enumerate(idx) if POINTER.match(l)]
    if len(ptr) > 1:
        raise Refused(f"{len(ptr)} '> N more hooks' pointer lines in {INDEX}, expected ≤ 1")
    count = archived_only(join(idx), new_archive)
    if ptr:
        i = ptr[0]
        idx[i] = POINTER.sub(lambda m: f"> {count}{m.group(2)}", idx[i])
    else:
        idx.append(f"> {count}{POINTER_DEFAULT}")
        # the new pointer line adds MEMORY-ARCHIVE.md to the index's links,
        # which is not in the archive, so the count is unchanged.
    return join(idx), new_archive


def verify(old_index: str, old_archive: str | None, new_index: str, new_archive: str,
           mem: Path, moved: list[str]) -> list[str]:
    problems = []
    old = Counter(l for l in lines_of(old_index) if not POINTER.match(l))
    old.update(lines_of(old_archive or ""))
    new = Counter(lines_of(new_index) + lines_of(new_archive))
    for line, n in old.items():
        if new[line] < n:
            problems.append(f"line lost: {line!r}")
    for link in sorted(links(old_index + (old_archive or "")) - links(new_index + new_archive)):
        problems.append(f"link dropped: {link}")
    idx_lines, arc_lines = set(lines_of(new_index)), set(lines_of(new_archive))
    for line in moved:
        if line in idx_lines:
            problems.append(f"moved line still in {INDEX}: {line!r}")
        if line not in arc_lines:
            problems.append(f"moved line missing from {ARCHIVE}: {line!r}")
    for link in sorted(links(new_index)):
        if not (mem / link).is_file():
            problems.append(f"index link does not resolve: {link}")
    ptr = [int(m.group(1)) for l in lines_of(new_index) if (m := POINTER.match(l))]
    want = archived_only(new_index, new_archive)
    if ptr != [want]:
        problems.append(f"pointer says {ptr}, archived-only links = {want}")
    return problems


def write_atomic(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def default_backup_root() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "claude-memory" / "archive-backups"


def main(argv: list[str] | None = None, after_write=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="+", metavar="NAME")
    ap.add_argument("--section", required=True, help="archive section title")
    ap.add_argument("--memory-dir", type=Path, required=True)
    ap.add_argument("--backup-dir", type=Path, default=default_backup_root(),
                    help="a timestamped subdir is created here (default %(default)s)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    mem = a.memory_dir.resolve()
    ip, apath = mem / INDEX, mem / ARCHIVE
    heading = f"## Archived {a.date} — {a.section}"
    try:
        if not ip.is_file():
            raise Refused(f"{ip} not found")
        broot = a.backup_dir.resolve()
        if broot == mem or mem in broot.parents:
            raise Refused(f"backup dir {broot} is inside the memory dir {mem}")
        old_index = ip.read_text(encoding="utf-8")
        old_archive = apath.read_text(encoding="utf-8") if apath.is_file() else None
        moved = find_matches(lines_of(old_index), a.names)
        new_index, new_archive = build(old_index, old_archive, moved, heading)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return EXIT_REFUSED

    print(f"moving {len(moved)} line(s) to '{heading}':")
    for l in moved:
        print(f"  {l}")
    if a.dry_run:
        print("dry run: nothing written")
        return EXIT_OK

    snap = broot / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snap.mkdir(parents=True)
    shutil.copy2(ip, snap / INDEX)
    if old_archive is not None:
        shutil.copy2(apath, snap / ARCHIVE)
    print(f"backup: {snap}")

    # Archive first: a crash between the two writes duplicates, never loses.
    write_atomic(apath, new_archive)
    write_atomic(ip, new_index)
    if after_write:
        after_write(mem)

    problems = verify(old_index, old_archive,
                      ip.read_text(encoding="utf-8"), apath.read_text(encoding="utf-8"),
                      mem, moved)
    if problems:
        shutil.copy2(snap / INDEX, ip)
        if old_archive is not None:
            shutil.copy2(snap / ARCHIVE, apath)
        else:
            apath.unlink(missing_ok=True)
        print("VERIFY FAILED — both files restored from backup:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return EXIT_RESTORED

    print(f"verified: lossless; pointer = {archived_only(new_index, new_archive)}")
    sys.stdout.flush()
    rc = subprocess.run([sys.executable, str(CHECK), str(ip)]).returncode
    return EXIT_OK if rc == 0 else EXIT_CHECK_FAILED


if __name__ == "__main__":
    sys.exit(main())
