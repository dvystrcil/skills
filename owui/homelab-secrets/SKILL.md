---
name: "Homelab Secrets"
description: "How the homelab handles credentials. Use whenever you see a PR or manifest involving passwords, tokens, API keys, certificates — anything sensitive. Pattern is InfisicalSecret CR, NEVER literal values in a Secret manifest committed to a repo."
tags: ["homelab", "kubernetes", "secrets", "infisical", "security", "gitops"]
scope: "complex"
---

# Homelab Secrets

The homelab's One True Way for any credential reaching a pod is the **InfisicalSecret** CRD: a controller pulls the secret from a self-hosted Infisical instance and materializes a Kubernetes Secret at runtime. The repo never carries the secret value.

**Read PR diffs, not titles.** A PR claiming to "harden" something by moving a credential from ConfigMap into a Secret manifest is still plaintext-in-git if the Secret has literal `stringData:` or `data:` values. The homelab hit exactly this anti-pattern in `dvystrcil/libreoffice#1` and fixed it in `#2`.

## Template

Reference example: `dvystrcil/n8n-workflow/base/n8n-infisical-secret.yaml`.

```yaml
apiVersion: secrets.infisical.com/v1alpha1
kind: InfisicalSecret
metadata:
  name: <app>-infisical-secret
  namespace: <app-namespace>
spec:
  hostAPI: https://infisical.sirddail.net/api
  resyncInterval: 60
  authentication:
    universalAuth:
      secretsScope:
        projectSlug: homelab-bz-gt
        envSlug: prod
        secretsPath: "/"
        recursive: false
      credentialsRef:
        secretName: infisical-machine-identity
        secretNamespace: infisical-operator
  managedSecretReference:
    secretName: <app>-secrets
    secretNamespace: <app-namespace>
    creationPolicy: Owner
    template:
      includeAllSecrets: false
      data:
        API_KEY: "{{ .API_KEY.Value }}"
```

The Deployment binds to `<app>-secrets` via `secretKeyRef`. The secret VALUE lives in Infisical (project `homelab-bz-gt`, env `prod`), never in the repo.

## Anti-patterns — refuse + redirect

| Anti-pattern | What to do |
|---|---|
| `Secret` with literal `stringData:` | Replace with InfisicalSecret |
| `Secret` with literal `data: { key: <base64> }` | Replace with InfisicalSecret (base64 ≠ hardening) |
| ConfigMap key holding a password / token | Replace with InfisicalSecret |
| `env: { value: <literal> }` for sensitive var | Move to InfisicalSecret + `secretKeyRef` |
| Sealed-secrets (bitnami) | We don't use it — InfisicalSecret instead |
| "Just commit it, the repo is private" | Private repos flip public; rotate if committed |

## Operator workflow

**Adding a new credential:**
1. Add the key + value in Infisical UI (`homelab-bz-gt` / `prod`) FIRST.
2. Add it to the InfisicalSecret's `template.data:` block.
3. Reference in the Deployment via `secretKeyRef`.
4. Argo syncs; ~60s later the managed Secret exists; pod starts.

**Rotating:** edit in Infisical UI, wait ~60s (`resyncInterval`), restart the consuming pod if no Reloader annotation.

## Apps on the pattern (2026-05-18)

n8n-workflow, redis, open-terminal, open-webui, tailscale, stable-diffution-webui-rcom, arc-runner, wallos, mealie-mcp-docker, kroger-mcp-docker, harbor-pull (image pull), libreoffice (pending PR #2).

## Known gotchas

- `additionalAnnotations` on managed Secrets isn't supported by the controller (homelab#6).
- If you add a key to the template but forget to add it to Infisical, the InfisicalSecret stays Failed and the pod crashloops on `secret "X" not found`. Add to Infisical FIRST.
- Image-pull secrets work too — set the Secret `type: kubernetes.io/dockerconfigjson` on the managed Secret; see `open-terminal/base/harbor-pull-infisical-secret.yaml`.

## When to invoke

Any PR / manifest / question involving passwords, tokens, API keys, certificates, or anything else sensitive. Also "hardening", "credentials", "leak", "rotate".
