#!/usr/bin/env python3
"""Report-only audit of a Claude Code memory dir: orphans, and entries no session used.

    memory-audit.py --memory-dir M [--days N] [--json | --names-only]

It never writes anything. Two reports:

1. Orphans. Every topic file and every `](x.md)` link in MEMORY.md and
   MEMORY-ARCHIVE.md gets one label:

   LIVE       a file with a line in the index or the archive; a line whose
              file exists
   ORPHAN     a `type_name.md` file with no line in either (salvage it into
              the archive before removing anything); a line whose file is gone
   UNDECIDED  a stray `.md` outside the `(user|feedback|project|reference)_*.md`
              pattern, linked or not; a line pointing outside the memory dir

2. Unused. Index entries (not archived ones) whose file no session has used in
   N days, oldest first: never-used first, then by last use. "Used" means,
   in a transcript under the projects dir (`**/*.jsonl`, subagents included):

   - an assistant `tool_use` named Read, Write or Edit whose `input.file_path`
     resolves into this memory dir (a relative path resolves against the
     record's `cwd`)
   - an `attachment` of type `file` for such a path. This is the harness
     re-attaching a file the session had open, after a compaction.

   Not counted:
   - relevance recall (`<system-reminder>` injection). The transcript doesn't
     record it per file, so it can't be observed. Checked against 56 real
     transcripts, claude-code 2.1.282–2.1.316.
   - Bash. A grep or cat over the dir touches many files without using any.

   Because recall can't be seen, a candidate is a reason to look at an entry,
   not proof it's dead. If the transcripts cover less than N days, the
   window is reported as short (WARN).

   The names are link texts, in the form archive-memory-lines.py takes them:
   `--names-only` prints one per line, and the text report prints a ready
   `--dry-run` command.

Exit: 0 clean (all LIVE, no candidates); 1 findings; 2 usage error, or no
MEMORY.md in the memory dir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import sys
from pathlib import Path

INDEX = "MEMORY.md"
ARCHIVE = "MEMORY-ARCHIVE.md"
SPECIAL = {INDEX, ARCHIVE}
ENTRY = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<target>[^)]+\.md)\)")
LINK = re.compile(r"\]\(([^)]+\.md)\)")
PATTERN = re.compile(r"^(user|feedback|project|reference)_[a-z0-9_]+\.md$")
USE_TOOLS = {"Read", "Write", "Edit"}
EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2
ARCHIVER = "archive-memory-lines.py"


def parse_ts(s) -> dt.datetime | None:
    if not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        ".000+00:00", "Z").replace("+00:00", "Z")


# ------------------------------------------------------------------ orphans

def link_items(text: str, kind: str, mem: Path) -> tuple[list[dict], set[str]]:
    items, targets = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        for target in LINK.findall(line):
            if target in SPECIAL:
                continue
            if "/" in target or "\\" in target:
                label, reason = "UNDECIDED", "link points outside the memory dir"
            elif (mem / target).is_file():
                label, reason = "LIVE", "file exists"
                targets.add(target)
            else:
                label, reason = "ORPHAN", "file does not exist"
            items.append({"kind": kind, "subject": target, "line": n,
                          "label": label, "reason": reason})
    return items, targets


def classify(mem: Path, index: str, archive: str) -> list[dict]:
    idx_items, idx_targets = link_items(index, "index", mem)
    arc_items, arc_targets = link_items(archive, "archive", mem)
    linked = idx_targets | arc_targets
    files = []
    for p in sorted(mem.iterdir()):
        name = p.name
        if not p.is_file() or not name.endswith(".md") or name in SPECIAL:
            continue
        if not PATTERN.match(name):
            label = "UNDECIDED"
            reason = ("stray: outside the type_name.md pattern"
                      + (", linked" if name in linked else ", no line"))
        elif name in linked:
            label = "LIVE"
            reason = "in the index" if name in idx_targets else "in the archive only"
        else:
            label, reason = "ORPHAN", "no line in the index or the archive"
        files.append({"kind": "file", "subject": name, "line": None,
                      "label": label, "reason": reason})
    return files + idx_items + arc_items


# ------------------------------------------------------------------ transcripts

def used_paths(rec: dict) -> list[str]:
    """Paths this record shows the session using; [] for anything else."""
    t = rec.get("type")
    if t == "assistant":
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return []
        out = []
        for c in content:
            if (isinstance(c, dict) and c.get("type") == "tool_use"
                    and c.get("name") in USE_TOOLS and isinstance(c.get("input"), dict)
                    and isinstance(c["input"].get("file_path"), str)):
                out.append(c["input"]["file_path"])
        return out
    if t == "attachment":
        a = rec.get("attachment")
        if isinstance(a, dict) and a.get("type") == "file" and isinstance(a.get("filename"), str):
            return [a["filename"]]
    return []


def scan(projects: Path, mem: Path) -> tuple[dict[str, dt.datetime], dict]:
    last: dict[str, dt.datetime] = {}
    oldest = None
    nfiles = skipped = 0
    paths = sorted(projects.rglob("*.jsonl")) if projects.is_dir() else []
    for f in paths:
        nfiles += 1
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(rec, dict):
                    skipped += 1
                    continue
                ts = parse_ts(rec.get("timestamp"))
                if ts is not None and (oldest is None or ts < oldest):
                    oldest = ts
                hits = used_paths(rec)
                if not hits:
                    continue
                if ts is None:
                    skipped += 1
                    continue
                cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) else "/"
                for p in hits:
                    full = Path(os.path.normpath(Path(cwd) / p))
                    if full.parent != mem:
                        continue
                    if full.name not in last or ts > last[full.name]:
                        last[full.name] = ts
    return last, {"files": nfiles, "oldest": oldest, "skipped_lines": skipped}


def unused(index: str, last: dict[str, dt.datetime], cutoff: dt.datetime,
           mem: Path) -> list[dict]:
    out = []
    for line in index.splitlines():
        m = ENTRY.match(line)
        if not m or m["target"] in SPECIAL or not (mem / m["target"]).is_file():
            continue
        used = last.get(m["target"])
        if used is None or used < cutoff:
            out.append({"name": m["name"], "file": m["target"],
                        "last_used": iso(used) if used else None, "_t": used})
    out.sort(key=lambda c: (c["_t"] is not None, c["_t"] or cutoff, c["name"]))
    for c in out:
        del c["_t"]
    return out


# ------------------------------------------------------------------ output

def text_report(rep: dict, mem: Path) -> str:
    out = [f"memory-audit: {mem}"]
    c = rep["counts"]
    out.append(f"orphans: LIVE {c['LIVE']}  ORPHAN {c['ORPHAN']}  UNDECIDED {c['UNDECIDED']}")
    for item in rep["orphans"]:
        if item["label"] == "LIVE":
            continue
        where = item["kind"] + (f":{item['line']}" if item["line"] else "")
        out.append(f"  {item['label']:<9} {where:<12} {item['subject']} ({item['reason']})")
    t = rep["transcripts"]
    out.append(f"transcripts: {t['files']} file(s), oldest record {t['oldest'] or 'none'}")
    if t["window_short"]:
        out.append(f"  WARN transcripts cover less than {rep['days']} days: an entry "
                   "listed below may have been used before the window")
    out.append(f"unused: {len(rep['unused'])} index entr(y/ies) not used in "
               f"{rep['days']} days (oldest first)")
    for u in rep["unused"]:
        out.append(f"  {u['last_used'] or 'never':<24} {u['name']}  ({u['file']})")
    if rep["unused"]:
        names = " ".join(shlex.quote(u["name"]) for u in rep["unused"])
        out.append(f"  review, then: {ARCHIVER} --memory-dir {shlex.quote(str(mem))} "
                   f"--section 'not used in {rep['days']} days' --dry-run {names}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--memory-dir", type=Path, required=True)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    ap.add_argument("--projects-dir", type=Path, default=Path(cfg) / "projects",
                    help="transcripts are read from **/*.jsonl here (default %(default)s)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--now", help="ISO-8601 instead of the clock (tests, reruns)")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true")
    out.add_argument("--names-only", action="store_true",
                     help=f"candidate names only, one per line, for {ARCHIVER}")
    a = ap.parse_args(argv)

    if a.days < 1:
        ap.error("--days must be at least 1")
    now = parse_ts(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        ap.error(f"--now: not an ISO-8601 time: {a.now!r}")
    mem = a.memory_dir.resolve()
    if not (mem / INDEX).is_file():
        print(f"memory-audit: {mem / INDEX} not found", file=sys.stderr)
        return EXIT_USAGE

    index = (mem / INDEX).read_text(encoding="utf-8")
    archive = (mem / ARCHIVE).read_text(encoding="utf-8") if (mem / ARCHIVE).is_file() else ""
    items = classify(mem, index, archive)
    cutoff = now - dt.timedelta(days=a.days)
    last, info = scan(a.projects_dir, mem)
    cands = unused(index, last, cutoff, mem)
    oldest = info["oldest"]
    rep = {
        "memory_dir": str(mem),
        "now": iso(now),
        "days": a.days,
        "counts": {k: sum(1 for i in items if i["label"] == k)
                   for k in ("LIVE", "ORPHAN", "UNDECIDED")},
        "orphans": items,
        "unused": cands,
        "transcripts": {"files": info["files"],
                        "oldest": iso(oldest) if oldest else None,
                        "skipped_lines": info["skipped_lines"],
                        "window_short": oldest is None or oldest > cutoff},
    }
    findings = bool(cands) or rep["counts"]["ORPHAN"] or rep["counts"]["UNDECIDED"]

    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    elif a.names_only:
        for c in cands:
            print(c["name"])
    else:
        print(text_report(rep, mem))
    return EXIT_FINDINGS if findings else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
