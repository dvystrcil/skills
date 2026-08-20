---
name: tdd-artifacts
description: Extends the tdd skill to work whose artifact cannot be unit-tested in-process — workflow JSON, K8s manifests, CI YAML, Alertmanager routing, dashboards — and to guards retrofitted onto code that already exists. In both cases RED is not free, so you must manufacture the failing state before trusting the guard. Use alongside tdd, not instead of it.
---

# tdd-artifacts — making RED reachable

The `tdd` skill's loop is right and this does not replace it. Use both: `tdd`
for how to design tests, this for the two cases where its RED step has no
natural form and therefore gets silently skipped.

```
tdd            RED is free — write the test first, watch it fail, implement.
tdd-artifacts  RED must be MANUFACTURED. Two cases below.
```

## Case 1 — the artifact is config, not code

Workflow JSON, Helm values, kustomize overlays, `PrometheusRule`, Alertmanager
routes, GitHub Actions YAML, dashboards. There is no function to call, so
"write a failing test" has no obvious form, so the loop quietly does not run.

This is where defects concentrate, because the reviewable surface and the
executable surface are different things. A 2026-08-19 homelab sweep found seven
defects; every one lived in config, and **every one survived a careful reading
of its diff while none survived being run once**:

- 13 JSON bodies interpolating `$json` outside `{{ }}` — never evaluated, so the
  body never parsed. One watcher had failed daily for weeks.
- 6 webhook nodes missing `webhookId` — registered under a malformed path, 500.
- A responder building `{"count": undefined}` — invalid JSON, aborting every run.

**RED for config is a static check that fails against the current tree.**

1. Write the check. Run it. **It must report the defect you already know is
   there.** If it reports nothing, the check is wrong — not the artifact.
2. Fix the artifact. Re-run. It must go quiet.
3. Wire the check into CI, as **its own step**, not as a side effect of another
   command. A linter exercised only indirectly can silently stop checking.

### Do not assume the vendor's validator covers it

Check what it actually inspects. In the same sweep, the ecosystem's own
validator — on its `strict` profile, with expression validation explicitly
enabled — returned this for a workflow that had been broken for weeks:

```
"valid": true,  "errorCount": 0,  "expressionsValidated": 0
```

It validated **zero** expressions. A validator that checks nothing returns the
same green as one that checks everything. Confirm it fails on a known-bad input
before relying on it — the same rule as for your own guards.

## Case 2 — a guard retrofitted onto something that already works

Classic TDD gets RED for free because the test precedes the code. A regression
guard added to an existing artifact never fails on the way in, so it is adopted
green and believed. **A guard nobody has seen fail is indistinguishable from a
guard that cannot fail.**

Manufacture RED by mutation:

1. Inject the defect the guard exists to catch — ideally the historical one,
   verbatim.
2. Assert the guard fires. Note the counts (`pass 7 / fail 1`).
3. Restore. Assert it goes quiet and the tree is byte-identical.

Doing this by hand catches real problems, but only when someone remembers.
Prefer encoding it: keep a mutation per rule in the test suite so CI re-proves
every guard on every run.

```js
for (const [ruleId, mutate] of Object.entries(MUTATIONS)) {
  test(`rule "${ruleId}" fires when its historical bug is re-injected`, () => {
    const tree = loadRealArtifacts().map(clone);
    mutate(tree);
    assert.ok(lint(tree, { rules: [ruleId] }).length > 0,
      `"${ruleId}" did not fire on its own mutation — it cannot fail, so it proves nothing`);
  });
}

test('every rule has a mutation proving it bites', () => {
  assert.deepEqual(RULES.map(r => r.id).filter(id => !(id in MUTATIONS)), []);
});
```

That last meta-guard is the load-bearing one: it makes shipping an unproven rule
impossible rather than merely discouraged.

## Guard the guard against vacuous truth

A check that matches nothing passes every assertion. Two failures to avoid:

- **The glob found no files.** Assert a non-trivial count first.
- **The rule over-reaches.** A rule firing on correct artifacts gets disabled,
  and then covers nothing. In the same sweep, a `\n` check flagged legitimate JS
  escapes inside expressions, and a uniform placeholder broke on a body mixing
  `"{{ x }}"` with a bare `{{ x }}`. Both were false positives found by running
  the rule across the whole corpus — do that before trusting a new rule.

## What this still will not catch

Semantic drift: an artifact that is internally consistent, does something real,
and is not the thing its documentation claims. In the same sweep a monitoring
canary had, since inception, stamped a heartbeat proving only that the scheduler
ran — while two documents said it exercised the alert path. No linter reaches
that.

The question that does, for anything claiming to observe something else:

> **If I killed this component right now, which file stops changing?**

If the answer is "none", it is not covered, whatever the diagram says.

## Checklist

```
[ ] The check reported the defect BEFORE the fix (real RED, not assumed)
[ ] Every guard has a mutation proving it can fail
[ ] A meta-test forbids adding a guard without one
[ ] The check asserts it found a non-trivial number of artifacts
[ ] The rule was run across the whole corpus to flush out false positives
[ ] CI runs the check as its own step, not as a side effect
[ ] The vendor's validator was confirmed to fail on known-bad input
```

## See also

- `tdd` — the loop this extends; use it for test design and the red/green cadence
- `change-validation` — identical suite before and after, then diff
