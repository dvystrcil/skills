#!/usr/bin/env python3
"""Gate: does Claude Code's MEMORY.md index fit its load budget? (homelab#1800 AC3)

    check-memory-index.py                      # every project's index on this machine
    check-memory-index.py path/to/MEMORY.md    # one file

Exit 0 = every index loads whole. Exit 1 = some of one is invisible to every
session (or a line is too long). Exit 2 = no file to check.

With no path it checks every `projects/*/memory/MEMORY.md` under the Claude
config dir (`$CLAUDE_CONFIG_DIR`, else `~/.claude`). The project dir name is
derived from the working directory, so it differs per machine — nothing here
hardcodes it (homelab#1800 AC7: same tool on the homelab laptop and the work
workstation, memory never shared between them).

Why this exists
---------------
Claude Code auto-loads only a prefix of `MEMORY.md`. Past the cut-off, entries
are not in any session's context, and the only signal is a warning line in the
system prompt that the agent has to notice itself. On 2026-11-01 the cut-off
was line 155 of 233: 79 entries had been invisible for however long the file
had been over.

The limits, and how they were established
-----------------------------------------
Read off the shipped binary (claude-code 2.1.316, functions `sar`/`LUe`), not
assumed from the "200 lines" in the docs:

    text  = content.trim()
    lines = text.count("\\n") + 1           limit FH = 200
    size  = text.length                     limit ZJ = 25000

`.length` is a JS string length — UTF-16 code units, not bytes. Checked
against the real file: 38,162 bytes, but the warning said "36.7KB", which is
37,588 characters / 1024; and the observed cut-off at line 155 is exactly where
cumulative characters first pass 25,000. Measured in bytes, line 154 would
already have been over.

When either limit is exceeded the loader keeps the first 200 lines, then cuts
at the last newline at or before index 25,000. `loaded_prefix()` ports that so
the report names the line where the loader actually cuts, not an estimate.

Per-line cap: the system prompt tells the agent to keep entries "under ~200
chars". The loader does not enforce that; this gate does, because a long line
is how the file got over the char budget in the first place.

If a Claude Code upgrade changes FH/ZJ, update MAX_LINES/MAX_CHARS and the
test that pins them, with the new evidence.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_LINES = 200
MAX_CHARS = 25000
MAX_LINE_CHARS = 200



def claude_home(env=None) -> Path:
    env = os.environ if env is None else env
    d = env.get("CLAUDE_CONFIG_DIR")
    return Path(d) if d else Path.home() / ".claude"


def discover(home: Path) -> list[Path]:
    return sorted((home / "projects").glob("*/memory/MEMORY.md"))

NL = 0x0A


def js_length(s: str) -> int:
    """Length as JavaScript counts it: UTF-16 code units."""
    return len(s.encode("utf-16-le")) // 2


def _units(s: str) -> tuple[int, ...]:
    b = s.encode("utf-16-le")
    return struct.unpack(f"<{len(b) // 2}H", b)


def js_trim(s: str) -> str:
    return s.strip().strip("﻿").strip()


@dataclass
class Result:
    line_count: int
    char_count: int
    loaded_lines: int
    violations: list[str] = field(default_factory=list)

    @property
    def hidden_lines(self) -> int:
        return self.line_count - self.loaded_lines

    @property
    def first_hidden_line(self) -> int | None:
        return self.loaded_lines + 1 if self.hidden_lines else None


def loaded_prefix(text: str, max_lines: int = MAX_LINES,
                  max_chars: int = MAX_CHARS) -> tuple[int, int, int]:
    """Port of the loader's truncation. Returns (line_count, char_count,
    loaded_lines), all as the loader counts them."""
    n = _units(js_trim(text))
    line_count = n.count(NL) + 1
    char_count = len(n)
    if line_count <= max_lines and char_count <= max_chars:
        return line_count, char_count, line_count

    w = n
    if line_count > max_lines:
        # n.split("\n").slice(0, FH).join("\n")
        seen = 0
        for i, u in enumerate(n):
            if u == NL:
                seen += 1
                if seen == max_lines:
                    w = n[:i]
                    break
    if len(w) > max_chars:
        # w.lastIndexOf("\n", ZJ): last newline at index <= ZJ
        z = -1
        for i in range(min(max_chars, len(w) - 1), -1, -1):
            if w[i] == NL:
                z = i
                break
        w = w[:z] if z > 0 else w[:max_chars]
    loaded = w.count(NL) + 1 if len(w) < len(n) and n[len(w)] == NL else 0
    return line_count, char_count, loaded


def check(text: str, max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS,
          max_line_chars: int = MAX_LINE_CHARS) -> Result:
    line_count, char_count, loaded = loaded_prefix(text, max_lines, max_chars)
    r = Result(line_count, char_count, loaded)
    if line_count > max_lines:
        r.violations.append(f"{line_count} lines (limit {max_lines})")
    if char_count > max_chars:
        r.violations.append(
            f"{char_count} characters (limit {max_chars}; JS length, not bytes)")
    for i, line in enumerate(js_trim(text).split("\n"), 1):
        width = js_length(line)
        if width > max_line_chars:
            r.violations.append(
                f"line {i} is {width} characters (limit {max_line_chars}): "
                f"{line[:60]}…")
    return r


def report(path: Path, a) -> int:
    r = check(path.read_text(encoding="utf-8"),
              a.max_lines, a.max_chars, a.max_line_chars)
    print(f"{path}: {r.line_count} lines, {r.char_count} chars "
          f"(budget {a.max_lines} lines / {a.max_chars} chars)")
    if r.first_hidden_line:
        print(f"  loader drops {r.hidden_lines} of {r.line_count} lines, "
              f"starting at line {r.first_hidden_line}")
    else:
        print(f"  headroom: {a.max_chars - r.char_count} chars, "
              f"{a.max_lines - r.line_count} lines")
    if r.violations:
        print(f"FAIL: {len(r.violations)} violation(s)")
        for v in r.violations:
            print(f"  - {v}")
        return 1
    print("OK: the whole index loads")
    return 0


def main(argv: list[str] | None = None, env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", nargs="?", type=Path)
    ap.add_argument("--max-lines", type=int, default=MAX_LINES)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--max-line-chars", type=int, default=MAX_LINE_CHARS)
    a = ap.parse_args(argv)

    if a.path is not None:
        paths = [a.path]
    else:
        home = claude_home(env)
        paths = discover(home)
        if not paths:
            print(f"ERROR: no projects/*/memory/MEMORY.md under {home} — an "
                  f"absent index is not a compliant one", file=sys.stderr)
            return 2

    rc = 0
    for p in paths:
        if not p.is_file():
            print(f"ERROR: {p} not found — an absent index is not a "
                  f"compliant one", file=sys.stderr)
            return 2
        rc = max(rc, report(p, a))
    return rc

if __name__ == "__main__":
    sys.exit(main())
