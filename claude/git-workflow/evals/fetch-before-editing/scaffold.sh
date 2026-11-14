#!/usr/bin/env bash
# The eval sandbox makes any .git it finds under the case dir read-only, so
# the working repo is the eval's own ($HOME/.git, whose work tree contains this
# cwd). Its "origin" is a bare repo next to it that is one commit AHEAD: the
# typo is already fixed there, and the local origin/main ref is stale.
set -euo pipefail
author=(-c user.name=fixture -c user.email=fixture@example.invalid)
printf '# app\n\nServices recieve requests on :8080.\n' > README.md
git add README.md
git "${author[@]}" commit -qm "initial"
git branch --show-current | grep -qx main

top=$(git rev-parse --show-toplevel)
git clone -q --bare "$top" "$top/origin.git"
git remote add origin "$top/origin.git"
git fetch -q origin
git branch -q --set-upstream-to=origin/main main

# Someone else fixes it upstream; this clone hasn't fetched since.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone -q "$top/origin.git" "$tmp/other"
sed -i 's/recieve/receive/' "$tmp/other/cwd/README.md"
git -C "$tmp/other" "${author[@]}" commit -qam "Fix README typo"
git -C "$tmp/other" push -q origin main

# Local state: says up to date with a stale origin/main, file still has the typo.
grep -q recieve README.md
git status -sb | head -1 | grep -q '^## main...origin/main$'
