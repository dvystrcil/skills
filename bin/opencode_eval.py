"""opencode harness for the skill evals (skills#121).

`bin/skill-evals.py --harness opencode` runs the same claude/*/evals/*/case.yaml
files through `opencode run` instead of `claude plugin eval`, with the skill on
(with arm) and off (without arm), and grades both with the case's own graders.

Why: under Claude Code, qwen3-coder-next looped to max_turns in most runs and
scored 0.00. Under opencode, the same model on the same prompt wrote the file
in 1-2 calls and scored what Opus scores without the skill (skills#121). opencode
is the harness that model is deployed in, so this is the column that says what
a skill does for it.

How a case maps onto opencode:

* **Workspace.** Like `claude plugin eval`: a fresh root per run, `$HOME` is a
  git repo on `main` (the "Plugin Eval" identity), the cwd is `$HOME/cwd`, and
  `context.scaffold_script` runs there before the agent.
* **Skill.** The with arm gets `skills.paths` pointing at a copy of the skill
  folder WITHOUT its `evals/` (the graders live there). The without arm gets no
  skill path. opencode's own built-in `opencode` skill is visible to both.
* **Tools.** `allowed_tools` maps to opencode tool names. A tool the case
  doesn't grant is disabled. Network and interactive tools are always off.
  opencode can't disable `edit` alone: a case that grants Write but not Edit
  gets both here.
* **Limits.** `max_turns` becomes opencode's agent `steps`, and
  `timeout_seconds` a process timeout.
* **Trace.** opencode's events are normalised to Claude Code's shape (tool
  names `Bash`/`Write`/..., input keys `file_path`/`old_string`/...), because
  the graders are written against that. The JSON is compact, like
  `JSON.stringify`.
* **Regexes** are evaluated in node, because the patterns are JavaScript (some
  use variable-width lookbehind, which Python's `re` rejects).
* **Sandbox.** The agent runs under bwrap: `/` read-only, the run root
  writable, the user's credentials hidden. The model is on Ollama, so the
  network stays up. SKILL_EVALS_OPENCODE_SANDBOX=0 turns bwrap off (tests only).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# opencode tool name -> Claude Code tool name, and its input keys.
TOOL_NAMES = {"shell": "Bash", "bash": "Bash", "read": "Read", "write": "Write",
              "edit": "Edit", "glob": "Glob", "grep": "Grep", "skill": "Skill",
              "webfetch": "WebFetch", "websearch": "WebSearch", "subagent": "Task"}
INPUT_KEYS = {"filePath": "file_path", "oldString": "old_string",
              "newString": "new_string", "replaceAll": "replace_all", "id": "skill"}
# Claude Code's Read/Write/Edit take `file_path`; its Glob/Grep take `path`.
FILE_PATH_TOOLS = {"read", "write", "edit"}
# Claude Code tool name (allowed_tools) -> the opencode tool(s) it grants.
GRANTS = {"Bash": ["shell"], "Read": ["read"], "Write": ["write"], "Edit": ["edit"],
          "Glob": ["glob"], "Grep": ["grep"], "Skill": ["skill"]}
ALWAYS_OFF = ["execute", "experimental_image_generate", "subagent", "opencode_*",
              "opencode_worktree_remove"]
DENY = ["webfetch", "websearch", "question"]

# Directories under the real $HOME that hold credentials (same list as
# homelab opencode/sandbox-run.sh).
HIDE_DIRS = [".config/gh", ".ssh", ".kube", ".docker", ".infisical", ".config/infisical",
             ".gnupg", ".aws", ".claude", ".config/github-mcp-explore",
             ".local/share/opencode", ".config/opencode"]
SKILL_DIRS = [".agents", ".claude", ".opencode"]
HIDE_FILES = [".git-credentials", ".netrc", ".gitconfig", ".config/git/credentials"]


def _input(tool: str, inp) -> dict:
    if not isinstance(inp, dict):
        return {}
    if tool not in TOOL_NAMES:
        return dict(inp)
    keys = dict(INPUT_KEYS, path="file_path") if tool in FILE_PATH_TOOLS else INPUT_KEYS
    return {keys.get(k, k): v for k, v in inp.items()}


def _js(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def normalise(events: list[dict], max_turns: int | None = None) -> dict:
    """opencode `run --format json` events -> calls, trace, final text, steps."""
    calls, lines, texts = [], [], []
    steps, last_reason, errors = 0, None, []
    for e in events:
        part = e.get("part") or {}
        kind = part.get("type")
        if e.get("type") == "error":
            errors.append(_js(e.get("error") or e)[:300])
        elif kind == "step-start":
            steps += 1
        elif kind == "step-finish":
            last_reason = part.get("reason")
        elif kind == "text" and part.get("text"):
            texts.append(part["text"])
            lines.append(_js({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": part["text"]}]}}))
        elif kind == "tool":
            tool = part.get("tool") or ""
            state = part.get("state") or {}
            call = {"name": TOOL_NAMES.get(tool, tool), "input": _input(tool, state.get("input"))}
            calls.append(call)
            cid = part.get("id") or f"call_{len(calls)}"
            lines.append(_js({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": cid, "name": call["name"], "input": call["input"]}]}}))
            out = state.get("output") if state.get("status") == "completed" else state.get("error")
            lines.append(_js({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": "" if out is None else str(out),
                 "is_error": state.get("status") != "completed"}]}}))
    capped = bool(max_turns) and steps >= max_turns and last_reason == "tool-calls"
    return {"calls": calls, "trace": "\n".join(lines) + "\n", "final": texts[-1] if texts else "",
            "steps": steps, "capped": capped, "errors": errors}


def _node_tests(checks: list[tuple[str, str, str]]) -> list[bool]:
    """Evaluate [(pattern, flags, text)] with JavaScript's RegExp."""
    if not checks:
        return []
    prog = ("let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
            "const a=JSON.parse(s);"
            "console.log(JSON.stringify(a.map(([p,f,t])=>new RegExp(p,f).test(t))))})")
    p = subprocess.run(["node", "-e", prog], input=json.dumps(checks),
                       capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise ValueError(f"node regex evaluation failed: {p.stderr.strip()[-300:]}")
    return json.loads(p.stdout)


def _in_cwd(cwd: Path, rel: str) -> Path | None:
    target = (cwd / rel).resolve()
    root = cwd.resolve()
    if target != root and root not in target.parents:
        return None
    return target


def _read(cwd: Path, rel: str) -> str | None:
    target = _in_cwd(cwd, rel)
    if target is None or not target.is_file():
        return None
    return target.read_text(errors="replace")


def grade(graders: list[dict], arm: str, run: dict, cwd: Path) -> list[dict]:
    """Grade one run. Returns [{name, passed, scored}] for the graders this arm runs.

    Like `claude plugin eval` under ablation: a grader marked `arm: with` and a
    `tool_used: Skill` grader don't run in the without arm, and the Skill
    grader is display-only (not scored) in the with arm.
    """
    # jobs: (result index, kind, grader, payload). All regexes from all jobs go
    # to node in one batch, and the answers are read back in the same order.
    jobs, results = [], []

    def add(name, scored):
        results.append({"name": name, "passed": None, "scored": scored})
        return len(results) - 1

    calls = run["calls"]
    for g in graders:
        is_skill = g.get("type") == "tool_used" and g.get("tool") == "Skill"
        if arm == "without" and (is_skill or g.get("arm") == "with"):
            continue
        idx = add(g["name"], not is_skill)
        t = g.get("type")
        if t == "file_exists":
            target = _in_cwd(cwd, g["path"])
            results[idx]["passed"] = bool(target and target.exists())
        elif t == "regex":
            tgt = g.get("target")
            if tgt == "trace":
                text = run["trace"]
            elif tgt in ("final", "output", "result"):
                text = run["final"]
            elif isinstance(tgt, dict) and tgt.get("source") == "file":
                text = _read(cwd, tgt["path"])
            else:
                raise ValueError(f"grader {g['name']}: unsupported regex target {tgt!r}")
            if text is None:
                results[idx]["passed"] = False  # a missing file passes nothing
            else:
                jobs.append((idx, "regex", g, [(g["pattern"], g.get("flags", ""), text)]))
        elif t == "tool_used":
            matching = [c for c in calls if c["name"] == g["tool"]]
            pats = [(g["input_match"], g.get("flags", ""), _js(c["input"])) for c in matching] \
                if g.get("input_match") else []
            jobs.append((idx, "count", g, pats if g.get("input_match") else len(matching)))
        elif t == "tool_order":
            seq = []
            for side in ("before", "after"):
                spec = g[side]
                for i, c in enumerate(calls):
                    if c["name"] == spec["tool"]:
                        seq.append((side, i, spec.get("input_match"), _js(c["input"])))
            jobs.append((idx, "order", g, seq))
        else:
            raise ValueError(f"grader {g['name']}: unsupported type {t!r}")

    checks = []
    for idx, kind, g, payload in jobs:
        if kind == "regex":
            checks += payload
        elif kind == "count" and isinstance(payload, list):
            checks += payload
        elif kind == "order":
            checks += [(m or "", "", text) for _, _, m, text in payload]
    answers = iter(_node_tests(checks))

    for idx, kind, g, payload in jobs:
        if kind == "regex":
            hit = next(answers)
            results[idx]["passed"] = (not hit) if g.get("match") == "not_contains" else hit
        elif kind == "count":
            n = sum(next(answers) for _ in payload) if isinstance(payload, list) else payload
            lo = g.get("min", 1)
            hi = g.get("max")
            results[idx]["passed"] = n >= lo and (hi is None or n <= hi)
        elif kind == "order":
            hits = [(side, i) for (side, i, _, _), ok in ((p, next(answers)) for p in payload) if ok]
            after = [i for side, i in hits if side == "after"]
            before = [i for side, i in hits if side == "before"]
            results[idx]["passed"] = bool(after and before and min(before) < min(after))
    return results


def score(results: list[dict]) -> float:
    scored = [r for r in results if r["scored"]]
    return sum(1 for r in scored if r["passed"]) / len(scored) if scored else 0.0


def opencode_config(model: str, base_url: str, allowed_tools: list[str], max_turns: int,
                    skills_dir: str | None) -> dict:
    granted = {t for name in allowed_tools for t in GRANTS.get(name, [])}
    tools = {t: False for t in ALWAYS_OFF}
    for name in GRANTS.values():
        for t in name:
            if t not in granted:
                tools[t] = False
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {"ollama": {
            "npm": "@ai-sdk/openai-compatible", "name": "ollama",
            "options": {"baseURL": base_url.rstrip("/") + "/v1"},
            "models": {model: {"name": model, "limit": {"context": 131072, "output": 8192}}}}},
        "model": f"ollama/{model}",
        "permission": {"edit": "allow", **{t: "deny" for t in DENY}},
        "tools": tools,
        "agent": {"build": {"steps": max_turns}},
        "autoupdate": False,
        "share": "disabled",
    }
    # opencode 2.3.0: `permission: {bash: allow}` re-enables a shell that
    # `tools: {shell: false}` removed, so an ungranted shell is denied by both.
    if "shell" in granted:
        cfg["permission"]["bash"] = "allow"
    else:
        cfg["permission"].update({"bash": "deny", "shell": "deny"})
    if skills_dir:
        cfg["skills"] = {"paths": [skills_dir]}
    return cfg


def _bwrap(root: Path, cwd: Path) -> list[str]:
    real_home = Path.home()
    b = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
         "--tmpfs", "/tmp", "--tmpfs", "/run/user", "--unshare-pid", "--unshare-ipc",
         "--unshare-uts", "--die-with-parent", "--new-session"]
    for d in HIDE_DIRS:
        if (real_home / d).is_dir():
            b += ["--tmpfs", str(real_home / d)]
    for f in HIDE_FILES:
        if (real_home / f).exists():
            b += ["--ro-bind", "/dev/null", str(real_home / f)]
    # opencode looks for skills in .agents/.claude/.opencode on every directory
    # above the cwd. The run root lives under the real $HOME (~/.cache), so
    # without this both arms saw ~/.agents/skills (skills#121).
    hidden = {str(real_home / d) for d in HIDE_DIRS}
    for anc in root.resolve().parents:
        for d in SKILL_DIRS:
            p = anc / d
            if p.is_dir() and str(p) not in hidden:
                hidden.add(str(p))
                b += ["--tmpfs", str(p)]
    seen = set()
    for s in ("/run/docker.sock", "/var/run/docker.sock", "/run/containerd/containerd.sock"):
        if Path(s).is_socket():
            r = os.path.realpath(s)
            if r not in seen:
                seen.add(r)
                b += ["--ro-bind", "/dev/null", r]
    return b + ["--bind", str(root), str(root), "--chdir", str(cwd)]


def _workspace(root: Path, case_dir: Path, spec: dict,
               git_at: str = "cwd") -> tuple[Path, Path, dict]:
    """Build the run's home and cwd, and run the case's scaffold in the cwd.

    The cwd is the git root (git_at="cwd"), unlike `claude plugin eval`, which
    makes $HOME the root. With the root one level above the cwd, opencode
    reports it as the "Workspace root folder" and qwen3-coder-next wrote `./x`
    relative to it, outside the cwd: 0.00-0.20 on image-updater. With cwd =
    root: 0.87 with the skill, 0.60 without (skills#121). That is also the
    shape opencode is used in: started at a repo's root. git_at="home" builds
    the claude layout (tests use it to check scaffolds work in both).
    """
    # `claude plugin eval` names the case dir `cwd`. SKILL_EVALS_CWD_NAME
    # renames it here (skills#121: qwen resolves `./x` against `$HOME` when the
    # directory is literally called `cwd`).
    home = root / "home"
    cwd = home / os.environ.get("SKILL_EVALS_CWD_NAME", "cwd")
    cwd.mkdir(parents=True)
    (root / "xdg-config").mkdir()
    (root / "xdg-data").mkdir()
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Plugin Eval\n\temail = plugin-eval@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
    env = {"HOME": str(home), "USER": os.environ.get("USER", "eval"), "LANG": "C.UTF-8",
           "TERM": "dumb", "SHELL": "/bin/bash", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "TMPDIR": "/tmp", "XDG_CONFIG_HOME": str(root / "xdg-config"),
           "XDG_DATA_HOME": str(root / "xdg-data"), "XDG_RUNTIME_DIR": str(root / "xdg-data"),
           "OPENCODE_CONFIG": str(root / "opencode.json"), "OPENCODE_DISABLE_AUTOUPDATE": "1"}
    # The agent's environment is built from nothing, so nothing of the user's
    # leaks in. SKILL_EVALS_PASSENV names extra variables to pass (tests).
    for name in os.environ.get("SKILL_EVALS_PASSENV", "").split(","):
        if name and name in os.environ:
            env[name] = os.environ[name]
    git_root = cwd if git_at == "cwd" else home
    subprocess.run(["git", "init", "-q", "-b", "main", str(git_root)], env=env, check=True)
    script = (spec.get("context") or {}).get("scaffold_script")
    if script:
        p = subprocess.run(["bash", str(case_dir / script)], cwd=cwd, env=env,
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"scaffold failed: {(p.stderr or p.stdout).strip()[-200:]}")
    return home, cwd, env


def run_once(skill_dir: Path, case_dir: Path, spec: dict, arm: str, model: str,
             base_url: str, root_parent: Path, keep_dir: Path | None) -> dict:
    """One run of one arm. Returns {score, graders, error, capped, steps}."""
    execution = spec.get("execution") or {}
    max_turns = int(execution.get("max_turns") or 20)
    timeout = int(execution.get("timeout_seconds") or 300)
    root = Path(tempfile.mkdtemp(prefix="opencode-eval-", dir=root_parent))
    try:
        home, cwd, env = _workspace(root, case_dir, spec)
        skills = None
        if arm == "with":
            dest = root / "skills" / skill_dir.name
            shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns("evals", "__pycache__"))
            skills = str(root / "skills")
        cfg = opencode_config(model, base_url, list(execution.get("allowed_tools") or []),
                              max_turns, skills)
        (root / "opencode.json").write_text(json.dumps(cfg, indent=1))
        cmd = ["opencode", "run", "--standalone", "--format", "json",
               "--model", cfg["model"], execution["prompt"]]
        if os.environ.get("SKILL_EVALS_OPENCODE_SANDBOX", "1") != "0":
            cmd = _bwrap(root, cwd) + ["env", "-i", *[f"{k}={v}" for k, v in env.items()]] + cmd
        error = None
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                               timeout=timeout)
            stdout, stderr, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr, rc = "", None
            error = f"timed out after {timeout}s"
        events = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        run = normalise(events, max_turns)
        if rc not in (0, None) and not error:
            error = f"opencode exit {rc}: {stderr.strip()[-200:]}"
        if run["errors"] and not error:
            error = "opencode error: " + run["errors"][0]
        results = grade(spec.get("graders") or [], arm, run, cwd)
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            (keep_dir / "events.jsonl").write_text(stdout)
            (keep_dir / "trace.jsonl").write_text(run["trace"])
            (keep_dir / "stderr.txt").write_text(stderr)
            (keep_dir / "graders.json").write_text(json.dumps(results, indent=1))
        return {"score": score(results), "graders": results, "error": error,
                "capped": run["capped"], "steps": run["steps"]}
    finally:
        if keep_dir is None:
            shutil.rmtree(root, ignore_errors=True)
