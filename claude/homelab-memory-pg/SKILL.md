---
name: homelab-memory-pg
description: Save a fact to the homelab_memory Postgres table (compound-scoped on user_id × domain per homelab#96). Postgres-backed sibling of [[homelab-memory]] (file-backed). The OWUI bridge Function will inject user_id and domain before calling this; the model never sees those values directly. AC1/AC2 deliverable for homelab#161 Shape 1.
script: bin/homelab-memory-pg.sh
# Subcommand-style CLI. The dispatcher validates the chosen subcommand's
# args + stdin before invoking. user_id and domain are bridge-injected
# (NOT model-supplied) — the OWUI Function pulls them from __user__.id
# and the 4-rule preset resolution respectively.
args:
  - name: subcommand
    type: enum
    required: true
    cli_position: 1
    values: [save]
    description: Operation to perform. Only `save` is implemented in v1; future versions may add list/show/critique.
subcommands:
  save:
    description: Upsert a fact to homelab_memory. Idempotent — re-saving the same name updates body/type/description in place. Body comes from stdin.
    args:
      - name: type
        type: enum
        required: true
        cli_position: 2
        values: [user, feedback, project, reference]
        description: Memory type — drives how readers consume the entry. Same vocabulary as Claude Code auto-memory.
      - name: name
        type: string
        required: true
        cli_position: 3
        description: Short kebab-case slug for the entry. Used as the UNIQUE key inside (user_id, domain).
      - name: user_id
        type: string
        required: true
        cli_position: 4
        description: OWUI user identifier. Bridge-injected from __user__.id — model does NOT supply this. Spoofing prevented at the bridge layer.
      - name: domain
        type: string
        required: true
        cli_position: 5
        description: Memory domain. Bridge-injected from the 4-rule preset resolution — model does NOT supply this directly.
    stdin:
      name: body
      type: string
      required: true
      description: Full markdown body of the memory. Read from stdin so embedded quotes/newlines don't escape-shell.

# Environment
env:
  - name: PG_URI
    required: true
    description: |
      Postgres connection URI for the homelab_memory database. The
      cluster MCP server reads the PGO-managed `pgbouncer-uri` from
      secret `open-webui/owui-postgres-pguser-homelab` and exports it
      as PG_URI before dispatching. NEVER build the URI from parts —
      per PGO quirks memory, password chars break query-string assembly.
