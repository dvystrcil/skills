---
name: "GitHub Workflow"
description: "Enforces a strict GitOps workflow: branch, rebase, test, PR. Never merge self."
tags: ["git", "github", "pr", "workflow"]
scope: "complex"
---

# GitHub Workflow

## Strict Git Rules
1. **Never commit to main**: Always create a descriptive branch (`feature/...` or `fix/...`)
2. **Rebase before committing**: Sync with main to avoid conflicts
3. **Test before committing**: Verify code works. Include test files if applicable.
4. **Commit with clear message**: Then push the branch
5. **Always create a PR** with:
   - What was built/changed and why
   - How to test it
   - Dependencies/configuration notes
   - Known limitations or follow-up work
6. **Wait for PR checks after creating any PR**: `gh pr checks <url> --watch --fail-fast`. A red check gets fixed on the same branch before you report done. "No checks reported" passes; red does not.
7. **Never merge your own PR**: Await user review and approval
