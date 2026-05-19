---
name: owui-import-pipeline
description: Install/update OWUI Pipeline .py files (filter / pipe / manifold) into the running owui-pipelines pod via kubectl cp + runtime reload. Replaces the manual "Admin Panel → Settings → Pipelines → upload" UI flow. Pipelines, NOT Functions — see "When NOT to use" below.
script: bin/owui-import-pipeline.sh
args:
  - name: path
    type: string
    required: true
    cli_position: 1
    description: A .py file OR a directory containing *.py files. Filenames must be valid Python module names (underscores OK, dashes not — the basename becomes the pipeline id in OWUI).
---

# OWUI Import Pipeline

You are deploying an OWUI **Pipeline** (the `owui-pipelines` pod surface), not a **Function** (the inside-OWUI surface). The two are commonly confused; the install paths are different.

## Pipelines vs Functions — the distinction that matters

| | Pipelines | Functions |
|---|---|---|
| Where they run | Separate `owui-pipelines` pod (FastAPI app, port 9099) | Inside OWUI's main process |
| Source class name | `class Pipeline:` with `self.type` and `self.name` | `class Filter:` (or `Pipe`, `Action`) |
| Storage | Files on PVC mounted at `/app/pipelines/` | Rows in OWUI's main Postgres |
| Install method | `kubectl cp` to PVC + reload | OWUI Functions REST API or Workspace UI |
| Lifecycle hooks | `on_startup` / `on_shutdown` / `on_valves_updated` | `inlet` / `outlet` / `stream` only |
| Use this script | ✅ | ❌ — use a Functions install path instead |

If your `.py` file has `class Pipeline:` with `self.type = "filter"` (or `"pipe"` / `"manifold"`), it's a Pipeline → use this script.

If your `.py` file has `class Filter:` without that metadata, it's a Function → install via OWUI's Workspace UI (or build a separate Functions REST API helper script — TBD).

## When to use this skill

- After editing or creating a Pipeline source file in `homelab/prompts/owui/filters/` (or any other dir of OWUI Pipeline Python).
- Re-running with the same input is safe and overwrites in place; the runtime re-registers via reload.

## When NOT to use it

- For OWUI Functions (see above).
- For per-pipeline credential / valve configuration. Those are set via the OWUI UI under Pipelines after the file is installed; this script doesn't touch them.

## How to invoke

```bash
# Single file
homelab/bin/owui-import-pipeline.sh \
  homelab/prompts/owui/filters/memory_loader.py

# Whole directory
homelab/bin/owui-import-pipeline.sh \
  homelab/prompts/owui/filters/
```

## Output contract

```
[1/3] resolving owui-pipelines pod     owui-pipelines-5c9995876f-77jrn
[2/3] copying 1 pipeline(s)            memory_loader.py
[3/3] verifying via /v1/pipelines      memory_loader|memory_loader|filter
OK
```

The verify step parses GET `/v1/pipelines` and extracts the row matching the file's basename. Non-zero exit if the runtime didn't register the new file (often means a pod restart is needed).

## Things that go wrong (and what to do)

- **"no Running pod found with label app=owui-pipelines"** — the pipelines pod is down or the label changed. Check `kubectl -n open-webui get pods -l app=owui-pipelines`.
- **"PIPELINES_API_KEY not set on the pod"** — this falls back to `0p3n-w3bu!` (the documented default for OWUI Pipelines). Warning is loud because that means the pod is using insecure defaults. Acceptable inside the cluster; bad if you ever expose port 9099 externally.
- **"none of the installed pipelines registered with the runtime"** — older OWUI Pipelines versions don't hot-reload. Run `kubectl -n open-webui rollout restart deploy/owui-pipelines` and re-run.
- **kubectl cp fails for a particular file** — file may not be a valid Python module name (dashes are not allowed; underscores OK). Rename and re-run.
- **"Pipelines Not Detected" appears in the OWUI admin UI after install** — almost always means the new pipeline's `Valves` class is missing the **`pipelines: list[str]`** attribute. The OWUI runtime accesses `valves.pipelines` for every pipeline when building the `/models` listing; an `AttributeError` there propagates out of a listcomp and zeroes out the entire response — meaning all pipelines vanish from the UI, not just yours. Fix: add to your Pipeline's Valves:
  ```python
  pipelines: list[str] = Field(
      default=["*"],
      description="Model IDs this filter applies to. ['*'] = all models.",
  )
  ```
  Then re-run this script; the /models endpoint becomes healthy again immediately. Documented from a real incident on 2026-05-08.

## Required Pipeline class shape

Every Pipeline file MUST have:

```python
class Pipeline:
    class Valves(BaseModel):
        pipelines: list[str] = Field(default=["*"], ...)   # REQUIRED — see above
        # ...other Valves...

    def __init__(self):
        self.type = "filter"           # or "pipe", "manifold"
        self.name = "Human Name"        # appears in OWUI admin
        self.valves = self.Valves()

    async def on_startup(self): pass
    async def on_shutdown(self): pass
    async def on_valves_updated(self): pass

    # Then either inlet/outlet (for filter type) or pipe (for pipe type).
```

## Composability

```bash
# Edit, test, deploy loop:
vim prompts/owui/filters/memory_loader.py
prompts/owui/filters/tests/run.sh        # local Python tests pass
homelab/bin/owui-import-pipeline.sh \
  prompts/owui/filters/memory_loader.py  # deploy to cluster
```

The runtime hot-reloads; the next OWUI chat using a model with this filter attached will pick up the new code. No OWUI pod restart needed.

## See also

- Script source: `/home/dan/Code/homelab/bin/owui-import-pipeline.sh` — full AI metadata header at top.
- Tests: `/home/dan/Code/homelab/bin/tests/test_owui_import.sh`.
- Sister scripts:
  - `n8n-import-workflow` — same pattern for n8n workflows.
  - `homelab-memory` — the storage primitive several pipelines (including memory_loader) read from.
- The first pipeline installed via this helper: the homelab memory loader at `homelab/prompts/owui/filters/memory_loader.py`.
