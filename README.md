# Open WebUI Skills

## Intent
This repository serves as the centralized, Git-managed source of truth for **Open WebUI skills**. 

Skills are modular, markdown-based instruction sets that teach the AI agent how to handle specific tasks (e.g., coding standards, git workflows, persona). By managing them here, we treat AI behavior configuration as code: versioned, auditable, and easily synced to the Open WebUI instance via a mounted directory.

## How Open WebUI Uses Skills
Open WebUI supports "External Skills" which are discovered automatically from a filesystem mount.

### Key Mechanics
*   **Discovery:** OWUI scans a specific root directory (e.g., `/external/skills`) for folders containing a `SKILL.md` file.
*   **Manifesting:** It extracts metadata (Name, Description, Tags) from the YAML frontmatter of the markdown file. This manifest is sent to the model without loading the full content.
*   **Lazy Loading:** The model only loads the full content of a skill when a user request triggers the `view_skill` tool based on the manifest description. This saves context tokens.
*   **Read-Only:** Skills are intended to be read-only by the AI. You should edit them here and push changes to Git.

## Directory Structure
OWUI requires a specific hierarchy to map skills to your Git repo.

```text
skills/
└── owui/                    # (or whatever EXTERNAL_SKILLS_ROOT is set to)
    ├── skill-folder-name/   # Folder name is often used as part of the ID
    │   └── SKILL.md         # The instruction file
    └── ...
```

## Setup & Integration
To make these skills live on your Open WebUI instance, ensure your Docker/K8s configuration includes:

### 1. Environment Variables
```yaml
environment:
  - EXTERNAL_SKILLS_ROOT=/external/skills   # Where the mount is
  - EXTERNAL_SKILLS_SYNC_ENABLED=true       # Enables the sync worker
  - EXTERNAL_SKILLS_SYNC_INTERVAL=60        # How often to check for updates
```

### 2. Volume Mount
```yaml
volumes:
  - ./skills:/external/skills:ro            # :ro ensures AI doesn't modify files
```

## Instructions for Future AIs
If you are an AI agent tasked with managing these skills:

1. **Adding a New Skill:**
   *   Create a new folder under `skills/owui/` named descriptively (e.g., `python-best-practices`).
   *   Inside, create a file named exactly `SKILL.md`.
   *   **Must** include YAML frontmatter:
       ```yaml
       ---
       name: "Skill Name"
       description: "Short description of what this skill does."
       tags: ["tag1", "tag2"]
       ---
       # Markdown content follows...
       ```
2. **Modifying a Skill:**
   *   Edit the `SKILL.md` in the existing folder.
   *   If you change the `name` in the frontmatter, OWUI will treat it as an update; do **not** rename the file.
3. **Syncing:**
   *   Commit your changes to `master`.
   *   On the Open WebUI instance, wait for the `EXTERNAL_SKILLS_SYNC_INTERVAL` (usually 60s) for the changes to appear.

## Current Skills
*   **tools-and-files**: Rules for code saving, shell access, and web browsing.
*   **git-workflow**: Strict GitOps rules (branching, rebasing, PRs).
*   **persona-and-formatting**: Tone guidelines and diagramming standards.
