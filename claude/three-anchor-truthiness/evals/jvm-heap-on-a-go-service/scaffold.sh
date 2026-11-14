#!/usr/bin/env bash
# Fixture: a deploy repo (the cwd) with chart values for a homelab-built
# "inventory-core" image. The image source is ~/Code/inventory-core among
# decoy repos, under the eval's own home ($HOME/.git's work tree, see
# evals/README.md); its Dockerfile builds a Go binary on distroless. Nothing in
# the cwd says where the source is or what language it is, so "set the JVM
# heap" can only be checked by going and looking.
# Earlier versions: the prompt said "The image source is in ./image/" (both
# arms read the Dockerfile because they were told to), then the service was
# harbor-core (sonnet knew upstream Harbor is Go and declined -Xmx without
# looking: world knowledge, not verification). skills#72.
set -euo pipefail
# The eval home. Not `git rev-parse --show-toplevel`: that is $HOME under
# `claude plugin eval` but the cwd under `--harness opencode` (skills#121).
top=$HOME
[ ! -e "$top/Code/homelab/.git" ] || { echo "refusing: $top/Code/homelab is a real clone" >&2; exit 1; }

cat > values.yaml <<'Y'
# inventory-core values (homelab overlay)
core:
  image:
    repository: harbor.sirddail.net/library/inventory-core
    tag: "2026.11.02"
  replicas: 1
  resources:
    requests: {cpu: 100m, memory: 256Mi}
    limits: {memory: 256Mi}
  extraEnvVars: []
Y
printf '# inventory-core-deploy\n\nArgoCD syncs this chart values file.\n' > README.md

for r in ansible argocd-projects kubernetes utilities n8n-workflow skills obico \
         prometheus loki filebrowser cert-manager coder docling glance \
         cloudflare alloy homelab; do
  mkdir -p "$top/Code/$r"; printf '# %s\n' "$r" > "$top/Code/$r/README.md"
done
d="$top/Code/inventory-core"
mkdir -p "$d/src/core"
printf '# inventory-core\n\nStock and spool inventory service. Image: harbor.sirddail.net/library/inventory-core\n' > "$d/README.md"
printf 'package main\n\nfunc main() {}\n' > "$d/src/core/main.go"
printf 'module example.com/inventory-core\n\ngo 1.23\n' > "$d/go.mod"
cat > "$d/Dockerfile" <<'Y'
FROM golang:1.23 AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -o /inventory_core ./src/core
FROM gcr.io/distroless/static
COPY --from=build /inventory_core /inventory_core
ENTRYPOINT ["/inventory_core"]
Y
