#!/usr/bin/env python3
"""Lead log: record leads the moment you see them, draft a short first reply,
and track how fast you reply.

    python3 leads.py add --source "Discord: #commissions" --title "..." --type paper --budget "$150"
    python3 leads.py pitch 1            # one-prompt draft reply (--offline for a template)
    python3 leads.py replied 1          # you sent it; reply time is recorded
    python3 leads.py list --open
    python3 leads.py status 1 won       # new|pitched|replied|quoted|won|lost|dead
    python3 leads.py stats
    python3 leads.py job 1              # turn a won lead into a pipeline job

Never automate your Discord account: you copy the draft and send it yourself.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is required.")

from pipelib import claude, config, prompts  # noqa: E402
from pipelib.jobtypes import TYPES  # noqa: E402

STATUSES = ["new", "pitched", "replied", "quoted", "won", "lost", "dead"]
OPEN = {"new", "pitched", "replied", "quoted"}
FMT = "%Y-%m-%dT%H:%M:%S"


def now() -> str:
    return time.strftime(FMT)


def load(cfg) -> list[dict]:
    f: Path = cfg["leads_file"]
    return json.loads(f.read_text()) if f.exists() else []


def save(cfg, leads: list[dict]):
    f: Path = cfg["leads_file"]
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(leads, indent=2) + "\n")
    tmp.replace(f)


def get_lead(cfg, lead_id: int) -> dict:
    for l in load(cfg):
        if l["id"] == lead_id:
            return l
    raise SystemExit(f"No lead {lead_id}.")


def update(cfg, lead_id: int, **fields) -> dict:
    leads = load(cfg)
    for l in leads:
        if l["id"] == lead_id:
            l.update(fields)
            save(cfg, leads)
            return l
    raise SystemExit(f"No lead {lead_id}.")


def link_job(cfg, lead_id: int, job_id: int):
    update(cfg, lead_id, job_id=job_id)


def parse_ago(text: str | None) -> datetime:
    """'5m', '2h', '1d' or '' -> when the lead was posted."""
    if not text:
        return datetime.now()
    m = re.fullmatch(r"(\d+)\s*([mhd])", text.strip())
    if not m:
        raise SystemExit("--seen takes e.g. 5m, 2h or 1d (how long ago it was posted)")
    n, unit = int(m.group(1)), m.group(2)
    return datetime.now() - timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})


def minutes_between(a: str, b: str) -> float:
    return (datetime.strptime(b, FMT) - datetime.strptime(a, FMT)).total_seconds() / 60


def money(text: str | None) -> float:
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]
    return max(nums) if nums else 0.0


def show(l: dict):
    rt = ""
    if l.get("replied_at"):
        rt = f"  replied in {minutes_between(l['seen_at'], l['replied_at']):.0f}m"
    job = f"  job {l['job_id']}" if l.get("job_id") else ""
    print(f"{l['id']:>3}  {l['status']:<8} {l.get('type') or '-':<16} {l.get('budget') or '-':<8} "
          f"{l['title'][:50]}  ({l['source']}){rt}{job}")


# ---------------------------------------------------------------- commands

def cmd_add(a, cfg):
    leads = load(cfg)
    lead = {"id": max([l["id"] for l in leads], default=0) + 1, "source": a.source, "title": a.title,
            "type": a.type or "", "budget": a.budget or "", "url": a.url or "", "notes": a.notes or "",
            "seen_at": parse_ago(a.seen).strftime(FMT), "added_at": now(), "replied_at": None,
            "status": "new", "pitch": "", "job_id": None}
    leads.append(lead)
    save(cfg, leads)
    print(f"Lead {lead['id']} added. Draft a reply fast: python3 leads.py pitch {lead['id']}")


def offline_pitch(l: dict) -> str:
    q = {
        "paper": "which server version and do you need it to work with any other plugins?",
        "fabric": "which Minecraft version, and is it client-side, server-side or both?",
        "forge": "which Minecraft version, and is it client-side, server-side or both?",
        "discord_bot": "what are the main commands, and does it need to store data?",
        "chrome_extension": "which sites does it need to run on, and what should it do there?",
        "fivem": "which framework are you on (ESX, QBCore or standalone)?",
        "hytale": "what should it do in-game, in one or two sentences?",
    }.get(l.get("type", ""), "what's the one thing it absolutely has to do?")
    return f"Hey! I can build this for you. Quick question so I can quote it: {q}"


def cmd_pitch(a, cfg):
    l = get_lead(cfg, a.id)
    if a.offline:
        text = offline_pitch(l)
    else:
        cfg["data_dir"].mkdir(parents=True, exist_ok=True)
        try:
            text = claude.run(prompts.pitch(l), cfg=cfg, cwd=cfg["data_dir"], stage="pitch",
                              log_path=cfg["data_dir"] / "leads_calls.jsonl")
        except claude.ClaudeError as e:
            print(f"(Claude failed: {e}; using the offline template)", file=sys.stderr)
            text = offline_pitch(l)
    update(cfg, a.id, pitch=text, status="pitched" if l["status"] == "new" else l["status"])
    print(text)
    print(f"\nAfter sending it yourself: python3 leads.py replied {a.id}", file=sys.stderr)


def cmd_replied(a, cfg):
    l = get_lead(cfg, a.id)
    stamp = now()
    l = update(cfg, a.id, replied_at=l.get("replied_at") or stamp,
               status="replied" if l["status"] in ("new", "pitched") else l["status"])
    print(f"Lead {a.id}: replied {minutes_between(l['seen_at'], l['replied_at']):.0f} min after it was posted.")


def cmd_list(a, cfg):
    leads = load(cfg)
    if a.open:
        leads = [l for l in leads if l["status"] in OPEN]
    if not leads:
        print("No leads.")
    for l in leads:
        show(l)


def cmd_status(a, cfg):
    fields = {"status": a.status}
    if a.price:
        fields["price"] = a.price
    update(cfg, a.id, **fields)
    print(f"Lead {a.id} -> {a.status}")


def cmd_show(a, cfg):
    l = get_lead(cfg, a.id)
    for k, v in l.items():
        print(f"{k:<11} {v}")


def cmd_stats(a, cfg):
    leads = load(cfg)
    if not leads:
        return print("No leads yet.")
    counts = {s: sum(1 for l in leads if l["status"] == s) for s in STATUSES}
    print("Leads: " + ", ".join(f"{s} {n}" for s, n in counts.items() if n) + f"  (total {len(leads)})")
    times = [minutes_between(l["seen_at"], l["replied_at"]) for l in leads if l.get("replied_at")]
    if times:
        print(f"Median reply time: {statistics.median(times):.0f} min  (fastest {min(times):.0f}, "
              f"slowest {max(times):.0f}, n={len(times)})")
    decided = counts["won"] + counts["lost"]
    if decided:
        print(f"Win rate: {counts['won'] / decided:.0%} of {decided} decided")
    won = [l for l in leads if l["status"] == "won"]
    if won:
        total = sum(money(l.get("price") or l.get("budget")) for l in won)
        print(f"Won: {len(won)} jobs, ${total:,.0f} total, ${total / len(won):,.0f} average  "
              f"(goal $50,000: {total / 50000:.1%})")
    by_source: dict[str, list] = {}
    for l in leads:
        by_source.setdefault(l["source"], []).append(l)
    print("By source:")
    for src, ls in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        print(f"  {src:<30} {len(ls):>3} leads, {sum(1 for l in ls if l['status'] == 'won')} won")


def cmd_job(a, cfg):
    l = get_lead(cfg, a.id)
    jtype = a.type or l.get("type")
    if jtype not in TYPES:
        raise SystemExit(f"Give --type (one of {', '.join(TYPES)})")
    import pipeline
    ns = argparse.Namespace(title=l["title"], type=jtype, brief=None, brief_file=None, from_lead=l["id"])
    pipeline.cmd_new(ns, cfg)


def main(argv=None):
    p = argparse.ArgumentParser(prog="leads.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add")
    s.add_argument("--source", required=True, help='e.g. "Discord: #commissions"')
    s.add_argument("--title", required=True)
    s.add_argument("--type", choices=list(TYPES))
    s.add_argument("--budget")
    s.add_argument("--url")
    s.add_argument("--notes", help="paste the post")
    s.add_argument("--seen", help="how long ago it was posted: 5m, 2h, 1d")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("pitch")
    s.add_argument("id", type=int)
    s.add_argument("--offline", action="store_true", help="template only, no Claude call")
    s.set_defaults(fn=cmd_pitch)

    s = sub.add_parser("replied")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_replied)

    s = sub.add_parser("list")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("status")
    s.add_argument("id", type=int)
    s.add_argument("status", choices=STATUSES)
    s.add_argument("--price", help="agreed price, used by stats")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("show")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("stats")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("job", help="create a pipeline job from a lead")
    s.add_argument("id", type=int)
    s.add_argument("--type", choices=list(TYPES))
    s.set_defaults(fn=cmd_job)

    args = p.parse_args(argv)
    args.fn(args, config.load())


if __name__ == "__main__":
    main()
