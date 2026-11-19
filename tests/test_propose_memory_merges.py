#!/usr/bin/env python3
"""Tests for propose-memory-merges.py — find overlapping entries, have a local
model draft one merged entry per cluster, guard what it drafts. Never writes.

homelab#1929 AC3: the proposer leaves the memory dir byte-identical (the same
digest test as memory-audit's, homelab#1928 AC4), and every draft goes through
a deterministic guard — merge-memory-lines.py's own `validate`, the check the
applier runs before writing — so the model can't hand the applier anything it
would refuse.

The model is a fake Ollama `/api/chat` served from this process, so the
shipped script runs as a subprocess against a real HTTP endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "claude" / "memory-maintenance" / "bin"
SCRIPT = BIN / "propose-memory-merges.py"
APPLY = BIN / "merge-memory-lines.py"

POINTER = ("> {n} more hooks in [MEMORY-ARCHIVE.md](MEMORY-ARCHIVE.md) — files "
           "intact, recalled on relevance, not auto-loaded")

# name, file, hook, description
ENTRIES = [
    ("retry-backoff", "feedback_retry_backoff.md", "retries need exponential backoff",
     "Retries against flaky upstreams need exponential backoff with jitter"),
    ("dns-cache", "reference_dns_cache.md", "coredns cache ttl is thirty seconds",
     "Cluster resolver caches answers for thirty seconds"),
    ("retry-bounded", "feedback_retry_bounded.md", "bounded retries, exponential backoff",
     "Unbounded retries with exponential backoff and jitter still melt upstreams"),
    ("printer-ip", "project_printer_ip.md", "the printer lives at a fixed address",
     "Printer integration needs its static address kept"),
    ("retry-cap", "feedback_retry_cap.md", "cap retries at three, with jitter",
     "Cap exponential backoff retries at three attempts plus jitter"),
    ("gpu-node", "project_gpu_node.md", "gpu node drains want a cordon first",
     "Cordon the gpu node before any drain"),
]
ARCHIVED = ("retry-old", "feedback_retry_old.md", "old exponential backoff retries jitter",
            "Old exponential backoff retries jitter lesson")
RETRY = ["feedback_retry_backoff.md", "feedback_retry_bounded.md", "feedback_retry_cap.md"]


def entry_line(name, file, hook):
    return f"- [{name}]({file}) — {hook}"


def topic(name, desc, typ, extra=""):
    why = "\n**Why:** because.\n\n**How to apply:** do it.\n" if typ in (
        "feedback", "project") else ""
    return (f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: {typ}\n---\n"
            f"Lesson of {name}.{extra}\n{why}")


def draft(**over) -> dict:
    d = {
        "name": "retries",
        "file": "feedback_retries.md",
        "type": "feedback",
        "description": "Retry flaky upstreams with bounded exponential backoff and jitter",
        "body": ("Merged from feedback_retry_backoff.md, feedback_retry_bounded.md and "
                 "feedback_retry_cap.md.\n\nBack off exponentially with jitter; cap at 3.\n\n"
                 "**Why:** three lessons said one thing.\n\n**How to apply:** cap at 3.\n"),
        "index_line": "- [retries](feedback_retries.md) — bounded exponential backoff + jitter",
    }
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


def tree_digest(root: Path) -> dict[str, tuple[str, int]]:
    """Every file under root (.git included) → (sha256, mtime_ns)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = (hashlib.sha256(p.read_bytes()).hexdigest(),
                                             p.stat().st_mtime_ns)
        elif p.is_dir():
            out[str(p.relative_to(root)) + "/"] = ("dir", 0)
    return out


class FakeOllama:
    """Serves queued `message.content` strings; records every request body."""

    def __init__(self):
        self.replies: list[str] = []
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, **body})
                content = outer.replies.pop(0) if outer.replies else "{}"
                data = json.dumps({"message": {"role": "assistant",
                                               "content": content}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Fixture(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="propose-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.mem = self.root / "memory"
        self.mem.mkdir()
        lines = ["# Memory Index", ""]
        for name, file, hook, desc in ENTRIES:
            lines.append(entry_line(name, file, hook))
            (self.mem / file).write_text(topic(name, desc, file.split("_")[0]),
                                         encoding="utf-8")
        lines.append(POINTER.format(n=1))
        (self.mem / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        name, file, hook, desc = ARCHIVED
        (self.mem / file).write_text(topic(name, desc, "feedback"), encoding="utf-8")
        (self.mem / "MEMORY-ARCHIVE.md").write_text(
            "# Memory Archive (not auto-loaded)\n\n## Archived 2026-11-01 — old\n"
            + entry_line(name, file, hook) + "\n", encoding="utf-8")
        self.model = None

    def fake(self, *replies) -> FakeOllama:
        self.model = FakeOllama()
        self.addCleanup(self.model.close)
        self.model.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        return self.model

    def run_cli(self, *args, env=None):
        e = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        e.pop("OLLAMA_URL", None)
        if self.model:
            e["OLLAMA_URL"] = self.model.url
        e.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), "--memory-dir", str(self.mem),
                               *args], capture_output=True, text=True, env=e)

    def out(self, r) -> dict:
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        return json.loads(r.stdout)


# ------------------------------------------------------------------ clustering

class ClusterTest(Fixture):

    def test_finds_the_overlapping_entries_and_nothing_else(self):
        r = self.run_cli("--clusters-only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        clusters = self.out(r)["clusters"]
        self.assertEqual([c["sources"] for c in clusters], [RETRY])
        self.assertIn("exponential", clusters[0]["shared"])

    def test_archived_entries_are_not_candidates(self):
        r = self.run_cli("--clusters-only")
        self.assertNotIn("feedback_retry_old.md", r.stdout)

    def test_entry_with_missing_file_is_not_a_candidate(self):
        (self.mem / "feedback_retry_cap.md").unlink()
        clusters = self.out(self.run_cli("--clusters-only"))["clusters"]
        self.assertEqual([c["sources"] for c in clusters], [RETRY[:2]])

    def test_max_size_caps_a_cluster(self):
        clusters = self.out(self.run_cli("--clusters-only", "--max-size", "2"))["clusters"]
        self.assertEqual([len(c["sources"]) for c in clusters], [2])

    def test_min_shared_too_high_finds_none(self):
        r = self.run_cli("--clusters-only", "--min-shared", "9")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.out(r)["clusters"], [])

    def test_bodies_and_stop_words_do_not_link(self):
        # "Lesson" is in every body, but bodies are not clustering input, and
        # "with" is a stop word; neither links unrelated entries.
        clusters = self.out(self.run_cli("--clusters-only", "--min-shared", "1"))["clusters"]
        flat = [s for c in clusters for s in c["sources"]]
        self.assertNotIn("project_gpu_node.md", flat)

    def test_order_is_deterministic(self):
        a = self.run_cli("--clusters-only", "--min-shared", "1").stdout
        b = self.run_cli("--clusters-only", "--min-shared", "1").stdout
        self.assertEqual(a, b)

    def test_max_clusters_limits_output(self):
        with open(self.mem / "MEMORY.md", "a", encoding="utf-8") as f:
            for i in (1, 2):
                f.write(entry_line(f"gpu-{i}", f"project_gpu_{i}.md",
                                   "gpu node drain cordon first") + "\n")
                (self.mem / f"project_gpu_{i}.md").write_text(
                    topic(f"gpu-{i}", "Cordon the gpu node before any drain", "project"),
                    encoding="utf-8")
        both = self.out(self.run_cli("--clusters-only"))["clusters"]
        self.assertEqual(len(both), 2)
        one = self.out(self.run_cli("--clusters-only", "--max-clusters", "1"))["clusters"]
        self.assertEqual(one, both[:1])

    def test_no_index_is_usage_error(self):
        (self.mem / "MEMORY.md").unlink()
        self.assertEqual(self.run_cli("--clusters-only").returncode, 2)


# ------------------------------------------------------------- model + guard

class ProposeTest(Fixture):

    def test_guarded_draft_becomes_a_proposal_with_code_set_sources(self):
        self.fake(draft(sources=["made_up.md"]))
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [p] = self.out(r)["proposals"]
        self.assertEqual(p["sources"], RETRY)          # from the cluster, not the model
        self.assertEqual(p["index_line"], draft()["index_line"])
        self.assertEqual(self.out(r)["rejected"], [])

    def test_prompt_carries_every_source_file_and_the_schema(self):
        m = self.fake(draft())
        self.run_cli()
        [req] = m.requests
        self.assertEqual(req["path"], "/api/chat")
        self.assertFalse(req["stream"])
        self.assertIn("index_line", json.dumps(req["format"]))
        prompt = req["messages"][-1]["content"]
        for f in RETRY:
            self.assertIn(f, prompt)
            self.assertIn((self.mem / f).read_text(encoding="utf-8"), prompt)

    def test_model_name_from_flag(self):
        m = self.fake(draft())
        self.run_cli("--model", "tiny:1b")
        self.assertEqual(m.requests[0]["model"], "tiny:1b")

    def test_bad_draft_is_retried_once_with_the_problems(self):
        m = self.fake(draft(index_line="- [retries](feedback_retries.md) — " + "x" * 130),
                      draft())
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.out(r)["proposals"]), 1)
        self.assertEqual(len(m.requests), 2)
        self.assertIn("150", m.requests[1]["messages"][-1]["content"])

    def test_draft_still_bad_after_retry_is_rejected_with_reasons(self):
        missing = draft(body=draft()["body"].replace("feedback_retry_cap.md", "the cap one"))
        m = self.fake(missing, missing, draft())
        r = self.run_cli()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out = self.out(r)
        self.assertEqual(out["proposals"], [])
        [rej] = out["rejected"]
        self.assertEqual(rej["sources"], RETRY)
        self.assertTrue(any("feedback_retry_cap.md" in p for p in rej["problems"]))
        self.assertEqual(len(m.requests), 2)

    def test_non_json_reply_is_a_guard_failure(self):
        self.fake("not json at all", "still not")
        out = self.out(self.run_cli())
        self.assertTrue(any("JSON" in p for p in out["rejected"][0]["problems"]))

    def test_json_that_is_not_an_object_is_a_guard_failure(self):
        self.fake("[1, 2]", "[1, 2]")
        out = self.out(self.run_cli())
        self.assertTrue(any("object" in p for p in out["rejected"][0]["problems"]))

    def test_name_collision_is_caught_by_the_guard(self):
        self.fake(draft(name="dns-cache", index_line="- [dns-cache](feedback_retries.md) — x"),
                  draft(name="dns-cache", index_line="- [dns-cache](feedback_retries.md) — x"))
        out = self.out(self.run_cli())
        self.assertTrue(any("dns-cache" in p for p in out["rejected"][0]["problems"]))

    def test_cluster_too_large_to_draft_is_rejected_without_a_model_call(self):
        big = "x" * 9000
        for f in RETRY:
            p = self.mem / f
            p.write_text(p.read_text(encoding="utf-8") + big, encoding="utf-8")
        m = self.fake(draft())
        r = self.run_cli()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("too large", " ".join(self.out(r)["rejected"][0]["problems"]))
        self.assertEqual(m.requests, [])

    def test_no_clusters_is_exit_1_with_no_model_call(self):
        m = self.fake(draft())
        r = self.run_cli("--min-shared", "9")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.out(r), {"proposals": [], "rejected": []})
        self.assertEqual(m.requests, [])

    def test_unreachable_model_is_exit_3(self):
        r = self.run_cli(env={"OLLAMA_URL": "http://127.0.0.1:9"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("model", r.stderr)

    def test_no_model_url_is_usage_error(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("OLLAMA_URL", r.stderr)

    def test_model_url_flag_overrides_env(self):
        m = self.fake(draft())
        r = self.run_cli("--model-url", m.url, env={"OLLAMA_URL": "http://127.0.0.1:9"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_output_applies_cleanly_with_the_applier_dry_run(self):
        self.fake(draft())
        r = self.run_cli()
        prop = self.root / "proposal.json"
        prop.write_text(r.stdout, encoding="utf-8")
        a = subprocess.run([sys.executable, str(APPLY), "--memory-dir", str(self.mem),
                            "--backup-dir", str(self.root / "bak"),
                            "--proposal", str(prop), "--dry-run"],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)


# ------------------------------------------------------------------ read-only

class ReadOnlyTest(Fixture):

    def test_memory_dir_is_byte_identical_after_every_mode(self):
        (self.mem / ".git").mkdir()
        (self.mem / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        before = tree_digest(self.mem)
        self.fake(draft(), "bad", "bad")
        runs = [("--clusters-only",), (), ()]           # ok draft, then rejected
        for args in runs:
            self.run_cli(*args)
            self.assertEqual(tree_digest(self.mem), before, args)
        self.run_cli(env={"OLLAMA_URL": "http://127.0.0.1:9"})
        self.assertEqual(tree_digest(self.mem), before, "model down")

    def test_nothing_appears_next_to_the_memory_dir(self):
        before = tree_digest(self.root)
        self.fake(draft())
        self.run_cli()
        self.assertEqual(tree_digest(self.root), before)


if __name__ == "__main__":
    unittest.main()
