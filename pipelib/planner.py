"""Turns the approved spec into components (the 'dissection' step) and validates them."""
from __future__ import annotations

import json
import re
import uuid

from . import claude, prompts
from .checks import command_problem
from .jobtypes import scaffold_files

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,19}$")


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def topo_order(components: list[dict]) -> list[dict]:
    by_id = {c["id"]: c for c in components}
    order, state = [], {}

    def visit(cid, stack):
        if state.get(cid) == "done":
            return
        if state.get(cid) == "visiting":
            raise ValueError("dependency cycle: " + " -> ".join(stack + [cid]))
        state[cid] = "visiting"
        for d in by_id[cid].get("depends_on", []):
            visit(d, stack + [cid])
        state[cid] = "done"
        order.append(by_id[cid])

    for c in components:
        visit(c["id"], [])
    return order


def validate(plan, cfg) -> list[str]:
    errs: list[str] = []
    if not isinstance(plan, dict):
        return ["top level must be a JSON object"]
    if not str(plan.get("project_summary", "")).strip():
        errs.append("project_summary is empty")
    comps = plan.get("components")
    maxc = cfg["limits"]["max_components"]
    if not isinstance(comps, list) or not comps:
        return errs + ["components must be a non-empty list"]
    if len(comps) > maxc:
        errs.append(f"{len(comps)} components; the limit is {maxc}. Merge small ones.")
    ids, owners = set(), {}
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            errs.append(f"component #{i + 1} is not an object")
            continue
        cid = c.get("id", "")
        if not ID_RE.match(str(cid)):
            errs.append(f"component #{i + 1} id {cid!r} must be short lowercase like 'c1'")
        if cid in ids:
            errs.append(f"duplicate id {cid}")
        ids.add(cid)
        for key in ("title", "instructions"):
            if not str(c.get(key, "")).strip():
                errs.append(f"{cid}: '{key}' is empty")
        c.setdefault("depends_on", [])
        c.setdefault("touches", [])
        c.setdefault("provides", "")
        c.setdefault("check", "")
        files = c.get("files")
        if not isinstance(files, list) or not files:
            errs.append(f"{cid}: 'files' must list the files it owns")
            files = []
        for f in files + list(c["touches"]):
            if not isinstance(f, str) or f.startswith("/") or ".." in f.split("/") or "\\" in f:
                errs.append(f"{cid}: bad path {f!r} (use relative paths inside the project)")
        for f in files:
            if f in owners:
                errs.append(f"{f} is owned by both {owners[f]} and {cid}; put it in 'touches' of one")
            owners[f] = cid
        if c["check"]:
            problem = command_problem(c["check"], cfg["checks"]["allow"])
            if problem:
                errs.append(f"{cid}: {problem}")
    for c in comps:
        if isinstance(c, dict):
            for d in c.get("depends_on", []):
                if d not in ids:
                    errs.append(f"{c.get('id')}: depends on unknown component {d!r}")
    if not errs:
        try:
            topo_order(comps)
        except ValueError as e:
            errs.append(str(e))
    return errs


def render_md(plan: dict) -> str:
    out = ["# Build plan", "", plan["project_summary"], ""]
    for c in topo_order(plan["components"]):
        out += [f"## {c['id']}: {c['title']}",
                f"- depends on: {', '.join(c['depends_on']) or 'nothing'}",
                f"- files: {', '.join(c['files'])}"]
        if c["touches"]:
            out.append(f"- touches: {', '.join(c['touches'])}")
        if c["check"]:
            out.append(f"- extra check: `{c['check']}`")
        out += ["", c["instructions"], "", f"Provides: {c['provides']}", ""]
    return "\n".join(out)


def make_plan(job, cfg) -> dict:
    """One chat, at most limits.max_plan_prompts prompts (the 2nd only fixes invalid JSON)."""
    spec = job.read("spec.approved.md") or job.read("spec.md")
    scaffold = sorted(scaffold_files(job.type, job.meta["title"]))
    allow = cfg["checks"]["allow"]
    prompt = prompts.plan(job.type, spec, scaffold, cfg["limits"]["max_components"], allow)
    session = str(uuid.uuid4())
    errs: list[str] = []
    for n in range(1, cfg["limits"]["max_plan_prompts"] + 1):
        out = claude.run(prompt, cfg=cfg, cwd=job.path, stage="plan", log_path=job.calls_log,
                         session=session, resume=n > 1, prompt_no=n, job_type=job.type)
        job.write(f"plan.raw{n}.txt", out)
        try:
            plan = extract_json(out)
            errs = validate(plan, cfg)
        except (json.JSONDecodeError, ValueError) as e:
            errs = [f"not valid JSON: {e}"]
        if not errs:
            plan["components"] = topo_order(plan["components"])
            return plan
        prompt = prompts.plan_fix(errs)
    raise SystemExit("Planner did not return a valid plan:\n- " + "\n- ".join(errs) +
                     f"\nRaw replies are in {job.path}. You can write plan.json by hand and run build.")
