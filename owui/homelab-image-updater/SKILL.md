---
name: "Homelab Image Updater"
description: "How the homelab uses argocd-image-updater. Use whenever creating, editing, or debugging an ImageUpdater CRD. Covers two writer types, constraint mechanics, schema gotchas, and a registry of working examples."
tags: ["homelab", "kubernetes", "argocd", "image-updater", "gitops"]
scope: "complex"
---

# Homelab Image Updater

CRD-based config in `dvystrcil/argocd-image-updater/<app>/`. Before writing or editing one, **find a working example in the cluster**:

```bash
kubectl -n argocd get imageupdater                            # list all
kubectl -n argocd get imageupdater <similar-app>-iu -o yaml   # copy structure
```

## Two writer types

**Kustomize** (most common, ~9 of 11 live CRDs) — for apps with `base/` + `overlays/kustomization.yaml`. NO `manifestTargets` needed.

```yaml
imageName: "<registry>/<image>:<semver-constraint>"
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "https://github.com/dvystrcil/<repo>.git"
    branch: "main"
    writeBackTarget: "kustomization:/overlays"
```

Reference: `trilium-iu`, `homepage-iu`, `n8n-workflow-iu`.

**Helm** — for apps with a Helm chart. `manifestTargets.helm.{name,tag}` are dot-paths INTO values.yaml.

```yaml
imageName: "<registry>/<image>:<semver-constraint>"
manifestTargets:
  helm:
    name: "image.repository"
    tag: "image.tag"
writeBackConfig:
  gitConfig:
    writeBackTarget: "helmvalues:./values.yaml"
```

Reference: `cloudflared-iu`, `coder-iu`.

**`manifestTargets.kubernetes` is NOT a thing** — there's no writer that takes raw `spec.template.spec.containers[].image` paths. Use kustomize instead.

## Constraint mechanics

| Where | Purpose |
|---|---|
| `imageName: <image>:1.x` | Semver range constraint |
| `commonUpdateSettings.allowTags: 'regexp:...'` | Tag regex filter (channel/build filter) |
| `commonUpdateSettings.updateStrategy: semver/name/digest/newest-build` | How to pick from candidates |

**Pre-release gotcha:** `imageName: ...:1.x-stable` does NOT filter the stable channel. Semver treats `-stable` as a pre-release identifier; `1.4.1-beta-slim > 1.3-stable` because the numeric portion wins. Channel filtering MUST go through `allowTags` regex.

## Schema silent-drop gotcha

The CRD schema accepts ONLY these top-level keys in `images[]`:
- `alias` (required)
- `imageName` (required)
- `commonUpdateSettings` (object)
- `manifestTargets` (object, helm only)

These belong UNDER `commonUpdateSettings` — at top level they get silently dropped:
- `updateStrategy`, `allowTags`, `ignoreTags`, `forceUpdate`, `platforms`, `pullSecret`

**Always verify after apply:**
```bash
kubectl -n argocd get imageupdater <app>-iu -o yaml | grep -A6 'commonUpdateSettings:'
```

## Private registries (Harbor)

```yaml
commonUpdateSettings:
  pullSecret: "pullsecret:<namespace>/harbor-pull"
```

The harbor-pull secret is sourced via InfisicalSecret — see the `homelab-secrets` skill.

## Working examples

| Pattern | Copy from |
|---|---|
| Plain kustomize semver | `trilium-iu` |
| Helm with values.yaml | `cloudflared-iu` |
| Channel filter via regex | `filebrowser-iu` (stable-only) |
| Harbor private + regex tag | `ollama-iu` |
| Harbor private + plain semver | `open-terminal-iu` |

## Debugging

```bash
# Cycle visibility
kubectl -n argocd logs -l app.kubernetes.io/name=argocd-image-updater --tail=200 | grep <app>-iu

# Look for:
# - "Starting image update cycle"
# - "Processing results: ... images_skipped=1 images_updated=0 errors=0"  ← constraint working, no bump needed
# - "Processing results: ... images_updated=1"  ← it pushed a commit
```

If `images_updated=1` happened when you didn't expect, check the target repo's main for the auto-commit — image-updater commits as `argocd-image-updater`.

## Anti-patterns from 2026-05-18 incident

1. `manifestTargets.kubernetes` with raw K8s field paths — controller no-ops silently
2. `imageName: ...:1.x-stable` as channel filter — semver ignores the `-stable` for numeric ordering
3. `updateStrategy`/`allowTags` at images[] top level — dropped by CRD schema, must nest under `commonUpdateSettings`

All three landed in production over a 20-minute window before being caught.
