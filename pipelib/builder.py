"""Builds a planned job one component at a time.

Each component gets its own Claude chat (a fresh session id) and at most
limits.max_prompts_per_component prompts (hard cap 3): one build prompt, then
fix prompts fed with the failing check output. Components that are done are
skipped on re-runs, so `build` can be resumed after a failure.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from . import claude, prompts
from .checks import run_checks
from .jobtypes import TYPES, scaffold_files
from .planner import topo_order, validate

IGNORE = {"node_modules", ".git", "build", ".gradle", "dist", "out", "__pycache__", ".venv", "venv", "run"}
DONE = ("done", "done_unverified")


def tree(root: Path, limit: int = 80) -> list[str]:
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE)
        for f in sorted(files):
            out.append(str(Path(dirpath, f).relative_to(root)))
            if len(out) >= limit:
                return out + ["..."]
    return out


def _git(ws: Path, *args) -> str:
    if not shutil.which("git"):
        return ""
    p = subprocess.run(["git", "-c", "user.name=pipeline", "-c", "user.email=pipeline@localhost", *args],
                       cwd=ws, capture_output=True, text=True)
    return p.stdout


def commit(ws: Path, msg: str):
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "--allow-empty", "-m", msg)


def changed_files(ws: Path) -> list[str]:
    out = _git(ws, "status", "--porcelain", "--untracked-files=all")
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def scaffold(job) -> Path:
    ws = job.workspace
    if ws.exists():
        return ws
    ws.mkdir(parents=True)
    for rel, body in scaffold_files(job.type, job.meta["title"]).items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    (ws / "SPEC.md").write_text(job.read("spec.approved.md") or job.read("spec.md"))
    if shutil.which("git"):
        _git(ws, "init", "-q")
        commit(ws, "scaffold")
    return ws


def _log(msg: str):
    print(msg, flush=True)


def _attempt_loop(job, cfg, *, key: str, first_prompt: str, checks: list[str],
                  fix_context: str, comp: dict, stage: str, tools) -> dict:
    """Run up to max prompts in one chat. Returns the component state dict."""
    max_p = cfg["limits"]["max_prompts_per_component"]
    resume_mode = cfg["claude"].get("fix_mode", "resume") == "resume"
    session = str(uuid.uuid4())
    st = {"status": "failed", "prompts": 0, "session": session, "skipped": [], "last_error": ""}
    prompt = first_prompt
    ws = job.workspace
    for n in range(1, max_p + 1):
        if n > 1 and not resume_mode:
            session = str(uuid.uuid4())
        _log(f"  [{key}] prompt {n}/{max_p} ...")
        st["prompts"] = n
        try:
            claude.run(prompt, cfg=cfg, cwd=ws, stage=stage, log_path=job.calls_log, tools=tools,
                       session=session, resume=(n > 1 and resume_mode), component=key,
                       prompt_no=n, job_type=job.type)
        except claude.ClaudeError as e:
            _log(f"  [{key}] claude error: {e}")
            if "not found" in str(e):
                raise SystemExit(str(e))
        res = run_checks(checks, ws, cfg)
        st["skipped"] = res.skipped
        if res.ok:
            st["status"] = "done_unverified" if res.skipped else "done"
            st["last_error"] = ""
            for s in res.skipped:
                _log(f"  [{key}] skipped: {s}")
            _log(f"  [{key}] {st['status']} after {n} prompt(s)")
            return st
        st["last_error"] = f"{res.failed_cmd}\n{res.output}"
        _log(f"  [{key}] check failed: {res.failed_cmd}")
        prompt = prompts.fix(comp, n + 1, max_p, res.failed_cmd, res.output,
                             context="" if resume_mode else fix_context)
    _log(f"  [{key}] FAILED after {max_p} prompts. Last error:\n" +
         "\n".join("    " + l for l in st["last_error"].splitlines()[-15:]))
    return st


def build(job, cfg, only: str | None = None, retry: bool = False) -> str:
    plan = job.read_json("plan.json")
    if not plan:
        raise SystemExit(f"Job {job.id} has no plan. Run `python3 pipeline.py plan {job.id}` first.")
    errs = validate(plan, cfg)
    if errs:
        raise SystemExit("plan.json is invalid:\n- " + "\n- ".join(errs))
    t = TYPES[job.type]
    ws = scaffold(job)
    order = topo_order(plan["components"])
    state = job.read_json("build.json") or {"components": {}, "final": {}}
    comps = state["components"]
    for c in order:
        comps.setdefault(c["id"], {"status": "pending", "prompts": 0})
        if retry and comps[c["id"]]["status"] in ("failed", "blocked"):
            comps[c["id"]] = {"status": "pending", "prompts": 0}
    if retry and state.get("final", {}).get("status") == "failed":
        state["final"] = {}
    if only and only not in comps:
        raise SystemExit(f"No component {only!r}. Components: {', '.join(comps)}")
    job.set_status("building")
    by_id = {c["id"]: c for c in order}

    for c in order:
        cid = c["id"]
        st = comps[cid]
        if only and cid != only:
            continue
        if st["status"] in DONE and not only:
            continue
        if st["status"] == "failed" and not only:
            _log(f"{cid}: failed earlier; use --retry to give it a new chat")
            continue
        bad = [d for d in c["depends_on"] if comps[d]["status"] not in DONE]
        if bad:
            comps[cid] = {"status": "blocked", "prompts": 0, "last_error": f"waiting on {', '.join(bad)}"}
            _log(f"{cid}: blocked (waiting on {', '.join(bad)})")
            job.write_json("build.json", state)
            continue
        _log(f"{cid}: {c['title']}")
        checks = list(t["quick"]) + ([c["check"]] if c.get("check") else [])
        deps = [by_id[d] for d in c["depends_on"]]
        first = prompts.build(job.type, plan["project_summary"], c, deps, tree(ws), checks,
                              cfg["limits"]["max_prompts_per_component"])
        st = _attempt_loop(job, cfg, key=cid, first_prompt=first, checks=checks, fix_context=first,
                           comp=c, stage="build", tools=cfg["claude"]["build_tools"])
        allowed = set(c["files"]) | set(c["touches"])
        stray = [f for f in changed_files(ws) if f not in allowed and not f.startswith(("node_modules", "build/", ".gradle")) and f != "package-lock.json"]
        if stray:
            st["outside_scope"] = stray
            _log(f"  [{cid}] note: also changed {', '.join(stray[:8])}")
        comps[cid] = st
        commit(ws, f"{cid}: {c['title']} ({st['status']})")
        job.write_json("build.json", state)

    if only or not all(comps[c["id"]]["status"] in DONE for c in order):
        status = "build_failed" if any(s["status"] in ("failed", "blocked") for s in comps.values()) else "building"
        job.set_status(status)
        return status

    if state.get("final", {}).get("status") in DONE:
        return job.meta["status"]

    _log("final checks ...")
    res = run_checks(t["final"], ws, cfg)
    if res.ok:
        final = {"status": "done_unverified" if res.skipped else "done", "prompts": 0, "skipped": res.skipped}
    else:
        _log(f"final check failed: {res.failed_cmd}; starting an integration chat")
        comp = {"id": "integrate", "title": "Integration fixes", "files": ["any"]}
        first = prompts.integrate(job.type, plan["project_summary"], tree(ws), res.failed_cmd, res.output,
                                  cfg["limits"]["max_prompts_per_component"])
        final = _attempt_loop(job, cfg, key="integrate", first_prompt=first, checks=t["final"],
                              fix_context=first, comp=comp, stage="integrate",
                              tools=cfg["claude"]["build_tools"])
        commit(ws, f"integrate ({final['status']})")
    for s in final.get("skipped", []):
        _log(f"  skipped: {s}")
    state["final"] = final
    job.write_json("build.json", state)
    status = {"done": "built", "done_unverified": "built_unverified"}.get(final["status"], "build_failed")
    job.set_status(status)
    return status
