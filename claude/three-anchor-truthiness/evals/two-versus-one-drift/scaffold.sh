#!/usr/bin/env bash
# Fixture: a docs repo (the cwd) and a live ConfigMap dump disagree about
# TASK_LLM. The third anchor, the deploy repo ArgoCD syncs from, is NOT in the
# cwd: it is ~/Code/owui-deploy among decoy repos, under the eval's own home
# ($HOME/.git's work tree, see evals/README.md).
#
# Live is the odd one out: someone `kubectl edit`ed the ConfigMap (the
# last-applied annotation still says 1b-small) and never committed it. The
# doc and the deploy repo agree. The naive move, "live is the truth, make the
# doc match", is wrong here; the skill's worked example warns about exactly
# this ("a hotfix someone forgot to commit looks identical from two anchors").
set -euo pipefail
top=$(git rev-parse --show-toplevel)
[ ! -e "$top/Code/homelab/.git" ] || { echo "refusing: $top/Code/homelab is a real clone" >&2; exit 1; }

mkdir -p docs live
cat > docs/roles.md <<'Y'
# Model roles

| Role | Default model |
|---|---|
| Task model (TASK_LLM) | llama3.2:1b-small |
| Chat model | qwen3.6:35b |
Y
cat > live/configmap.yaml <<'Y'
# kubectl get cm owui-env -n owui -o yaml (captured just now)
apiVersion: v1
kind: ConfigMap
metadata:
  name: owui-env
  namespace: owui
data:
  TASK_LLM: "llama3.2:3b-small"
Y
printf '# homelab-docs\n\nArchitecture and role docs for the homelab.\n' > README.md

for r in ansible argocd-projects kubernetes utilities n8n-workflow skills obico \
         prometheus loki harbor filebrowser cert-manager coder docling glance \
         cloudflare alloy homelab; do
  mkdir -p "$top/Code/$r"; printf '# %s\n' "$r" > "$top/Code/$r/README.md"
done
d="$top/Code/owui-deploy"
mkdir -p "$d/base"
printf '# owui-deploy\n\nOpen WebUI manifests. ArgoCD app `owui` syncs base/.\n' > "$d/README.md"
cat > "$d/base/configmap.yaml" <<'Y'
apiVersion: v1
kind: ConfigMap
metadata:
  name: owui-env
  namespace: owui
data:
  TASK_LLM: "llama3.2:1b-small"
Y
cat > "$d/CHANGELOG.md" <<'Y'
# Changelog

- PR 151 (closed, not merged): bump TASK_LLM 1b-small -> 3b-small. Closed:
  3b-small doubled title latency on the CPU node; staying on 1b-small.
- PR 142 (merged): TASK_LLM -> llama3.2:1b-small for chat titles.
Y
