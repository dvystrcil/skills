#!/usr/bin/env bash
# Fixture: five Deployments that ALREADY all have memory limits, and a unittest
# suite. A new guard for "every container has a memory limit" passes on the
# first run whatever it checks. Committed to the eval's own repo ($HOME/.git,
# see evals/README.md).
set -euo pipefail
mkdir -p k8s tests
i=0
for app in api web worker scheduler notifier; do
  i=$((i + 1))
  cat > "k8s/$app.yaml" <<Y
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $app
spec:
  replicas: 1
  selector:
    matchLabels: {app: $app}
  template:
    metadata:
      labels: {app: $app}
    spec:
      containers:
        - name: $app
          image: harbor.example.invalid/printfarm/$app:2.4.$i
          resources:
            requests:
              cpu: 50m
              memory: $((i * 64))Mi
            limits:
              memory: $((i * 128))Mi
Y
done
cat > tests/test_manifests.py <<'PY'
"""Static checks over k8s/*.yaml. Run: python3 -m unittest discover -s tests"""
import glob
import os
import unittest

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")


def deployments():
    for path in sorted(glob.glob(os.path.join(ROOT, "k8s", "*.yaml"))):
        with open(path) as f:
            for doc in yaml.safe_load_all(f):
                if doc and doc.get("kind") == "Deployment":
                    yield path, doc


class TestManifests(unittest.TestCase):
    def test_images_are_pinned(self):
        for path, d in deployments():
            for c in d["spec"]["template"]["spec"]["containers"]:
                self.assertNotRegex(c["image"], r":latest$|^[^:]+$", path)


if __name__ == "__main__":
    unittest.main()
PY
printf '# printfarm-deploy\n\nTests: `python3 -m unittest discover -s tests`\n' > README.md
git add -A . && git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "deploy fixture"
python3 -m unittest discover -s tests >/dev/null 2>&1
