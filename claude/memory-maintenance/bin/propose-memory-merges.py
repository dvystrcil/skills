#!/usr/bin/env python3
"""Propose merges of overlapping memory entries. Read-only (homelab#1929).

    propose-memory-merges.py --memory-dir M --clusters-only
    OLLAMA_URL=http://host:11434 propose-memory-merges.py --memory-dir M > proposal.json

It never writes: not in the memory dir, not next to it. Output is JSON on
stdout; a one-line summary per cluster goes to stderr.

1. Cluster (no model). Index entries (not archived ones, and only those whose
   file exists) become word sets: link text, hook, file name (minus its type prefix) and the topic
   file's `description:`. Words are ≥ 4 chars, minus stop words, and only
   rare ones count: in at most max(3, 5%) of entries. Pairs sharing at least
   --min-shared rare words join, strongest first, while a cluster stays
   ≤ --max-size. Bodies are not used: every body shares boilerplate.
2. Draft (local model, Ollama /api/chat, JSON-schema output). One call per
   cluster with every source file's full text. A cluster over 24,000 chars
   is rejected without a call.
3. Guard. The draft gets the cluster's sources (set by code, never by the
   model) and goes through merge-memory-lines.py's `validate()`, the check
   the applier refuses on: schema, every source named in the body, the
   index line ≤ 150 chars in `- [name](file.md) — hook` form, no name or
   file collision, the new file's shape. A refused draft is retried once
   with the problems; refused again, it is listed under `rejected`.

Output: `{"clusters": [{"sources", "shared"}]}` with --clusters-only, else
`{"proposals": [...], "rejected": [{"sources", "problems"}]}` — the file
merge-memory-lines.py --proposal takes.

Env: OLLAMA_URL (or --model-url; required unless --clusters-only),
MEMORY_MERGE_MODEL (default qwen3-coder-next:latest).
Exit: 0 at least one cluster / proposal; 1 none; 2 usage or no MEMORY.md;
3 model unreachable or malformed reply.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("merge_memory_lines",
                                               HERE / "merge-memory-lines.py")
merge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge)

EXIT_FOUND, EXIT_NONE, EXIT_USAGE, EXIT_MODEL = 0, 1, 2, 3
MAX_CHARS = 24000
WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset("""
about after again already also always because been before being could does done
dont each even every exact from have here into just more most must need needs
never only other over should since some still such than that them then there
they this were what when which while with would your
""".split())
DRAFT_KEYS = set(merge.REQUIRED) - {"sources"} | set(merge.OPTIONAL)
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "file": {"type": "string"},
        "type": {"type": "string", "enum": list(merge.cmf.TYPES)},
        "description": {"type": "string"}, "body": {"type": "string"},
        "index_line": {"type": "string"}, "rationale": {"type": "string"},
    },
    "required": ["name", "file", "type", "description", "body", "index_line"],
}
SYSTEM = f"""You merge overlapping entries of an agent's memory into ONE entry.
Keep every lesson, fact, date, number, link and caveat from every source; drop
only repetition. Reply with one JSON object:
- name: short kebab-case link text for the merged entry, not one of the sources' names
- file: `<type>_<snake_case>.md`, a new name
- type: user, feedback, project or reference (the sources' type if they agree)
- description: one line saying what the merged memory is about
- body: the merged markdown text, no frontmatter. Name every source file
  (e.g. "Merged from a.md, b.md and c.md."). A feedback or project body needs a
  `**Why:**` line and a `**How to apply:**` line, each with text.
- index_line: exactly `- [name](file) — hook`, at most {merge.MAX_INDEX_LINE} characters
- rationale: one sentence on why these belong together"""


class ModelError(Exception):
    pass


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if len(w) >= 4 and w not in STOP}


def candidates(mem: Path) -> list[tuple[str, str, set[str]]]:
    """(file, index line, word set) for each index entry whose file exists."""
    out = []
    for name, target, line in merge.entries((mem / merge.INDEX).read_text(encoding="utf-8")):
        f = mem / target
        if not merge.BARE_MD.match(target) or not f.is_file():
            continue
        parsed = merge.cmf.frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        desc = parsed[0].get("description", "") if parsed else ""
        hook = line.split(" — ", 1)[1] if " — " in line else ""
        stem = target[:-3].split("_", 1)[-1]          # the type prefix is not a topic
        out.append((target, line, words(" ".join((name, hook, stem, desc)))))
    return out


def clusters(cands, min_shared: int, max_size: int) -> list[dict]:
    n = len(cands)
    df: dict[str, int] = {}
    for _, _, ws in cands:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    limit = max(3, math.ceil(n * 0.05))
    rare = [{w for w in ws if df[w] <= limit} for _, _, ws in cands]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            shared = rare[i] & rare[j]
            if len(shared) >= min_shared:
                pairs.append((-len(shared), -len(shared) / len(rare[i] | rare[j]), i, j))
    parent = list(range(n))
    size = [1] * n

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for _, _, i, j in sorted(pairs):
        ri, rj = root(i), root(j)
        if ri != rj and size[ri] + size[rj] <= max_size:
            parent[rj] = ri
            size[ri] += size[rj]
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        seen: dict[str, int] = {}
        for i in members:
            for w in rare[i]:
                seen[w] = seen.get(w, 0) + 1
        shared = sorted(w for w, c in seen.items() if c > 1)
        out.append({"sources": [cands[i][0] for i in members], "shared": shared,
                    "_key": (-len(members), -len(shared), members[0])})
    out.sort(key=lambda c: c["_key"])
    for c in out:
        del c["_key"]
    return out


def chat(url: str, model: str, messages: list[dict]) -> str:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps({
            "model": model, "messages": messages, "stream": False, "format": SCHEMA,
            "think": False,
            "options": {"temperature": 0.2, "top_p": 0.8, "top_k": 20,
                        "num_ctx": 16384, "num_predict": 4000},
        }).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["message"]["content"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        raise ModelError(f"model call to {url} failed: {e}")


def guard(content: str, sources: list[str], mem: Path) -> tuple[dict | None, list[str]]:
    try:
        d = json.loads(content)
    except ValueError as e:
        return None, [f"model output is not JSON: {e}"]
    if not isinstance(d, dict):
        return None, ["model output is not a JSON object"]
    p = {k: v for k, v in d.items() if k in DRAFT_KEYS}
    p["sources"] = list(sources)
    problems = merge.validate(p, mem)
    return (None if problems else p), problems


def prompt(mem: Path, c: dict, lines: dict[str, str]) -> str:
    parts = [f"Merge these {len(c['sources'])} memory entries into one."]
    for s in c["sources"]:
        text = (mem / s).read_text(encoding="utf-8", errors="replace")
        parts.append(f"### {s}\nindex line: {lines[s]}\n````\n{text}\n````")
    return "\n\n".join(parts)


def propose(mem: Path, c: dict, lines: dict[str, str], url: str, model: str
            ) -> tuple[dict | None, list[str]]:
    total = sum(len((mem / s).read_text(encoding="utf-8", errors="replace"))
                for s in c["sources"])
    if total > MAX_CHARS:
        return None, [f"cluster too large to draft: {total} chars > {MAX_CHARS}"]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt(mem, c, lines)}]
    content = chat(url, model, messages)
    p, problems = guard(content, c["sources"], mem)
    if p is None:
        messages += [{"role": "assistant", "content": content},
                     {"role": "user", "content": "That draft was refused:\n- "
                      + "\n- ".join(problems) + "\nReply with the corrected JSON object."}]
        p, problems = guard(chat(url, model, messages), c["sources"], mem)
    return p, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--memory-dir", type=Path, required=True)
    ap.add_argument("--clusters-only", action="store_true", help="no model call")
    ap.add_argument("--min-shared", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=5)
    ap.add_argument("--max-clusters", type=int, default=5)
    ap.add_argument("--model-url", default=os.environ.get("OLLAMA_URL"))
    ap.add_argument("--model", default=os.environ.get("MEMORY_MERGE_MODEL",
                                                      "qwen3-coder-next:latest"))
    a = ap.parse_args(argv)

    mem = a.memory_dir.resolve()
    if not (mem / merge.INDEX).is_file():
        print(f"no {merge.INDEX} in {mem}", file=sys.stderr)
        return EXIT_USAGE
    if not a.clusters_only and not a.model_url:
        print("no model: set OLLAMA_URL or pass --model-url (or use --clusters-only)",
              file=sys.stderr)
        return EXIT_USAGE

    cands = candidates(mem)
    found = clusters(cands, a.min_shared, a.max_size)[:a.max_clusters]
    if a.clusters_only:
        print(json.dumps({"clusters": found}, indent=2, ensure_ascii=False))
        return EXIT_FOUND if found else EXIT_NONE

    lines = {f: l for f, l, _ in cands}
    out: dict[str, list] = {"proposals": [], "rejected": []}
    try:
        for n, c in enumerate(found, 1):
            p, problems = propose(mem, c, lines, a.model_url, a.model)
            verdict = "proposed" if p else "rejected"
            print(f"cluster {n}: {', '.join(c['sources'])} → {verdict}", file=sys.stderr)
            if p:
                out["proposals"].append(p)
            else:
                out["rejected"].append({"sources": c["sources"], "problems": problems})
    except ModelError as e:
        print(str(e), file=sys.stderr)
        return EXIT_MODEL
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_FOUND if out["proposals"] else EXIT_NONE


if __name__ == "__main__":
    sys.exit(main())
