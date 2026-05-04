#!/usr/bin/env python3
"""Generate owui-skills-cm.yaml from skills/owui/*/SKILL.md.

Run after editing any skill file:
    python skills/build_configmap.py

Commit both the SKILL.md change and the updated owui-skills-cm.yaml together.
ArgoCD deploys the ConfigMap; the skill-sync CronJob mounts it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
SKILLS_DIR = ROOT / "owui"
OUT = ROOT / "owui-skills-cm.yaml"

skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
if not skill_files:
    print(f"No skill files found under {SKILLS_DIR}", file=sys.stderr)
    sys.exit(1)

lines = [
    "# AUTO-GENERATED — do not edit by hand.",
    "# Run `python skills/build_configmap.py` to regenerate.",
    "apiVersion: v1",
    "kind: ConfigMap",
    "metadata:",
    "  name: owui-skills",
    "  namespace: open-webui",
    "data:",
]

for path in skill_files:
    key = path.parent.name + ".md"
    content = path.read_text()
    lines.append(f"  {key}: |")
    for text_line in content.splitlines():
        lines.append(f"    {text_line}")
    lines.append("")

# Embed the sync script so the CronJob can run it without a git clone
sync_script = (ROOT / "sync_to_owui.py").read_text()
lines.append("  sync_to_owui.py: |")
for text_line in sync_script.splitlines():
    lines.append(f"    {text_line}")
lines.append("")

OUT.write_text("\n".join(lines) + "\n")
print(f"Wrote {OUT} ({len(skill_files)} skills + sync script)")
