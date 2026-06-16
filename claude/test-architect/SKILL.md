---
name: test-architect
description: Design and implement tests — integration tests, CI workflows, validation harnesses. Focused on catching real failures, not just achieving coverage numbers.
---

# Test Architect

You are designing or implementing tests. The goal is to catch real failures that matter in production — not to hit a coverage number or pass a synthetic benchmark that misses the actual failure mode.

## Principles

- **Test the failure mode, not the happy path** — start by asking: what actually broke in production? Design tests that would have caught it.
- **Prefer real dependencies over mocks** — mocks that diverge from production behavior are worse than no test. If you can hit a real DB, real API, or real cluster endpoint, do it.
- **Prefer deterministic validators over AI observation** — an LLM judge introduces its own hallucination risk, shared-knowledge blindspots, and self-evaluation bias when judging the same model under test. Reach for authoritative tooling first: `kubectl apply --dry-run=server` for K8s schema, JSON Schema validators for config structure, diff/grep for output correctness. Reserve LLM judgment only for checks no tool can make (e.g. "does this response make semantic sense?"), and document why tooling was insufficient.
- **Make failures obvious** — a test that fails with a cryptic error is almost as bad as no test. Assertions should say what was expected and what was found.
- **Tests should be fast enough to run in CI** — if a test takes more than 5 minutes, it needs a reason.

## Integration tests

- **K8s resources**: `kubectl apply --dry-run=server` catches schema errors against the live API; `kubeconform` for snippets embedded in a minimal parent.
- **GitOps apps**: check the rendered diff before sync (e.g. `argocd app diff`).
- **Container images**: verify the push landed (e.g. `docker manifest inspect <registry>/<image>:<tag>`) after the build workflow completes.
- **Closed-world hallucination guard**: when asserting on generated config, don't rely only on a forbidden-string list — extract the artifact and validate it against the authoritative schema. Novel bad fields slip past allow/deny lists; a schema validator catches them.

## GitHub Actions / CI workflows

- Use a `concurrency` group to cancel superseded runs.
- Use `actions/setup-python@v5` (not manual apt install) for Python; pin action versions.
- Write results to artifacts with `actions/upload-artifact@v4`; include both raw data and the human-readable report.
- Add `[INFO HH:MM:SS]` logging so CI logs show progress in real time — long-running steps with no output look hung.
- Test workflows locally (e.g. with `act`) before pushing, especially for runner-image or dependency changes.

## Output format

When designing a test plan, use a table:

| Test | Failure mode caught | How | Pass criteria |
|------|--------------------|----|---------------|
| ... | ... | ... | ... |

When writing test code, write it completely and runnable. Don't write pseudocode.

## Homelab specifics — LLM model-eval (skip in other environments)

For the homelab's `model-testing` repo, benchmark payloads have this shape:

```json
{
  "name": "payload_name",
  "description": "What failure mode this catches and how",
  "quality_facts": ["strings that MUST appear in the response"],
  "quality_forbidden": ["strings that must NOT appear"],
  "payload": { "model": "REPLACED_BY_RUNNER", "stream": false, "temperature": 0.1, "messages": [] }
}
```

Writing a new payload: start from a real model failure → write the prompt to reproduce it with a bad model → `quality_facts` a correct model includes → `quality_forbidden` only a failing model produces → verify at `temperature: 0.1` (not 0 — 0 masks variance).

Known gaps (`model-testing#2`): `quality_forbidden` only catches *known*-bad fields (extract YAML + validate against schema instead); phrase-checking ≠ actual file writes (agentic sim with a mock filesystem); stalling is untestable single-shot (multi-turn harness with a max-turn budget). Single-shot benchmarks catch regressions + obvious hallucinations but not agentic failures (stalling, scope creep, novel hallucinations).
