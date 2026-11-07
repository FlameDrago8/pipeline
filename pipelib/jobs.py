"""Job folders: <data_dir>/jobs/<id>/ with job.json, brief.md, spec.md, reply.md,
client_replies.md, plan.json, plan.md, build.json, calls.jsonl and workspace/."""
from __future__ import annotations

import json
import time
from pathlib import Path


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Job:
    def __init__(self, path: Path):
        self.path = path
        self.meta = json.loads((path / "job.json").read_text())

    @property
    def id(self) -> int:
        return self.meta["id"]

    @property
    def type(self) -> str:
        return self.meta["type"]

    @property
    def workspace(self) -> Path:
        return self.path / "workspace"

    @property
    def calls_log(self) -> Path:
        return self.path / "calls.jsonl"

    def file(self, name: str) -> Path:
        return self.path / name

    def read(self, name: str, default: str = "") -> str:
        p = self.path / name
        return p.read_text() if p.exists() else default

    def write(self, name: str, text: str):
        (self.path / name).write_text(text)

    def read_json(self, name: str, default=None):
        p = self.path / name
        return json.loads(p.read_text()) if p.exists() else default

    def write_json(self, name: str, data):
        (self.path / name).write_text(json.dumps(data, indent=2) + "\n")

    def set_status(self, status: str):
        self.meta["status"] = status
        self.meta.setdefault("history", []).append([now(), status])
        self.save()

    def save(self):
        self.write_json("job.json", self.meta)

    def calls(self) -> list[dict]:
        if not self.calls_log.exists():
            return []
        return [json.loads(l) for l in self.calls_log.read_text().splitlines() if l.strip()]


def all_jobs(cfg) -> list[Job]:
    d = cfg["jobs_dir"]
    if not d.exists():
        return []
    jobs = [Job(p) for p in d.iterdir() if (p / "job.json").exists()]
    return sorted(jobs, key=lambda j: j.id)


def get(cfg, job_id: int) -> Job:
    p = cfg["jobs_dir"] / str(job_id)
    if not (p / "job.json").exists():
        raise SystemExit(f"No job {job_id}. Run `python3 pipeline.py status` to list jobs.")
    return Job(p)


def create(cfg, title: str, job_type: str, brief: str, lead_id: int | None = None) -> Job:
    cfg["jobs_dir"].mkdir(parents=True, exist_ok=True)
    next_id = max([j.id for j in all_jobs(cfg)], default=0) + 1
    path = cfg["jobs_dir"] / str(next_id)
    path.mkdir()
    meta = {"id": next_id, "title": title, "type": job_type, "status": "new", "created": now(),
            "lead_id": lead_id, "history": [[now(), "new"]]}
    (path / "job.json").write_text(json.dumps(meta, indent=2) + "\n")
    (path / "brief.md").write_text(brief.strip() + "\n")
    return Job(path)
