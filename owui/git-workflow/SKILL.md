---
name: "GitHub Workflow"
description: "Enforces a strict GitOps workflow: Branch, Rebase, Test, PR. Never merge self."
tags: ["git", "github", "pr", "workflow"]
---

# GitHub Workflow

**Strict Git Rules:**
1. **Branch First:** Never commit to `main`. Use `feature/[desc]` or `fix/[desc]`.
2. **Sync:** Always rebase `main` before committing to avoid conflicts.
3. **Verify:** Run tests/code execution before committing.
4. **PR:** Open PR immediately after push.
5. **PR Content:** Must include:
   - Summary of changes
   - Testing steps
   - Config/Dependency notes
   - Known limitations
6. **Wait:** Never merge your own PR. Awaiting user review.

**Slash Commands:**
- `/sync_up`: Commit & push all changes.
- `/sync_down`: Pull latest changes.
- `/sync_pr`: Branch, commit, push, and open PR automatically.
