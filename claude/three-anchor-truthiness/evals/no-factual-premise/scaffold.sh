#!/usr/bin/env bash
# Fixture: a task with no factual premise at all. The skill three-anchor-truthiness
# now fires on unchecked premises, but should NOT fire when there's no factual
# premise to verify (just a general question or idle chat).
set -euo pipefail
# The eval home.
top=$HOME
[ ! -e "$top/Code/homelab/.git" ] || { echo "refusing: $top/Code/homelab is a real clone" >&2; exit 1; }

printf '# skills\n\nThis is a skills repo for Claude Code / opencode skills.\n' > README.md
