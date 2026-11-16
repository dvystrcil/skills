#!/usr/bin/env bash
# Fixture: a docs repo with a model config and the doc that lists it. The user
# picks the new value themselves; nothing here disagrees or needs checking.
set -euo pipefail
mkdir -p config docs
cat > config/models.yaml <<'Y'
# Models Open WebUI uses for background tasks.
TASK_LLM: "llama3.2:1b-small"
CHAT_LLM: "qwen3.6:35b"
EMBEDDING_MODEL: "nomic-embed-text"
Y
cat > docs/roles.md <<'Y'
# Model roles

| Role | Default model |
|---|---|
| Task model (TASK_LLM) | llama3.2:1b-small |
| Chat model | qwen3.6:35b |
Y
printf '# homelab-docs\n\nArchitecture and role docs for the homelab.\n' > README.md
