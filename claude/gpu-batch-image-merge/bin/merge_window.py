#!/usr/bin/env python3
"""Is now a good time to merge the gpu-batch image bump PRs? Read-only: never merges, cancels or writes.

A deploy PR in dvystrcil/gpu-batch (from the CI bot, "deploy: gpu-batch-... <ver>") bumps newTag in
overlays/kustomization.yaml. Argo CD then rolls the CronJob templates, and gpu-batch-submit / n8n read the image off the
live CronJob each time a Job is made. So merging while a chain is in flight puts its later steps on the new image
(a mixed-version chain), and a Job that is running keeps the old one. A good time = the PR is green and mergeable, and
the lane is idle: no active Job (the watchdog doesn't count) and no chain step still waiting to start.

    python3 merge_window.py            # report; exit 0 READY, 1 WAIT, 2 nothing to merge, 3 couldn't tell
    python3 merge_window.py --json
"""
import argparse, datetime as dt, glob, json, os, subprocess, sys

REPO = "dvystrcil/gpu-batch"
NS = "gpu-batch"
WORK = os.environ.get("GPU_BATCH_WORK", "/mnt/nfs/media/gpu-batch")
TERMINAL = {"succeeded", "failed", "refused", "aborted", "cancelled", "canceled", "timeout", "guard"}
DEAD = {"failed", "refused", "aborted", "cancelled", "canceled", "timeout", "guard"}
PENDING_MAX_H = 24          # a step dir older than this with no status is an abandoned chain, not a pending one


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, check=True).stdout


def deploy_prs():
    out = json.loads(sh("gh", "pr", "list", "-R", REPO, "--state", "open", "--json",
                        "number,title,url,author,isDraft,mergeable,mergeStateStatus,statusCheckRollup,createdAt"))
    prs = []
    for p in out:
        if not p["title"].startswith("deploy:"): continue
        checks = p.get("statusCheckRollup") or []
        bad = [c.get("name") for c in checks if (c.get("conclusion") or c.get("state")) not in ("SUCCESS", "NEUTRAL", "SKIPPED")]
        prs.append(dict(number=p["number"], title=p["title"], url=p["url"], created=p["createdAt"],
                        green=bool(checks) and not bad, not_green=bad, mergeable=p["mergeable"] == "MERGEABLE",
                        clean=p["mergeStateStatus"] == "CLEAN", draft=p["isDraft"]))
    return prs


def active_jobs():
    items = json.loads(sh("kubectl", "get", "jobs", "-n", NS, "-o", "json"))["items"]
    out = []
    for j in items:
        name = j["metadata"]["name"]
        if name.startswith("gpu-batch-watchdog"): continue
        s = j.get("status", {})
        if s.get("active", 0) > 0 or (not s.get("succeeded") and not s.get("failed") and not s.get("completionTime")):
            out.append(name)
    return out


def pending_steps(now):
    """Chain steps written to the work share but not started, whose chain is still alive (no dead step)."""
    chains = {}
    for spec_f in glob.glob(f"{WORK}/*/spec.json"):
        try: spec = json.load(open(spec_f))
        except Exception: continue
        cid = ((spec.get("chain") or {}).get("id"))
        if not cid: continue
        st_f = os.path.join(os.path.dirname(spec_f), "status.json")
        state = None
        if os.path.exists(st_f):
            try: state = json.load(open(st_f)).get("state")
            except Exception: state = "unreadable"
        try: created = dt.datetime.fromisoformat(spec["created"])
        except Exception: created = dt.datetime.fromtimestamp(os.path.getmtime(spec_f), dt.timezone.utc)
        chains.setdefault(cid, []).append((spec["id"], state, created))
    out = []
    for cid, steps in chains.items():
        if any(s in DEAD for _, s, _ in steps): continue
        for sid, state, created in steps:
            if state is None and (now - created).total_seconds() < PENDING_MAX_H * 3600:
                out.append(sid)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    rep = dict(checked=now.isoformat(timespec="seconds"))
    try:
        rep["prs"] = deploy_prs()
        rep["active_jobs"] = active_jobs()
        rep["pending_steps"] = pending_steps(now)
    except Exception as ex:
        rep["verdict"], rep["why"] = "UNKNOWN", f"couldn't read state: {ex}"
        print(json.dumps(rep, indent=1) if a.json else f"UNKNOWN: {rep['why']}"); return 3
    prs = rep["prs"]
    why = []
    if not prs:
        rep["verdict"], why = "NOTHING", ["no open deploy: PR in " + REPO]
    else:
        for p in prs:
            if p["draft"]: why.append(f"#{p['number']} is a draft")
            if not p["green"]: why.append(f"#{p['number']} checks not green: {p['not_green'] or 'none reported yet'}")
            if not (p["mergeable"] and p["clean"]): why.append(f"#{p['number']} not cleanly mergeable")
        if len(prs) > 1: why.append(f"{len(prs)} deploy PRs open: merge the newest, close the older as superseded")
        if rep["active_jobs"]: why.append(f"Jobs running: {', '.join(rep['active_jobs'])}")
        if rep["pending_steps"]: why.append(f"chain steps not started yet: {', '.join(rep['pending_steps'])}")
        blocking = [w for w in why if "deploy PRs open" not in w]
        rep["verdict"] = "WAIT" if blocking else "READY"
    rep["why"] = why
    if a.json: print(json.dumps(rep, indent=1))
    else:
        print(f"{rep['verdict']}: " + ("; ".join(why) if why else "PR green, lane idle"))
        for p in prs: print(f"  #{p['number']} {p['title']}  {p['url']}")
    return {"READY": 0, "WAIT": 1, "NOTHING": 2}[rep["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
