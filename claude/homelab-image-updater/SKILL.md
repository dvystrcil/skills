---
name: homelab-image-updater
description: How the homelab uses argocd-image-updater. Use whenever creating, editing, or debugging an ImageUpdater CRD. Covers the two writer types (helm/kustomize), constraint mechanics (semver + allowTags regex), the silent-drop schema gotcha, and a registry of working examples.
---

# Homelab Image Updater

The homelab uses [argocd-image-updater](https://github.com/argoproj-labs/argocd-image-updater) with **CRD-based config** (not the legacy annotation-based config on Argo Applications). Every CRD lives under `dvystrcil/argocd-image-updater/<app>/<app>-image-updater.yaml` and gets applied into the `argocd` namespace by the `app-of-updates` Argo Application.

If you're about to write or edit one, **find a working example in the cluster first**:

```bash
kubectl -n argocd get imageupdater                                # list all
kubectl -n argocd get imageupdater <similar-app>-iu -o yaml       # copy structure from
```

That five-second lookup would have prevented all three of today's (2026-05-18) regressions in the filebrowser-iu rollout.

## The two writer types

### Kustomize (most common — 9 of 11 live CRDs)

For apps with `base/` + `overlays/kustomization.yaml`. Image-updater rewrites the `images:` override in the overlay's kustomization. **No `manifestTargets` block needed** — the writer handles the path automatically.

Reference: [`trilium/argocd-image-updater.yaml`](https://github.com/dvystrcil/argocd-image-updater/blob/main/trilium/argocd-image-updater.yaml). Cluster example: `trilium-iu`.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: <app>-iu
spec:
  namespace: argocd
  applicationRefs:
    - namePattern: "<argo-app-name>"      # MUST match a live Argo Application
      images:
        - alias: "<app>"
          imageName: "<registry>/<image>:<semver-constraint>"   # e.g. "ghcr.io/.../foo:1.x"
      writeBackConfig:
        method: "git"
        gitConfig:
          repository: "https://github.com/dvystrcil/<repo>.git"
          branch: "main"
          writeBackTarget: "kustomization:/overlays"
```

### Helm

For apps with a Helm chart + values.yaml. Image-updater rewrites two keys in the values file. **`manifestTargets.helm` IS required** (it tells the writer which keys hold the image name and tag).

Reference: [`cloudflared/cloudflared-image-updater.yaml`](https://github.com/dvystrcil/argocd-image-updater/blob/main/cloudflared/cloudflared-image-updater.yaml). Cluster example: `cloudflared-iu`.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: <app>-iu
spec:
  namespace: argocd
  applicationRefs:
    - namePattern: "<argo-app-name>"
      images:
        - alias: "<app>"
          imageName: "<registry>/<image>:<semver-constraint>"
          manifestTargets:
            helm:
              name: "image.repository"   # dot-path INTO values.yaml
              tag: "image.tag"
      writeBackConfig:
        method: "git"
        gitConfig:
          repository: "https://github.com/dvystrcil/<repo>.git"
          branch: "main"
          writeBackTarget: "helmvalues:./values.yaml"
```

## What does NOT exist

**`manifestTargets.kubernetes` is not a thing.** There's no writer that takes raw `spec.template.spec.containers[0].image` YAML dot-paths into a `deployment.yaml`. Today's filebrowser-iu first draft tried this and the controller silently no-op'd. The CRD validates strict at `manifestTargets` — only `helm` is allowed.

If you find yourself trying to write a "manifestTargets that points at deployment.yaml", you're using the wrong tool. Use the kustomize writer instead and let it rewrite the kustomization's `images:` override.

## Tag conventions (canonical homelab style)

This split bites every new IU CR. Get it wrong and the regex silently never matches.

| Source | Git tag | Image tag in registry |
|---|---|---|
| **Homelab self-built** (any of our `*-docker` repos) | `vX.Y.Z` | `X.Y.Z` (no `v`) |
| **Vendor / upstream** images | n/a (theirs) | Whatever the vendor chose |

Why the split: `docker/metadata-action`'s `type=semver,pattern={{version}}` **strips the `v` prefix by default** when retagging from a GitHub release. So our `release.yml` workflows convert `v0.0.4` (release) → `0.0.4` (image). Both intentional, both correct.

For **vendor images** there is no convention to assume — match the actual tag format you see:

| Vendor | Their image tags | IU CR shape |
|---|---|---|
| infisical/infisical | `v0.160.7` (v prefix) | regex `^v0\.160\.\d+$` |
| cloudflare/cloudflared | `2026.5.0` (calver, no v) | constraint `:2026.x` |
| ghcr.io/mealie-recipes/mealie | `v3.19.0` (v prefix) | regex `^v3\.[0-9]+\.[0-9]+$` |
| ghcr.io/some-other | depends | check Docker Hub / ghcr first |

**Verification commands when in doubt:**

```bash
# Docker Hub
curl -sS https://hub.docker.com/v2/repositories/<image>/tags/?page_size=10 | jq '.results[].name'

# GitHub release tags (likely v-prefixed)
gh release list --repo <owner>/<repo>

# Harbor (private — use a pod with the pullSecret)
# Or look at one of our docker-release.yaml workflow runs to see what got pushed
```

**Rule:** match the SOURCE's actual image tag format in your regex / constraint. Don't copy-paste from a sibling IU CR unless the sibling tracks the same registry's images.

## Constraint mechanics

Two things constrain which tag image-updater will bump to:

### `imageName: <image>:<tag-glob>`

The tag suffix on `imageName` is the **semver constraint range**. Examples:

| Constraint | Matches | Use when |
|---|---|---|
| `:1.x` | 1.0.0, 1.3.2, 1.10.0, 1.4.0-beta — anything in 1.x major | You want to track a major |
| `:v1.x` | v1.0.0, v1.3.2-beta — anything with `v` prefix in 1.x | Upstream uses `v` prefix (homepage, trilium) |
| `:0.x` | All of 0.x | Track a 0.x line |
| `:2026.x` | 2026.5.1, 2026.12.0 | Calver (cloudflared) |
| No tag | Any tag matching the strategy | `imageName: harbor.sirddail.net/ai/ollama` (no tag, needs allowTags to constrain) |

### `commonUpdateSettings.allowTags: 'regexp:...'`

**Must be nested under `commonUpdateSettings`.** A regex filter applied to candidate tags BEFORE the strategy picks one. Use when you need to restrict beyond what semver alone can express.

```yaml
images:
  - alias: ollama
    imageName: "harbor.sirddail.net/ai/ollama"
    commonUpdateSettings:
      allowTags: 'regexp:^\d+\.\d+\.\d+(-rc\d+)?-rocm-homelab$'
      updateStrategy: "newest-build"
      pullSecret: "pullsecret:ollama/harbor-pull"
```

Cluster example: `ollama-iu` (above), `filebrowser-iu` (regex for `-stable` channel).

### `commonUpdateSettings.updateStrategy`

| Strategy | What it picks |
|---|---|
| `semver` (default) | Highest semver-valid tag matching the imageName constraint AND allowTags |
| `name` | Alphabetically highest tag — **be careful**, `1.3.10 < 1.3.2` alphabetically |
| `digest` | Same tag, different digest (mutable tags like `:latest`) |
| `newest-build` | Newest by build timestamp from the registry metadata. Best for Harbor-published custom builds. |

## The pre-release gotcha (today's mistake)

**Semver treats `-stable`, `-beta`, `-beta-slim` as pre-release identifiers.** Numeric comparison wins: `1.4.1-beta-slim > 1.3-stable` because `1.4.1 > 1.3`. Pre-release alpha-order (`beta-slim` vs `stable`) only breaks ties when the numeric portion is equal.

**This means `imageName: ...:1.x-stable` does NOT actually filter to the stable channel.** Image-updater parses `1.x` as the constraint; `-stable` is just part of the imageName string with no filtering behavior. We learned this the hard way at 19:27 today when filebrowser-iu bumped `1.3-stable → 1.4.1-beta-slim` on its first cycle.

To actually filter by channel, use `allowTags`:

```yaml
imageName: "ghcr.io/gtsteffaniak/filebrowser:1.x"
commonUpdateSettings:
  updateStrategy: "semver"
  allowTags: 'regexp:^1\.\d+\.\d+-stable$'   # only concrete-patch stable
```

The regex `\d+\.\d+\.\d+` requires three numeric components so moving pointers (`1.3-stable`, `1-stable`) don't compete with concrete patches (`1.3.2-stable`).

## The silent-drop schema gotcha (today's second mistake)

The CRD's openapi schema accepts **only** these top-level fields on `images[]`:

- `alias` (required)
- `imageName` (required)
- `commonUpdateSettings` (object — see below)
- `manifestTargets` (object, helm only)

These fields belong under **`commonUpdateSettings`** — putting them at the top level results in the controller silently dropping them:

- `updateStrategy`
- `allowTags`
- `ignoreTags`
- `forceUpdate`
- `platforms`
- `pullSecret`

**Verify the constraint is actually active after applying:**

```bash
kubectl -n argocd get imageupdater <app>-iu -o yaml | grep -A8 'commonUpdateSettings:'
```

If you see nothing, your fields got dropped — re-nest them.

Today's first-pass filebrowser fix had `updateStrategy` and `allowTags` at the top level. They were silently dropped. The controller defaulted to bare-semver behavior and tried to bump to the beta channel on the very next cycle.

## Write-back targets

| Scheme | Use for | Example |
|---|---|---|
| `kustomization:/overlays` | Kustomize repos | Most apps |
| `kustomization:/<path>` | Kustomize repo with non-standard overlay path | (none in cluster currently) |
| `helmvalues:./values.yaml` | Helm chart with values at repo root | `cloudflared-iu`, `coder-iu` |
| `helmvalues:/<path>` | Helm with non-root values | (none in cluster currently) |

## Private registries (Harbor)

For images on `harbor.sirddail.net`, image-updater needs to authenticate. Use `pullSecret` in `commonUpdateSettings`:

```yaml
commonUpdateSettings:
  pullSecret: "pullsecret:<namespace>/<secret-name>"
  # e.g. "pullsecret:ollama/harbor-pull" — references the harbor-pull secret
  # in the ollama namespace (managed via InfisicalSecret per homelab-secrets skill)
```

Cluster examples: `open-terminal-iu`, `ollama-iu`. The pull secret itself is sourced via InfisicalSecret — see the `homelab-secrets` skill.

## Registry of working examples (2026-05-18)

Use these as templates by similarity:

| Pattern | Reference CRD | When to copy |
|---|---|---|
| Plain kustomize, semver constraint, GHCR/Docker Hub public | `trilium-iu` | Most public OSS images |
| Plain helm, dot-paths into values.yaml | `cloudflared-iu` | Apps deployed via Helm chart |
| Channel filter via regex (only stable tags) | `filebrowser-iu` | Image publishes multiple channels under same major (stable/beta/slim) |
| Harbor private + custom build regex | `ollama-iu` | Internally-built Harbor images with specific tag patterns |
| Harbor private + plain semver | `open-terminal-iu` | Internally-built Harbor images with standard semver tags |

## Debugging checklist

When image-updater isn't doing what you expect:

1. **Did the CRD get applied with all your fields?**
   ```bash
   kubectl -n argocd get imageupdater <app>-iu -o yaml
   ```
   Compare to your repo file. Missing fields → schema silently dropped them, check nesting.

2. **Is image-updater seeing the CRD?**
   ```bash
   kubectl -n argocd logs -l app.kubernetes.io/name=argocd-image-updater --tail=200 | grep <app>-iu
   ```
   You should see `"Starting image update cycle"` lines every ~2 minutes.

3. **What did it decide?**
   ```
   "Processing results: applications=N images_considered=N images_skipped=N images_updated=N errors=N"
   ```
   - `images_updated=1` → it pushed a commit. Check the target repo's `main` for an `argocd-image-updater` author commit.
   - `images_skipped=1, errors=0` → constraint is active, no newer tag matched. **This is what you want most of the time.**
   - `errors>=1` → check registry auth, regex syntax, application name match.

4. **What tags is it considering?** Image-updater logs the candidate set at debug level. Bump log level via configmap if needed:
   ```bash
   kubectl -n argocd get cm argocd-image-updater-config -o yaml
   ```

5. **Did the namePattern match?** `namePattern` must match a live Argo Application name. Verify:
   ```bash
   kubectl -n argocd get application <name>
   ```
   Logs show `"Listing all applications in target namespace"` followed by 0 results if the pattern matches nothing.

## Today's anti-pattern receipts (don't repeat)

| Mistake | Symptom | Fix |
|---|---|---|
| `manifestTargets.kubernetes.name: "spec.template.spec.containers[0].image"` | No commits pushed, controller silently no-ops | Use kustomize writer, no manifestTargets, `writeBackTarget: "kustomization:/overlays"` |
| `imageName: ...:1.x-stable` to filter stable channel | First cycle bumps to `1.4.1-beta-slim` | Move filter to `commonUpdateSettings.allowTags: 'regexp:...'` |
| `updateStrategy` / `allowTags` at top level of `images[]` | Fields disappear after kubectl apply; bare-semver behavior resumes | Nest under `commonUpdateSettings` |

## When the AI should invoke this skill

- Creating a new ImageUpdater CRD (look for an existing similar one first)
- Editing an existing CRD's constraint, strategy, or write-back target
- Debugging "image-updater isn't bumping my app" or "it bumped to the wrong tag"
- Reviewing a PR that adds/modifies a file under `dvystrcil/argocd-image-updater/`
- Onboarding a new app that should auto-update its image

## Related

- `dvystrcil/argocd-image-updater` — the repo where all CRDs live
- `dvystrcil/argocd-image-writer` — the operator's deployment
- `homelab-secrets` skill — for the `pullSecret` referenced when using private Harbor images
- Today's incident PRs (cross-ref for future me): `filebrowser-iu` ones were the lesson, `ollama-iu` and `open-terminal-iu` are the canonical examples of the right shape with private registries
