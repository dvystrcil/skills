#!/usr/bin/env python3
"""Gate: is a memory file in the shape Claude Code and opencode both read? (homelab#2002 AC3)

    check-memory-file.py FILE [FILE ...]
    check-memory-file.py --require-index FILE ...   # also: linked from MEMORY.md / MEMORY-ARCHIVE.md

Run it on a file you just wrote, not on the whole store. On 2026-11-09, 67
feedback and 45 project files had no `**Why:**` line. They predate the rule.

A file passes when:

  * it starts with `---` frontmatter holding a non-empty `name:` and
    `description:`, and a type: `metadata:` → `type:`, or a top-level `type:`
    (the older form, still in ~90 files)
  * the type is one of user, feedback, project, reference
  * the file name is `<type>_<snake_case>.md`, with the prefix equal to the type
  * feedback and project files have a `**Why:**` line and a `**How to apply:**`
    line in the body (not the frontmatter), each followed by text. homelab#1988
    found memory keeps the "why" only when the writer puts it there on purpose.
  * with --require-index: a `](<file name>)` link in MEMORY.md or
    MEMORY-ARCHIVE.md in the same dir. A file nothing links to only comes
    back through relevance recall.

Exit 0 = every file passes. 1 = a problem (printed as `path: problem`).
2 = usage: a missing file, or MEMORY.md / MEMORY-ARCHIVE.md itself.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TYPES = ("user", "feedback", "project", "reference")
NEEDS_WHY = ("feedback", "project")
FILE_NAME = re.compile(r"^(?P<type>[a-z]+)_[a-z0-9_]+\.md$")
INDEX_FILES = ("MEMORY.md", "MEMORY-ARCHIVE.md")
MARKERS = ("**Why:**", "**How to apply:**")


def frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """(fields, body), or None without a leading `---` block.

    Fields are top-level `key: value` plus `metadata.<key>` for keys indented
    under `metadata:`. A small line parser, not YAML: the store is written by
    agents, and these files never use more than this.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    fields: dict[str, str] = {}
    parent = None
    for line in lines[1:end]:
        m = re.match(r"^(\s*)([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        indent, key, value = m.groups()
        value = value.strip().strip('"').strip("'").strip()
        if indent:
            if parent:
                fields[f"{parent}.{key}"] = value
        else:
            fields[key] = value
            parent = key if not value else None
    return fields, "\n".join(lines[end + 1:])


def has_marker(body: str, marker: str) -> bool:
    """`marker` starts a line (optionally as a list item) and text follows it."""
    lines = body.split("\n")
    pat = re.compile(r"^\s*(?:[-*]\s+)?" + re.escape(marker) + r"(.*)$")
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        if m.group(1).strip():
            return True
        nxt = next((x for x in lines[i + 1:] if x.strip()), "")
        if nxt and not any(k in nxt for k in MARKERS):
            return True
    return False


def indexed(path: Path) -> bool:
    link = f"]({path.name})"
    for name in INDEX_FILES:
        f = path.parent / name
        if f.is_file() and link in f.read_text(errors="replace"):
            return True
    return False


def check_file(path: Path, require_index: bool = False) -> list[str]:
    problems: list[str] = []
    parsed = frontmatter(path.read_text(errors="replace"))
    if parsed is None:
        return ["no frontmatter: the file must start with a `---` block"]
    fields, body = parsed
    for key in ("name", "description"):
        if not fields.get(key):
            problems.append(f"frontmatter has no `{key}:` value")
    typ = fields.get("metadata.type") or fields.get("type")
    if not typ:
        problems.append("frontmatter has no type (`metadata:` → `type:`)")
    elif typ not in TYPES:
        problems.append(f"type `{typ}` is not one of {', '.join(TYPES)}")
    m = FILE_NAME.match(path.name)
    if not m or m.group("type") not in TYPES:
        problems.append(f"file name `{path.name}` is not `<type>_<snake_case>.md`")
    elif typ in TYPES and m.group("type") != typ:
        problems.append(f"file name prefix `{m.group('type')}_` does not match type `{typ}`")
    if typ in NEEDS_WHY:
        for marker in MARKERS:
            if not has_marker(body, marker):
                problems.append(f"{typ} memory has no `{marker}` line with text in the body")
    if require_index and not indexed(path):
        problems.append(f"not linked from {' or '.join(INDEX_FILES)}: add `- [name]({path.name}) — hook` to the index")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--require-index", action="store_true",
                    help="also require a link from MEMORY.md or MEMORY-ARCHIVE.md")
    a = ap.parse_args(argv)
    rc = 0
    for f in a.files:
        if f.name in INDEX_FILES:
            print(f"{f}: is an index file, not a memory", file=sys.stderr)
            return 2
        if not f.is_file():
            print(f"{f}: no such file", file=sys.stderr)
            return 2
        problems = check_file(f, a.require_index)
        for p in problems:
            print(f"{f}: {p}")
        if problems:
            rc = 1
        else:
            print(f"{f}: ok")
    return rc


if __name__ == "__main__":
    sys.exit(main())
