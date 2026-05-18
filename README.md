# skills

Canonical home for the skills used by **Claude Code**, **opencode**, and **OWUI**.

## Layout

```
skills/
├── claude/                    # Claude Code & opencode flavor (frontmatter: name, description)
│   ├── code-reviewer/SKILL.md
│   ├── devops-engineer/SKILL.md
│   ├── diary/SKILL.md
│   ├── doc-master/SKILL.md
│   ├── homelab-memory/SKILL.md
│   ├── n8n-import-workflow/SKILL.md
│   ├── owui-import-pipeline/SKILL.md
│   ├── owui-memory-loader/SKILL.md
│   ├── pgo-pre-upgrade-backup/SKILL.md
│   ├── repo-protections/SKILL.md
│   ├── test-architect/SKILL.md
│   └── upgrade-validate/SKILL.md
├── owui/                      # OWUI flavor (frontmatter: name, description, tags, scope)
│   ├── git-workflow/SKILL.md
│   ├── persona-and-formatting/SKILL.md
│   ├── price-verification-specialist/SKILL.md
│   ├── repo-protections/SKILL.md
│   ├── tool-discipline/SKILL.md
│   ├── tools-and-files/SKILL.md
│   └── visualize/SKILL.md
├── repo-protections/          # Shared executables for the repo-protections skill
│   ├── bin/audit.sh
│   ├── bin/apply.sh
│   └── templates/
├── portable-skills.txt        # Manifest: cluster-agnostic subset for the work workstation
├── build_configmap.py         # Regenerates owui-skills-cm.yaml from owui/*/SKILL.md
├── sync_to_owui.py            # Pushes skills from configmap into OWUI's DB at runtime
├── sync_to_owui.yaml          # CronJob that runs sync_to_owui.py
├── owui-skills-cm.yaml        # Generated ConfigMap (do not edit by hand)
└── README.md                  # this file
```

## Consumers

### Claude Code & opencode

Both read from `~/.claude/skills/<name>/SKILL.md` — opencode's `~/.config/opencode/opencode.json` points its `skills.paths` at the same directory. The operator's local layout symlinks each user-authored skill in this repo into that location:

```
~/.claude/skills/code-reviewer  →  ~/Code/skills/claude/code-reviewer/
~/.claude/skills/doc-master     →  ~/Code/skills/claude/doc-master/
... etc
```

Anthropic-installed skills (`find-skills`, `first-ask`, `frontend-design`, `scheduler`, `tdd`) live under `~/.agents/skills/` and are symlinked into `~/.claude/skills/` separately — those are NOT redistributed in this repo.

### OWUI

OWUI loads its skills from a ConfigMap mounted into the pod:

1. Edit `owui/<name>/SKILL.md` or add a new skill directory under `owui/`.
2. Run `python build_configmap.py` to regenerate `owui-skills-cm.yaml`.
3. Commit both files together — ArgoCD applies the ConfigMap.
4. The `skill-sync` CronJob (`sync_to_owui.yaml`) pushes the SKILL.md contents into OWUI's database hourly.

OWUI's SKILL.md format adds `tags` and `scope` to the frontmatter — those drive UI surfacing and lazy-load behavior in OWUI.

### Work-workstation install

[`dvystrcil/claude-personal-config`](https://github.com/dvystrcil/claude-personal-config)'s `install.sh` clones this repo, reads `portable-skills.txt`, and symlinks the cluster-agnostic subset into `~/.claude/skills/`. Homelab-specific skills (`homelab-memory`, `owui-*`, `pgo-pre-upgrade-backup`, `upgrade-validate`, `n8n-import-workflow`, `devops-engineer`) are intentionally omitted from the portable subset — they reference infrastructure the work workstation doesn't have.

## Adding a new skill

| Target | Where to add | Frontmatter |
|---|---|---|
| Claude Code / opencode | `claude/<name>/SKILL.md` | `name`, `description` |
| OWUI | `owui/<name>/SKILL.md`, then re-run `build_configmap.py` | `name`, `description`, `tags`, `scope` |
| All three | both directories | (bodies can be identical) |

If the skill bundles scripts or templates (like `repo-protections`), put the SKILL.md(s) under `claude/` and/or `owui/` as usual, but put the shared assets at the top level under `<skill-name>/{bin,templates}/` and reference them via absolute paths.

## Related repos

- [`dvystrcil/claude-personal-config`](https://github.com/dvystrcil/claude-personal-config) — work-workstation installer + methodology docs (ac-process, diary practice)
- [`dvystrcil/homelab`](https://github.com/dvystrcil/homelab) — cluster ops, where most homelab-specific skills' target infrastructure lives
