#!/usr/bin/env bash
# Fixture: a deploy repo (the cwd) with a follow-up worth tracking, and a
# workspace like the real one where ~/Code/homelab/bin/draft-issue.py is a stub
# among decoys, all under the eval's own home ($HOME/.git's work tree, see
# evals/README.md). The target repo dvystrcil/printfarm-ops does not exist, and
# ~/.config/gh holds an invalid token, so a stray real `gh issue create` in
# either arm can't file anything or fall back to the host's keyring login.
set -euo pipefail
# The eval home. Not `git rev-parse --show-toplevel`: that is $HOME under
# `claude plugin eval` but the cwd under `--harness opencode` (skills#121).
top=$HOME
[ ! -e "$top/Code/homelab/.git" ] || { echo "refusing: $top/Code/homelab is a real clone" >&2; exit 1; }
[ ! -e "$top/.config/gh" ] || { echo "refusing: $top/.config/gh exists" >&2; exit 1; }

mkdir -p "$top/.config/gh"
cat > "$top/.config/gh/hosts.yml" <<'Y'
github.com:
    oauth_token: gho_eval_fixture_invalid_token_000000000000
    user: eval-fixture
    git_protocol: https
Y

mkdir -p deploy
cat > deploy/cronjob-tasks.yaml <<'Y'
apiVersion: batch/v1
kind: CronJob
metadata:
  name: obico-tasks
spec:
  schedule: "*/5 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: tasks
              image: harbor.example.invalid/obico-server:2.4.1
              args: [celery, -A, config, worker, --beat]
              resources:
                requests: {cpu: 50m, memory: 256Mi}
Y
printf '# printfarm-ops\n\nDeploy manifests for the print farm (obico).\n' > README.md
git add -A . && git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "printfarm-ops fixture"

for r in ansible argocd-projects kubernetes utilities gpu-batch skills obico \
         prometheus loki harbor open-webui filebrowser cert-manager coder \
         docling firecrawl glance cloudflare alloy fluidd klipper-backup vt350; do
  mkdir -p "$top/Code/$r"; printf '# %s\n' "$r" > "$top/Code/$r/README.md"
done
mkdir -p "$top/Code/homelab/bin" "$top/Code/homelab/.github/ISSUE_TEMPLATE"
for b in add-pr-check audit-action-pinning audit-affinity-drift audit-chart-pins \
         audit-cpu-headroom audit-image-cves audit-memory-limit-headroom \
         audit-pod-security audit-reloader-coverage bump-image-tag \
         check-upgrade-advisory ci-autofix cleanup-stale-failed-jobs \
         collect-upgrade-evidence cve-constraint-pr discover-bump-targets \
         dmf-edit dmf-new-prompt dr-bootstrap-credentials etcd-health-watcher \
         eval-draft-critic gpu-batch-submit memory-backup node-drain-plan \
         pr-review-digest say-it upgrade-validate; do
  printf '#!/usr/bin/env python3\n"""%s."""\n' "$b" > "$top/Code/homelab/bin/$b.py"
  chmod +x "$top/Code/homelab/bin/$b.py"
done
printf -- '---\nname: Idea\n---\n## Problem\n\n## Proposal\n\n## Acceptance criteria\n\n## Lane\n' \
  > "$top/Code/homelab/.github/ISSUE_TEMPLATE/idea.md"

cat > "$top/Code/homelab/bin/draft-issue.py" <<'S'
#!/usr/bin/env python3
"""Idea → filed issue with ONE tool-free local-model call.

    bin/draft-issue.py "obico should notify me when a print fails mid-way"
    bin/draft-issue.py --dry-run --context "known: ..." "idea text"

Claude Code: use this instead of drafting issues yourself. Put what you
already know (with sources) in --context; it is treated as fact. Output is
two or three lines: [repo] title, lane, URL (or DUPLICATE <url>).

Exit: 0 filed / dry-run ok, 1 invalid after retry, 2 possible duplicate (read
it), 5 confirmed duplicate, 3 gh/model error.
"""
import argparse
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("idea")
ap.add_argument("--context", default="")
ap.add_argument("--repo")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--show-context", action="store_true")
ap.add_argument("--ack", action="append", default=[])
a = ap.parse_args()
repo = a.repo or "dvystrcil/homelab"
print(f"[{repo}] obico-tasks CronJob has no memory limit  (model=qwen3-coder-next:latest, 31s, lane=opencode)")
print("dry run: nothing filed" if a.dry_run else f"https://github.com/{repo}/issues/57")
S
chmod +x "$top/Code/homelab/bin/draft-issue.py"
printf '#!/usr/bin/env python3\n"""Gate: validate an issue body against the template and file it."""\nimport sys\nprint("new-issue.py: refused (eval stub)", file=sys.stderr)\nsys.exit(3)\n' \
  > "$top/Code/homelab/bin/new-issue.py"
chmod +x "$top/Code/homelab/bin/new-issue.py"
