---
name: secrets-hygiene
description: How credentials reach a running app without ever being committed to git. Use whenever a PR or manifest involves a password, token, API key, certificate, or anything sensitive. The rule is invariant across secret managers — never a literal credential value in a repo.
---

# secrets-hygiene

A credential value must never live in a git repo — not in a `Secret`, not in a
`ConfigMap`, not in an `env: value:`, not "just this once because the repo is
private." The repo references the secret; a secret manager holds the value and
materializes it at runtime.

## The invariant

Whatever the backend (External Secrets Operator, Vault Agent / VSO, Infisical,
sealed-secrets, SOPS, a cloud provider's secret manager + CSI driver), the
shape is always:

1. **The value lives in the secret manager**, added there first (out of band).
2. **The repo carries a *reference* object**, not the value — a CRD / encrypted
   blob / external-secret manifest that names *where* to fetch from.
3. **A controller (or CSI driver) materializes** a real `Secret` into the
   namespace at runtime.
4. **The workload binds that materialized secret** normally (`secretKeyRef`,
   mounted file, etc.).

The repo, its history, and its backups never contain a usable credential.

## Read the diff, not the title

A PR titled "harden secret handling" that *moves a credential from a ConfigMap
into a Secret manifest* has hardened nothing — a literal `stringData:` or
base64 `data:` value committed to git is plaintext-in-git regardless of the
resource kind. **Always read the diff.** If the diff contains a real credential
value, it's not hardening; it's a leak with better branding.

## Anti-patterns to refuse + redirect

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| `Secret` with literal `stringData: { key: VALUE }` | Plaintext in git | Reference object → secret manager |
| `Secret` with literal `data: { key: <base64> }` | Trivially decoded; still in git | Same |
| `ConfigMap` key holding a password/token | Plaintext in git, less defensible | Same |
| `env: { value: <literal> }` for a sensitive var | Bypasses the secret subsystem | Move to the manager + `secretKeyRef` |
| "Just commit it, the repo is private" | Private repos flip public; accounts get breached; backups leak | Use the manager; **rotate** anything ever committed |

## When the value WAS committed

If a real credential ever landed in git — even in a deleted commit, even in a
private repo — **rotate it.** Git history and backups are forever; redaction
isn't deletion. Rotation is the only fix; scrubbing history is cleanup, not
remediation.

## When to invoke

- A PR/manifest touches a `Secret`, a `ConfigMap` key with a sensitive name, or
  an `env: value:` with a sensitive value.
- An issue mentions hardening, secret management, credentials, leak, or rotate.
- A new app needs to reach an API (API key, DB password, OAuth token).

> Homelab note: the concrete backend here is the **InfisicalSecret** CR — see
> the `homelab-secrets` skill for the exact `hostAPI` / `projectSlug` / template
> invariants and reference manifests. This skill is the portable rule; that one
> is the homelab instance.
