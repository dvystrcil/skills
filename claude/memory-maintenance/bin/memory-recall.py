#!/usr/bin/env python3
"""Archived memories that match a prompt, for Claude Code and opencode (homelab#2002 AC5).

    echo "<prompt>" | memory-recall.py --memory-dir M           # opencode plugin: text block or nothing
    memory-recall.py --claude-hook [--memory-dir M] < hook.json # Claude Code UserPromptSubmit hook

Both tools load MEMORY.md, the index. Neither loads MEMORY-ARCHIVE.md, where
entries go to keep the index under its 25,000-char budget. This brings an
archived entry back when a prompt is about it. It prints the matching entries'
absolute paths and hooks so the agent can read the file.

Matching is deterministic, with no model call. An entry's text is its link
name, its hook, and the `description:` of its topic file. Prompt words of 3+
letters (stopwords dropped, a trailing plural `s` folded) are matched against
it. An entry needs at least MIN_RARE distinct matching words that are RARE:
in at most max(RARE_MIN_DF, 1% of) archive entries. Hits are ranked by the
summed rarity (idf) of all matching words, and the top `--limit` are printed.
A prompt with more than MAX_PROMPT_WORDS distinct words is skipped: a paste
shares rare words with everything.

Tuned on 120 real prompts from this machine's transcripts (2026-11-09). Two
matching words of any kind put a block on 18 of 30 prompts, mostly noise.
Two rare words and the length cap put a block on 6 of 120, and kept 4 of 5
hand-written prompts that should hit.

Skipped: entries whose file is also linked from MEMORY.md (already loaded),
lines whose file is gone, and duplicate lines for one file.

--claude-hook reads the hook JSON from stdin (`prompt`, `transcript_path`).
Without --memory-dir it uses `<dir of transcript_path>/memory`, which is the
session's project memory dir. Output is
`{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ...}}`,
or nothing when there's no match.

It never blocks a prompt. On any error it prints nothing to stdout and exits 0.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ENTRY = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<file>[^)/]+\.md)\)\s*(?:—|-|:)?\s*(?P<hook>.*)$")
LINK = re.compile(r"\]\(([^)]+\.md)\)")
WORD = re.compile(r"[a-z0-9][a-z0-9.+#-]*[a-z0-9]|[a-z0-9]")
MIN_LEN = 3
MIN_RARE = 2          # distinct matching words that are rare across the archive
RARE_FRACTION = 0.01  # rare = in at most this share of entries...
RARE_MIN_DF = 3       # ...or in at most this many, whichever is larger
MAX_PROMPT_WORDS = 40 # longer prompts (pastes, continuation summaries) are skipped
LIMIT = 3
STOP = frozenset("""
the and for are but not you all any can had her was one our out has have him his how its may new now
old see two way who did get got let put say she too use with that this from they will would there their
what about which when make like time just know take into year your some could them than then look only
come over also back after work first well even want because these give most should does done doing been
being were here more very such much many each other while where why who whom whose able need needs please
thanks thank yes okay sure let's lets into onto upon via per out off any every again still yet ever never
""".split())


@dataclass
class Hit:
    file: str
    path: Path
    name: str
    hook: str
    score: float


def words(text: str) -> set[str]:
    out = set()
    for w in WORD.findall(text.lower()):
        w = w.strip(".+#-")
        if len(w) < MIN_LEN or w in STOP or w.isdigit():
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def description(path: Path) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    head = text.split("\n---", 1)[0]
    m = re.search(r"^description:\s*(.*)$", head, re.M)
    return m.group(1) if m else ""


def entries(mem: Path) -> list[tuple[str, str, str, set[str]]]:
    archive = mem / "MEMORY-ARCHIVE.md"
    if not archive.is_file():
        return []
    index = mem / "MEMORY.md"
    loaded = set(LINK.findall(index.read_text(errors="replace"))) if index.is_file() else set()
    seen: set[str] = set()
    out = []
    for line in archive.read_text(errors="replace").split("\n"):
        m = ENTRY.match(line)
        if not m:
            continue
        f = m.group("file")
        if f in seen or f in loaded or not (mem / f).is_file():
            continue
        seen.add(f)
        text = " ".join((m.group("name"), m.group("hook"), description(mem / f)))
        out.append((f, m.group("name"), m.group("hook"), words(text)))
    return out


def recall(mem: Path, prompt: str, limit: int = LIMIT) -> list[Hit]:
    ents = entries(mem)
    if not ents:
        return []
    n = len(ents)
    df: dict[str, int] = {}
    for *_, ws in ents:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    q = words(prompt)
    if len(q) > MAX_PROMPT_WORDS:
        return []
    rare = max(RARE_MIN_DF, math.ceil(n * RARE_FRACTION))
    hits = []
    for f, name, hook, ws in ents:
        common = q & ws
        if sum(1 for w in common if df[w] <= rare) < MIN_RARE:
            continue
        score = sum(math.log(1 + n / df[w]) for w in common)
        hits.append(Hit(f, mem / f, name, hook, score))
    hits.sort(key=lambda h: (-h.score, h.file))
    return hits[:limit]


def render(hits: list[Hit]) -> str:
    if not hits:
        return ""
    lines = ["<memory-recall>",
             "Archived memories that match this prompt. They are not in the MEMORY.md index. "
             "Read a file before relying on it; ignore any that don't apply:"]
    lines += [f"- {h.path} — {h.name}: {h.hook}" for h in hits]
    lines.append("</memory-recall>")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--memory-dir", type=Path)
    ap.add_argument("--claude-hook", action="store_true")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args(argv)
    try:
        raw = sys.stdin.read()
        if a.claude_hook:
            doc = json.loads(raw)
            prompt = doc.get("prompt") or ""
            mem = a.memory_dir
            if mem is None and doc.get("transcript_path"):
                mem = Path(doc["transcript_path"]).parent / "memory"
        else:
            prompt, mem = raw, a.memory_dir
        if mem is None or not prompt.strip():
            return 0
        block = render(recall(mem, prompt, a.limit))
        if not block:
            return 0
        if a.claude_hook:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit", "additionalContext": block}}))
        else:
            print(block)
    except Exception as e:  # never block a prompt
        print(f"memory-recall: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
