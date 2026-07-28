#!/usr/bin/env bash
# onboard-new-app-dispatch.sh — POST a workflow_dispatch event to
# onboard-new-app.yaml (dvystrcil/homelab) via GitHub's REST API.
#
# Deliberately no independent validation here (image XOR upstream_repo,
# pvc_size-when-StatefulSet, hosts-when-expose): the workflow's own
# "Validate inputs" step already does that and fails loudly on a bad
# combination. This script is a pure pass-through, same posture the
# workflow file documents for itself relative to bin/onboard-new-app.py.
#
# GitHub's workflow_dispatch API requires every input value to be
# either a string or a boolean, matching the type declared in the
# workflow's `on.workflow_dispatch.inputs` block -- `port` is declared
# as `type: string` there (not integer) even though it's logically a
# port number, so it's passed through as a string here too.
#
# Env: MCP_SERVER_GH_DISPATCH_TOKEN must be set to a fine-grained PAT
# scoped to dvystrcil/homelab, Actions: Read and write only.
# homelab#620 tracks replacing this static PAT with dynamic minting.

set -euo pipefail

REPO="dvystrcil/homelab"
WORKFLOW="onboard-new-app.yaml"
REF="main"

die() { echo "FAIL: $*" >&2; exit 1; }

[[ -n "${MCP_SERVER_GH_DISPATCH_TOKEN:-}" ]] || die "MCP_SERVER_GH_DISPATCH_TOKEN env var not set"

app="" image="" upstream_repo="" image_name="" override_name="" port=""
workload_kind="" pvc_size="" namespace="" pull_secret="" expose="false" hosts=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app) app="$2"; shift 2 ;;
        --image) image="$2"; shift 2 ;;
        --upstream-repo) upstream_repo="$2"; shift 2 ;;
        --image-name) image_name="$2"; shift 2 ;;
        --override-name) override_name="$2"; shift 2 ;;
        --port) port="$2"; shift 2 ;;
        --workload-kind) workload_kind="$2"; shift 2 ;;
        --pvc-size) pvc_size="$2"; shift 2 ;;
        --namespace) namespace="$2"; shift 2 ;;
        --pull-secret) pull_secret="$2"; shift 2 ;;
        --expose) expose="true"; shift 1 ;;
        --hosts) hosts="$2"; shift 2 ;;
        *) die "unknown flag: $1" ;;
    esac
done

[[ -n "${app}" ]] || die "--app is required"
[[ -n "${port}" ]] || die "--port is required"
[[ -n "${workload_kind}" ]] || die "--workload-kind is required"

# Build the inputs object with jq (never hand-interpolate JSON strings
# into a request body -- feedback_jq_for_curl_json_bodies). Only
# non-empty optional fields get included; empty string is still valid
# JSON but the workflow treats "" the same as absent for its own
# `[ -n "${{ inputs.x }}" ]` checks, so omitting vs. sending "" makes no
# behavioral difference -- included here as "" for simplicity rather
# than conditionally omitting keys.
inputs_json=$(jq -nc \
    --arg app "$app" \
    --arg image "$image" \
    --arg upstream_repo "$upstream_repo" \
    --arg image_name "$image_name" \
    --arg override_name "$override_name" \
    --arg port "$port" \
    --arg workload_kind "$workload_kind" \
    --arg pvc_size "$pvc_size" \
    --arg namespace "$namespace" \
    --arg pull_secret "$pull_secret" \
    --argjson expose "$expose" \
    --arg hosts "$hosts" \
    '{app: $app, image: $image, upstream_repo: $upstream_repo, image_name: $image_name,
      override_name: $override_name, port: $port, workload_kind: $workload_kind,
      pvc_size: $pvc_size, namespace: $namespace, pull_secret: $pull_secret,
      expose: $expose, hosts: $hosts}')

body=$(jq -nc --arg ref "$REF" --argjson inputs "$inputs_json" '{ref: $ref, inputs: $inputs}')

http_status=$(curl -sS -o /tmp/onboard-dispatch-response.json -w '%{http_code}' \
    -X POST \
    -H "Authorization: Bearer ${MCP_SERVER_GH_DISPATCH_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches" \
    -d "$body")

if [[ "$http_status" != "204" ]]; then
    die "GitHub API returned ${http_status}: $(cat /tmp/onboard-dispatch-response.json 2>/dev/null)"
fi

echo "Dispatched ${WORKFLOW} for app=${app}. This only confirms the workflow STARTED, not that onboarding succeeded."
echo "Check run status: gh run list --repo ${REPO} --workflow=${WORKFLOW} --limit 1"
echo "PRs (once the run completes) will be reported in that run's step summary -- never report the app as deployed until a human has reviewed and merged them."
