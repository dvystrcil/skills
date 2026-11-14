#!/usr/bin/env bash
set -euo pipefail
git init -q -b main app
cd app
printf '# app\n\nServices recieve requests on :8080.\n' > README.md
git add README.md
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "initial"
