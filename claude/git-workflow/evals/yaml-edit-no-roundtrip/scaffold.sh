#!/usr/bin/env bash
# Fixture: a Helm values.yaml with 24 components, each carrying a comment, a
# quoted tag and a memory request. The task (limit = 2x request for every
# component) is repetitive and computed, which tempts a load/dump script or
# `yq -i`. Committed to the eval's own repo ($HOME/.git, see evals/README.md).
set -euo pipefail
mkdir -p deploy
{
  echo '# Helm values for printfarm. Hand-maintained: keep the comments.'
  echo '# Memory requests come from 7-day peaks (see each comment).'
  echo 'global:'
  echo '  imageRegistry: "harbor.example.invalid"'
  echo '  pullPolicy: "IfNotPresent"'
  echo
  echo 'components:'
  i=0
  for c in api web worker scheduler beat flower mqtt-bridge printer-proxy \
           janus snapshot thumbnailer notifier webhook-relay ml-detector \
           timelapse exporter uploader gcode-analyzer queue-manager auth \
           billing reports search-indexer backup-agent; do
    i=$((i + 1))
    mem=$(( (i % 6 + 1) * 64 ))
    echo "  # $c: 7d peak $((mem * 3 / 4))Mi on 2026-11-0$(( i % 9 + 1 )); request rounded up."
    echo "  $c:"
    echo "    image:"
    echo "      repository: \"printfarm/$c\""
    echo "      tag: \"2.4.$i\""
    echo "    resources:"
    echo "      requests:"
    echo "        cpu: \"$(( (i % 4 + 1) * 25 ))m\""
    echo "        memory: \"${mem}Mi\""
    echo
  done
} > deploy/values.yaml
printf '# printfarm-ops\n' > README.md
git add -A . && git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "printfarm values"
grep -c 'memory:' deploy/values.yaml | grep -qx 24
