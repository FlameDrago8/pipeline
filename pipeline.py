#!/usr/bin/env python3
"""Commission pipeline: client request -> spec -> (you approve) -> plan -> build.

    python3 pipeline.py new "Job title" --type chrome_extension --brief "client's message"
    python3 pipeline.py spec 1          # Claude drafts spec.md + the reply to send the client
    python3 pipeline.py reply 1         # show the reply; add --client "..." to record their answer
    python3 pipeline.py approve 1       # you sign off on the spec
    python3 pipeline.py plan 1          # spec is split into components (one chat)
    python3 pipeline.py build 1         # each component built in its own chat, max 3 prompts
    python3 pipeline.py status [1]
    python3 pipeline.py go "one prompt describing the whole project" --type other

Run `python3 pipeline.py <command> -h` for options.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required (python3 --version).")

from pipelib import builder, claude, config, jobs, planner, prompts  # noqa: E402
from pipelib.jobtypes import TYPES  # noqa: E402

LEGACY_JOBS = Path(__file__).resolve().parent / "jobs"


def parse_spec_reply(text: str) -> tuple[str, str]:
    if "=== SPEC ===" in text and "=== REPLY ===" in text:
        spec = text.split("=== SPEC ===", 1)[1].split("=== REPLY ===", 1)[0].strip()
        reply = text.split("=== REPLY ===", 1)[1].strip()
        return spec, reply
    return text.strip(), ""


def read_text_arg(value: str | None, file: str | None) -> str | None:
    if file:
        return Path(file).expanduser().read_text()
    if value == "-":
        return sys.stdin.read()
    return value


# ---------------------------------------------------------------- commands

def cmd_new(args, cfg):
    brief = read_text_arg(args.brief, args.brief_file)
    lead_id = None
    if args.from_lead:
        import leads
        lead = leads.get_lead(cfg, args.from_lead)
        lead_id = lead["id"]
        brief = brief or f"{lead['title']}\nBudget: {lead.get('budget') or 'n/a'}\n\n{lead.get('notes', '')}"
    if not brief:
        brief = args.title
        print("No --brief given; the title is the brief. Paste the client's full message into "
              "brief.md before `spec` for a better result.")
    job = jobs.create(cfg, args.title, args.type, brief, lead_id)
    if lead_id:
        import leads
        leads.link_job(cfg, lead_id, job.id)
    print(f"Job {job.id} created: {args.title} [{args.type}]")
    print(f"  folder: {job.path}")
    print(f"  next:   python3 pipeline.py spec {job.id}")
    return job


def _show_spec(job):
    print(job.read("spec.md"))
    print("\n----- reply to send the client -----")
    print(job.read("reply.md") or "(none)")
    print("------------------------------------")


def cmd_spec(args, cfg):
    job = jobs.get(cfg, args.id)
    out = claude.run(prompts.spec(job.type, job.read("brief.md")), cfg=cfg, cwd=job.path,
                     stage="spec", log_path=job.calls_log, job_type=job.type)
    spec, reply = parse_spec_reply(out)
    job.write("spec.md", spec + "\n")
    job.write("reply.md", reply + "\n")
    job.set_status("specced")
    _show_spec(job)
    print(f"\nNext: send the reply, then `python3 pipeline.py reply {job.id} --client \"their answer\"`,"
          f" or `python3 pipeline.py approve {job.id}` if the spec is right.")


def cmd_reply(args, cfg):
    job = jobs.get(cfg, args.id)
    msg = read_text_arg(args.client, args.client_file)
    if not msg:
        print(job.read("reply.md") or "No reply drafted yet; run `spec` first.")
        return
    if not job.read("spec.md"):
        raise SystemExit("Run `spec` first.")
    with open(job.file("client_replies.md"), "a") as f:
        f.write(f"## {jobs.now()}\n{msg.strip()}\n\n")
    out = claude.run(prompts.revise(job.type, job.read("spec.md"), msg), cfg=cfg, cwd=job.path,
                     stage="revise", log_path=job.calls_log, job_type=job.type)
    spec, reply = parse_spec_reply(out)
    job.write("spec.md", spec + "\n")
    job.write("reply.md", reply + "\n")
    job.set_status("specced")
    _show_spec(job)


def cmd_approve(args, cfg):
    job = jobs.get(cfg, args.id)
    spec = job.read("spec.md")
    if not spec.strip():
        raise SystemExit("No spec to approve. Run `spec` first.")
    job.write("spec.approved.md", spec)
    job.set_status("approved")
    print(f"Spec for job {job.id} approved. Next: python3 pipeline.py plan {job.id}")


def cmd_plan(args, cfg):
    job = jobs.get(cfg, args.id)
    if args.show:
        print(job.read("plan.md") or "No plan yet.")
        return
    if job.meta["status"] not in ("approved", "planned", "build_failed") and not args.force:
        raise SystemExit("Approve the spec first (`approve`), or pass --force.")
    if job.workspace.exists() and not args.force:
        raise SystemExit("This job already has a workspace from an earlier build. Re-planning would "
                         "mix two plans; pass --force to re-plan anyway (build state is reset).")
    plan = planner.make_plan(job, cfg)
    if job.workspace.exists():
        old = job.path / f"workspace.old-{jobs.now().replace(':', '')}"
        job.workspace.rename(old)
        print(f"Old workspace moved to {old}")
    job.write_json("plan.json", plan)
    job.write("plan.md", planner.render_md(plan))
    if job.file("build.json").exists():
        job.file("build.json").unlink()
    job.set_status("planned")
    print(job.read("plan.md"))
    print(f"Plan saved to {job.file('plan.json')} (edit it if needed).")
    print(f"Next: python3 pipeline.py build {job.id}")


def cmd_build(args, cfg):
    job = jobs.get(cfg, args.id)
    status = builder.build(job, cfg, only=args.component, retry=args.retry)
    print(f"\nJob {job.id}: {status}")
    print(f"Code: {job.workspace}")
    if status.startswith("built"):
        print(f"Package for the client: python3 pipeline.py package {job.id}")
    elif status == "build_failed":
        print(f"See `python3 pipeline.py status {job.id}`. Fix by hand, or "
              f"`python3 pipeline.py build {job.id} --retry` (new chat, new prompt budget).")


def cmd_status(args, cfg):
    if args.id is None:
        all_jobs = jobs.all_jobs(cfg)
        if not all_jobs:
            print(f"No jobs yet (data folder: {cfg['data_dir']}).")
        for j in all_jobs:
            calls = j.calls()
            print(f"{j.id:>3}  {j.meta['status']:<17} {j.type:<17} {len(calls):>3} calls  {j.meta['title']}")
        if LEGACY_JOBS.exists() and LEGACY_JOBS != cfg["jobs_dir"]:
            print(f"\nNote: old jobs found in {LEGACY_JOBS}; jobs now live in {cfg['jobs_dir']}.")
        return
    job = jobs.get(cfg, args.id)
    print(f"Job {job.id}: {job.meta['title']} [{job.type}]  status: {job.meta['status']}")
    print(f"Folder: {job.path}")
    state = job.read_json("build.json")
    plan = job.read_json("plan.json")
    if plan:
        comps = (state or {}).get("components", {})
        print("\nComponents:")
        for c in plan["components"]:
            s = comps.get(c["id"], {"status": "pending", "prompts": 0})
            print(f"  {c['id']:<10} {s['status']:<16} prompts {s.get('prompts', 0)}  {c['title']}")
            if s.get("last_error") and s["status"] != "done":
                print("             " + s["last_error"].strip().splitlines()[-1][:150])
        if state and state.get("final"):
            f = state["final"]
            print(f"  {'final':<10} {f['status']:<16} prompts {f.get('prompts', 0)}")
            for sk in f.get("skipped", []):
                print(f"             skipped: {sk}")
    calls = job.calls()
    if calls:
        by_stage: dict[str, list] = {}
        for c in calls:
            by_stage.setdefault(c["stage"], []).append(c)
        print("\nClaude usage (calls / chars in / chars out / seconds):")
        for stage, cs in by_stage.items():
            print(f"  {stage:<10} {len(cs):>3}  {sum(c['prompt_chars'] for c in cs):>8}"
                  f"  {sum(c['output_chars'] for c in cs):>8}  {sum(c['seconds'] for c in cs):>7.0f}")
        sessions = {c["session"] for c in calls if c.get("session")}
        print(f"  {len(calls)} calls in {len(sessions) + sum(1 for c in calls if not c.get('session'))} separate chats")


def cmd_package(args, cfg):
    job = jobs.get(cfg, args.id)
    ws = job.workspace
    if not ws.exists():
        raise SystemExit("Nothing built yet.")
    out_dir = job.path / "deliver"
    out_dir.mkdir(exist_ok=True)
    name = jobs_slug(job.meta["title"])
    zpath = out_dir / f"{name}.zip"
    skip = builder.IGNORE | {".env"}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ws.rglob("*")):
            rel = p.relative_to(ws)
            if p.is_file() and not (set(rel.parts) & skip) and str(rel) not in (".env", "SPEC.md"):
                z.write(p, Path(name) / rel)
    print(f"Wrote {zpath}")
    if job.type in ("paper", "fabric", "forge", "hytale"):
        jars = list((ws / "build" / "libs").glob("*.jar")) if (ws / "build" / "libs").exists() else []
        for j in jars:
            shutil.copy(j, out_dir / j.name)
            print(f"Copied {out_dir / j.name}")


def jobs_slug(title: str) -> str:
    from pipelib.jobtypes import names
    return names(title)["slug"]


def cmd_go(args, cfg):
    """One prompt in, built project out. Stops for your approval unless --yes."""
    title = args.title or " ".join(args.prompt.split()[:6])
    ns = argparse.Namespace(title=title, type=args.type, brief=args.prompt, brief_file=None, from_lead=None)
    job = cmd_new(ns, cfg)
    cmd_spec(argparse.Namespace(id=job.id), cfg)
    if not args.yes:
        if not sys.stdin.isatty():
            print(f"Not approving automatically. Review, then: python3 pipeline.py approve {job.id}")
            return
        if input("\nApprove this spec and build it? [y/N] ").strip().lower() != "y":
            print(f"Stopped. Edit {job.file('spec.md')} or use `reply`, then `approve {job.id}`.")
            return
    cmd_approve(argparse.Namespace(id=job.id), cfg)
    cmd_plan(argparse.Namespace(id=job.id, show=False, force=False), cfg)
    cmd_build(argparse.Namespace(id=job.id, component=None, retry=False), cfg)
    print()
    cmd_status(argparse.Namespace(id=job.id), cfg)


def cmd_types(args, cfg):
    for name, t in TYPES.items():
        print(f"{name:<17} {t['label']}")
        print(f"{'':<17} final checks: {'; '.join(c.replace('{validators} ', '') for c in t['final'])}")


def cmd_doctor(args, cfg):
    print(f"python   {sys.version.split()[0]} ok")
    print(f"data     {cfg['data_dir']}")
    for tool, why in [("claude", "required"), ("git", "per-component history"),
                      ("node", "discord_bot / chrome_extension checks"), ("npm", "discord_bot installs"),
                      ("java", "Minecraft / Hytale builds"), ("gradle", "Minecraft / Hytale builds (brew install gradle)"),
                      ("luac", "FiveM Lua syntax check (brew install lua)")]:
        exe = cfg["claude"]["bin"].split()[0] if tool == "claude" else tool
        path = shutil.which(exe)
        version = ""
        if path and tool in ("claude", "node", "git"):
            version = subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip().splitlines()[0:1]
            version = version[0] if version else ""
        print(f"{tool:<8} {'ok  ' + version if path else 'MISSING'}  ({why})")
    if args.live:
        try:
            out = claude.run("Reply with exactly: OK", cfg=cfg, cwd=Path.cwd(), stage="doctor")
            print(f"live     claude replied: {out[:60]!r}")
        except claude.ClaudeError as e:
            print(f"live     FAILED: {e}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pipeline.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a job")
    s.add_argument("title")
    s.add_argument("--type", required=True, choices=list(TYPES))
    s.add_argument("--brief", help="client's request text ('-' reads stdin)")
    s.add_argument("--brief-file")
    s.add_argument("--from-lead", type=int, help="use a lead from leads.py as the brief")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("spec", help="draft spec + client reply (1 prompt, no tools)")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_spec)

    s = sub.add_parser("reply", help="show the reply to send, or record the client's answer")
    s.add_argument("id", type=int)
    s.add_argument("--client", help="what the client said ('-' reads stdin)")
    s.add_argument("--client-file")
    s.set_defaults(fn=cmd_reply)

    s = sub.add_parser("approve", help="approve the spec")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("plan", help="split the spec into components (1 chat, <=2 prompts)")
    s.add_argument("id", type=int)
    s.add_argument("--show", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("build", help="build each component in its own chat (<=3 prompts each)")
    s.add_argument("id", type=int)
    s.add_argument("--component", help="(re)build just this component, in a new chat")
    s.add_argument("--retry", action="store_true", help="give failed components a new chat")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("status", help="list jobs, or show one job")
    s.add_argument("id", type=int, nargs="?")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("package", help="zip the workspace for delivery")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_package)

    s = sub.add_parser("go", help="one prompt -> spec -> approve -> plan -> build")
    s.add_argument("prompt")
    s.add_argument("--type", required=True, choices=list(TYPES))
    s.add_argument("--title")
    s.add_argument("--yes", action="store_true", help="approve the spec without asking")
    s.set_defaults(fn=cmd_go)

    s = sub.add_parser("types", help="list job types")
    s.set_defaults(fn=cmd_types)

    s = sub.add_parser("doctor", help="check tools; --live sends one tiny prompt")
    s.add_argument("--live", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    cfg = config.load()
    try:
        args.fn(args, cfg)
    except claude.ClaudeError as e:
        raise SystemExit(f"Error: {e}")


if __name__ == "__main__":
    main()
