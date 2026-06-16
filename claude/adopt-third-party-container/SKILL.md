---
name: adopt-third-party-container
description: Pre-flight investigation before drafting deployment config (Deployment/CronJob/Helm values/secret objects) for any third-party container image not already running in your environment. Forces source-read + sibling-survey instead of inferring from generic Docker/K8s conventions.
---

# adopt-third-party-container

## When to invoke

Before drafting any deployment manifest for a third-party container image not
already running in your environment. Fires whenever you're about to write
`image: <vendor>/<thing>` for the first time, or adapt an existing pattern
(e.g. a secret object) for a new app or namespace.

## Why

Inferring a container's runtime contract from generic Docker/Kubernetes
conventions is the single most expensive habit in deployment work. Vendor
images rarely follow the conventions you'd guess: the DB env var is `DB_TYPE`
not `DATABASE_TYPE`, the uid is `1100` not `1000`, the config is a mounted
file not env vars. Every one of those misses is a failed rollout and a
correction cycle — and every one was 30 seconds of `grep` or `docker inspect`
away. This skill forces the cheap investigation upfront, before a line of
YAML is written. (It was born from a 5-PR correction trail where *every* miss
— DB var name, uid, config-file location, secret wiring — was one `grep`
away.)

## Pre-flight checklist

Every step is **mandatory**. Each kills a specific class of guess.

1. **Clone upstream to `/tmp/upstream-<name>/`**:
   `git clone <upstream-repo-url> /tmp/upstream-<name>`
   Without source on disk, every env-var / uid claim is inference.

2. **Read the Dockerfile end-to-end**:
   Capture the literal `USER`, `ENTRYPOINT`, `WORKDIR`, `ENV HOME`. The uid
   and home dir are load-bearing for `securityContext` and volume ownership —
   and almost never the generic `1000` / `/home/app` you'd assume.

3. **Enumerate the real env-var contract**:
   `grep -rE '\$\{?[A-Z_]+\}?' /tmp/upstream-<name>/ > /tmp/upstream-<name>-envs.txt`
   Save it to disk. The actual names rarely match generic conventions (`DB_TYPE`
   vs `DATABASE_TYPE`; a mounted `rclone.conf` file vs synthesized
   `RCLONE_CONFIG_*` env vars).

4. **Read the README verbatim + check for `examples/` and `docker-compose*.yml`**:
   Author-blessed working config is the cheapest ground truth there is.

5. **Inspect the published image metadata**:
   `docker inspect <image>:<tag> --format '{{json .Config}}' | jq`
   Confirms runtime `User`, `Cmd`, `Env` defaults — and catches
   Dockerfile-vs-published-manifest drift.

6. **Survey your OWN existing manifests for the same SHAPE, not the same name**:
   If you already run a similar app, copy its working shape — especially for
   the cross-cutting concerns that are easiest to get wrong by inference: how
   secrets are wired (**your secret manager's object/CR**), image-pull
   credentials, storage classes, ingress/routes. `grep -rl '<image>'
   <your-config-repos>` — if it's already deployed somewhere, copy that shape
   rather than synthesizing it from generic docs.

7. **Write a failing integration test FIRST** (TDD): assert the env-var names,
   uid/gid, and mount paths discovered in steps 2–3 — before drafting the
   manifest.

## Done criteria

Before writing any deployment manifest, all of these must exist:

- [ ] `/tmp/upstream-<name>/` cloned, Dockerfile read
- [ ] `/tmp/upstream-<name>-envs.txt` saved
- [ ] `docker inspect` output captured for the pinned tag
- [ ] At least one sibling manifest identified (or "none found" recorded explicitly)
- [ ] Secret-wiring shape copied from an existing app (if the app needs secrets)
- [ ] Failing test committed asserting the discovered contract

## When to skip

Skip only when **both** are true:

1. The image is built from a repo you own (source already on disk), AND
2. A working deployment of the same image already exists to copy.

Then: copy the working manifest, run your standard pre/post upgrade validation
on the diff, and proceed. For any vendor image, any first deployment, or any
new secret object in a fresh namespace, the checklist is mandatory — the
30-second investigation always beats the multi-PR correction trail.

## Homelab specifics (skip in other environments)

In the homelab, the cross-cutting "shape" from step 6 is the **InfisicalSecret**
CR. Survey siblings and grep for the five invariant fields before wiring a new one:

```bash
kubectl get infisicalsecret -A -o yaml > /tmp/sibling-isecs.yaml
grep -E 'hostAPI|secretNamespace|projectSlug|secretsPath|includeAllSecrets' \
  /tmp/sibling-isecs.yaml | sort -u
```

Related homelab memory rules: `feedback_enumerate_schema_dont_infer` (the
parent rule), `feedback_mocks_encode_assumed_contracts`,
`feedback_infisical_root_path_plus_template`, `feedback_always_tdd`,
`feedback_three_repo_split_for_new_services`.
