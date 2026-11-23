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

A second tier runs after the first and adds what it missed: BM25 over the
whole topic file (index line and description counted twice, then the body),
kept only at score >= BODY_MIN_SCORE. It catches a prompt that uses the
memory's own words rather than its index line. Its gate is a score because
body text makes every word more common, and the rare-word count then rejects
nearly everything (1 of 14 targets). Measured 2026-11-23 on the 373-entry
archive: 8 of 14 hand-written archived targets (first tier alone: 4), and on
30 stand-in prompts it fired 4 times, every entry relevant. Scores below 17
were mostly noise. Same length cap; first-tier hits are listed first.

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
from collections import Counter
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
BODY_MIN_SCORE = 17.0  # second tier: whole-file BM25 score a hit must reach
BM25_K1, BM25_B = 1.2, 0.75
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


def tokens(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text.lower()):
        w = w.strip(".+#-")
        if len(w) < MIN_LEN or w in STOP or w.isdigit():
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def words(text: str) -> set[str]:
    return set(tokens(text))


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


def body(path: Path) -> str:
    """The topic file after its frontmatter."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        text = parts[1] if len(parts) > 1 else ""
    return text


def entries(mem: Path) -> list[tuple[str, str, str, set[str], Counter]]:
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
        head = tokens(" ".join((m.group("name"), m.group("hook"), description(mem / f))))
        # The second tier's document: the head counts twice, like a title field.
        doc = Counter(head * 2 + tokens(body(mem / f)))
        out.append((f, m.group("name"), m.group("hook"), set(head), doc))
    return out


def recall(mem: Path, prompt: str, limit: int = LIMIT) -> list[Hit]:
    ents = entries(mem)
    if not ents:
        return []
    n = len(ents)
    df: dict[str, int] = {}
    for _, _, _, ws, _ in ents:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    q = words(prompt)
    if len(q) > MAX_PROMPT_WORDS:
        return []
    rare = max(RARE_MIN_DF, math.ceil(n * RARE_FRACTION))
    hits = []
    for f, name, hook, ws, _ in ents:
        common = q & ws
        if sum(1 for w in common if df[w] <= rare) < MIN_RARE:
            continue
        score = sum(math.log(1 + n / df[w]) for w in common)
        hits.append(Hit(f, mem / f, name, hook, score))
    hits.sort(key=lambda h: (-h.score, h.file))
    # Second tier, after the first: BM25 over the whole file, kept only above
    # a high score. It finds prompts that use a memory's own words rather than
    # its index line. Its gate is a score, not the rare-word count: body text
    # makes every word more common, and that count then rejects nearly all.
    first = {h.file for h in hits}
    body_hits = [h for h in bm25(mem, ents, q) if h.file not in first and h.score >= BODY_MIN_SCORE]
    body_hits.sort(key=lambda h: (-h.score, h.file))
    return (hits + body_hits)[:limit]


def bm25(mem: Path, ents: list, q: set[str]) -> list[Hit]:
    n = len(ents)
    avg = sum(sum(doc.values()) for *_, doc in ents) / n or 1.0
    df: Counter = Counter(w for *_, doc in ents for w in doc)
    out = []
    for f, name, hook, _, doc in ents:
        length = sum(doc.values())
        score = 0.0
        for w in q:
            tf = doc.get(w, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * tf * (BM25_K1 + 1) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avg))
        if score:
            out.append(Hit(f, mem / f, name, hook, score))
    return out


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
