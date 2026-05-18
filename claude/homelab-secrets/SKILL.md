---
name: homelab-secrets
description: How the homelab handles credentials. Use whenever you see a PR or manifest involving passwords, tokens, API keys, certificates, or anything else sensitive. The pattern is InfisicalSecret CR — NEVER literal `stringData:`/`data:` in a Secret manifest committed to a repo.
---

# Homelab Secrets

The homelab's One True Way for any credential reaching a pod is the **InfisicalSecret** CRD: a controller pulls the secret from a self-hosted Infisical instance and materializes a Kubernetes Secret at runtime. The repo never carries the secret value.

If you see a PR claiming to "harden" something by moving a credential from ConfigMap into a Secret manifest — **read the diff, not the title**. A literal `stringData:` or `data:` value committed to a repo is plaintext-in-git regardless of resource kind. The homelab caught exactly this anti-pattern in `dvystrcil/libreoffice#1` and fixed it in `#2` using the pattern below.

## The pattern

Every secret-bearing app in the homelab uses this shape. Reference example: [`dvystrcil/n8n-workflow/base/n8n-infisical-secret.yaml`](https://github.com/dvystrcil/n8n-workflow/blob/main/base/n8n-infisical-secret.yaml).

```yaml
apiVersion: secrets.infisical.com/v1alpha1
kind: InfisicalSecret
metadata:
  name: <app>-infisical-secret
  namespace: <app-namespace>
spec:
  hostAPI: https://infisical.sirddail.net/api
  resyncInterval: 60                              # rotations propagate in ~60s
  authentication:
    universalAuth:
      secretsScope:
        projectSlug: homelab-bz-gt                # the homelab Infisical project
        envSlug: prod                             # always 'prod' for the live cluster
        secretsPath: "/"
        recursive: false
      credentialsRef:
        secretName: infisical-machine-identity
        secretNamespace: infisical-operator
  managedSecretReference:
    secretName: <app>-secrets                     # convention: <app>-secrets (plural)
    secretNamespace: <app-namespace>
    creationPolicy: Owner
    template:
      includeAllSecrets: false
      data:
        # Keys here MUST exist in Infisical at projectSlug/envSlug above.
        # If a key is missing, the InfisicalSecret CR stays in the Failed
        # state and the managed Secret won't exist — pods that bind it
        # CrashLoopBackOff.
        API_KEY: "{{ .API_KEY.Value }}"
        DB_PASSWORD: "{{ .DB_PASSWORD.Value }}"
```

The Deployment then references the managed Secret normally:

```yaml
        env:
        - name: API_KEY
          valueFrom:
            secretKeyRef:
              name: <app>-secrets
              key: API_KEY
```

## Conventions

| Field | Value | Why |
|---|---|---|
| `hostAPI` | `https://infisical.sirddail.net/api` | Cluster-hosted Infisical instance |
| `projectSlug` | `homelab-bz-gt` | Single project for all homelab apps |
| `envSlug` | `prod` | We don't run a dev/staging tier in the homelab |
| `credentialsRef` | `infisical-machine-identity` / `infisical-operator` | Shared machine identity; deployed by the Infisical operator chart |
| `managedSecretReference.secretName` | `<app>-secrets` | Plural convention. Examples: `n8n-secrets`, `redis-secrets`, `libreoffice-secrets` |
| `resyncInterval` | `60` | Compromise between freshness and Infisical API load |
| `creationPolicy` | `Owner` | The InfisicalSecret CR owns the managed Secret; deletion of the CR cleans up the Secret |

## Operator workflow

### Creating a new secret-bearing app

1. **Add the secret value(s) to Infisical first.** Open the Infisical UI, project `homelab-bz-gt`, env `prod`, add the keys. Without this, the InfisicalSecret CR stays Failed and the pod can't start.
2. Write the InfisicalSecret manifest at `<app>-repo/base/<app>-infisical-secret.yaml`.
3. Add it to `base/kustomization.yaml`'s `resources:` list.
4. Reference the managed Secret in the Deployment via `secretKeyRef`.
5. Argo syncs, the controller resolves Infisical, the managed Secret appears in the namespace, the pod starts.

### Rotating a credential

1. Edit the value in the Infisical UI.
2. Wait ~60s (`resyncInterval`). The controller re-fetches and updates the managed Secret.
3. If the consuming pod doesn't have `reloader.stakater.com/auto: "true"` annotation, restart it manually: `kubectl -n <ns> rollout restart deploy/<deploy>`.

### Removing the InfisicalSecret

`creationPolicy: Owner` means deleting the InfisicalSecret CR deletes the managed Secret too. Always delete the InfisicalSecret first, then the consuming Deployment — not the other way around (the Deployment would error on missing Secret before being deleted).

## Anti-patterns to refuse + redirect

When reviewing a PR or writing a manifest, refuse these patterns and propose the InfisicalSecret shape instead:

| Anti-pattern | Why it's wrong | What to do |
|---|---|---|
| `Secret` with literal `stringData: { key: VALUE }` | Plaintext-in-git | Replace with InfisicalSecret |
| `Secret` with literal `data: { key: <base64> }` | Trivially decoded; still in git | Replace with InfisicalSecret |
| ConfigMap key holding a password / token | Plaintext-in-git, less defensible | Replace with InfisicalSecret |
| `env: { value: <literal> }` for sensitive var | Bypasses Secret subsystem entirely | Move to InfisicalSecret + `secretKeyRef` |
| Sealed-secrets (bitnami) | Different model; we don't use it | Use InfisicalSecret instead |
| "Just commit it, the repo is private" | Private repos flip public (homelab#133 did exactly this 2026-05-18); collaborator accounts get breached; backups leak | Use InfisicalSecret; rotate the credential if it was ever committed |

When you see "PR title says hardening", read the diff. If the diff contains a literal credential value, it's not hardening regardless of the kind of resource holding it.

## Apps currently using the pattern (2026-05-18)

Use any of these as a template; all 12 follow the same shape:

- `dvystrcil/n8n-workflow/base/n8n-infisical-secret.yaml` (reference example — most fields)
- `dvystrcil/redis/redis-infisical-secret.yaml`
- `dvystrcil/open-terminal/base/open-terminal-infisical-secret.yaml`
- `dvystrcil/open-terminal/base/harbor-pull-infisical-secret.yaml` (image-pull secrets case)
- `dvystrcil/open-webui/base/owui-infisical-secret.yaml`
- `dvystrcil/tailscale/base/infisical-secret.yaml`
- `dvystrcil/stable-diffution-webui-rcom/k8s/sd-webui-rcom-infisical-secret.yaml`
- `dvystrcil/homelab/arc-runner/infisical-secret.yaml`
- `dvystrcil/wallos/base/wallos-infisical-secrets.yaml`
- `dvystrcil/mealie-mcp-docker/kustomize/infisical-secret.yaml`
- `dvystrcil/kroger-mcp-docker/kustomize/infisical-secret.yaml`
- `dvystrcil/libreoffice/base/libreoffice-infisical-secret.yaml` (pending merge as of 2026-05-18, PR #2)

## Known gotchas

- **homelab#6** — `additionalAnnotations` field on managed Secrets isn't supported by the controller. Set annotations on the InfisicalSecret CR; they don't propagate to the managed Secret.
- **homelab#7** — apps not yet on the pattern. Open follow-ups; if you're working on one of them, add the InfisicalSecret as part of the same change.
- **Missing keys cause CrashLoopBackOff** — if you add a key to the InfisicalSecret template but forget to add it to Infisical, the controller refuses to create the managed Secret; the pod crashloops on `secret "X" not found`. Always add to Infisical first.
- **Image-pull secrets are also InfisicalSecret** — see `open-terminal/base/harbor-pull-infisical-secret.yaml` for the `kubernetes.io/dockerconfigjson` shape; the managed Secret type field needs to be set explicitly.

## When the AI should invoke this skill

- A PR or manifest involves a `Secret`, `ConfigMap` key with sensitive name (password/token/key/cert/credential), or `env: { value: }` with a sensitive value.
- An issue mentions "hardening", "secret management", "credentials", "leak", or "rotate".
- A new app is being onboarded and needs to reach an API (API_KEY, DB_PASSWORD, OAUTH_TOKEN, etc.).
- An existing app needs a new credential added — check its existing InfisicalSecret manifest and extend the template's `data:` block.

## Related

- Memory rule: `feedback_secret_manifest_in_repo_is_not_hardening.md`
- Issue: `dvystrcil/homelab#7` (migration tracker)
- Issue: `dvystrcil/homelab#6` (additionalAnnotations gotcha)
- Trigger event: `dvystrcil/libreoffice#1` (anti-pattern) → `#2` (correct pattern)
