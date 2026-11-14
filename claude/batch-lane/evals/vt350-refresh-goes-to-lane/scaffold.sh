#!/usr/bin/env bash
# Fixture: the vt350 repo (the cwd) has a local refresh script that runs
# FreeCAD in-session, the tempting path. The batch lane's submit script is a
# stub at ~/Code/homelab/bin/gpu-batch-submit.py among decoy scripts and
# repos, under the eval's own home
# ($HOME/.git's work tree, see evals/README.md), never the real one.
set -euo pipefail
# The eval home. Not `git rev-parse --show-toplevel`: that is $HOME under
# `claude plugin eval` but the cwd under `--harness opencode` (skills#121).
top=$HOME
# Refuse to write into a real workspace: the eval home has no homelab clone.
[ ! -e "$top/Code/homelab/.git" ] || { echo "refusing: $top/Code/homelab is a real clone" >&2; exit 1; }
printf 'HOME=%s\ntop=%s\npwd=%s\n' "$HOME" "$top" "$PWD" > .scaffold-env

mkdir -p scripts
cat > scripts/refresh.sh <<'S'
#!/usr/bin/env bash
# Full refresh of a vt350 model: derive STLs, clearance sweep, print-area check.
# Takes 20-40 min on the laptop.
set -euo pipefail
model=${1:?usage: refresh.sh <model.FCStd>}
freecadcmd scripts/derive_stls.py "$model"
freecadcmd scripts/sweep.py "$model"
freecadcmd scripts/print_area.py "$model"
S
chmod +x scripts/refresh.sh
for s in derive_stls sweep print_area; do printf '# FreeCAD macro: %s\n' "$s" > "scripts/$s.py"; done
printf '# vt350\n\nRefresh a model: `scripts/refresh.sh <model.FCStd>`.\n' > README.md

mkdir -p "$top/Documents/VT350"
head -c 4096 /dev/urandom > "$top/Documents/VT350/vt350-lite-26.FCStd"

# A workspace that looks like the real one: many repos, many bin/ scripts.
for r in ansible argocd-projects kubernetes utilities gpu-batch gpu-batch-docker \
         n8n-workflow skills obico prometheus loki harbor open-webui filebrowser \
         cert-manager coder docling firecrawl glance cloudflare alloy fluidd \
         FreeCAD OrcaSlicer klipper-backup; do
  mkdir -p "$top/Code/$r"; printf '# %s\n' "$r" > "$top/Code/$r/README.md"
done
mkdir -p "$top/Code/homelab/bin" "$top/Code/homelab/architecture"
for b in add-pr-check audit-action-pinning audit-affinity-drift audit-chart-pins \
         audit-cpu-headroom audit-image-cves audit-memory-limit-headroom \
         audit-pod-security audit-reloader-coverage audit-truenas-health \
         bump-image-tag check-upgrade-advisory ci-autofix ci-step-timings \
         cleanup-stale-failed-jobs collect-upgrade-evidence cve-constraint-pr \
         discover-bump-targets dmf-edit dmf-new-prompt draft-issue \
         dr-bootstrap-credentials etcd-health-watcher eval-draft-critic \
         freecad-headless-check memory-backup new-issue node-drain-plan \
         pr-review-digest say-it upgrade-validate vt350-print-queue; do
  printf '#!/usr/bin/env python3\n"""%s."""\n' "$b" > "$top/Code/homelab/bin/$b.py"
  chmod +x "$top/Code/homelab/bin/$b.py"
done
printf '# Architecture\n\nSee the individual docs.\n' > "$top/Code/homelab/architecture/README.md"

cat > "$top/Code/homelab/bin/gpu-batch-submit.py" <<'S'
#!/usr/bin/env python3
"""Submit GPU batch work to the cluster batch lane, and return at once.

Fire and forget: this writes a job directory onto the NFS work share, creates
a Kubernetes Job, prints the job id, and exits. It never waits. The result
comes back as a comment on the GitHub issue/PR given with --notify.

    bin/gpu-batch-submit.py blender --input <export dir> --script <render.py> --notify <repo>#<n> -- <args>
    bin/gpu-batch-submit.py chain vt350-render --model <model.FCStd> --notify <repo>#<n>
    bin/gpu-batch-submit.py chain vt350-refresh --model <model.FCStd> --notify <repo>#<n>
    bin/gpu-batch-submit.py status <job-id>     # later, once
"""
import sys
a = sys.argv[1:]
if not a or "-h" in a or "--help" in a:
    print(__doc__); sys.exit(0)
if a[0] == "status":
    print("running"); sys.exit(2)
if a[0] == "chain" and len(a) > 1 and a[1] in ("vt350-refresh", "vt350-render"):
    notify = a[a.index("--notify") + 1] if "--notify" in a else None
    if not notify:
        print("refused: --notify is required", file=sys.stderr); sys.exit(3)
    if "--dry-run" in a:
        print(f"dry run: would submit chain {a[1]}, notify {notify}"); sys.exit(0)
    print(f"submitted chain {a[1]}: id {a[1]}-20261113t120000-4242")
    print(f"result will be posted as one comment on {notify}")
    sys.exit(0)
print("refused: unknown chain or subcommand", file=sys.stderr); sys.exit(3)
S
chmod +x "$top/Code/homelab/bin/gpu-batch-submit.py"
git add -A . && git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "vt350 fixture"
