"""Config loading. Python 3.11+ (tomllib), standard library only."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    # Jobs and leads live OUTSIDE the pipeline folder so replacing the
    # pipeline code never deletes client work.
    "data_dir": "~/commission-data",
    "claude": {
        "bin": "claude",
        "model": "",                 # "" = your account default
        "timeout_sec": 900,
        "max_turns_text": 2,         # spec / plan / pitch: no tools, one answer
        "max_turns_build": 40,       # one build prompt may use many tool turns
        "build_tools": ["Read", "Write", "Edit", "Glob", "Grep"],
        # Skip MCP servers: their tool schemas would be loaded into every chat.
        "extra_args": ["--strict-mcp-config"],
        # "resume": fix prompts continue the component's own chat.
        # "fresh": every fix prompt is a new chat with a compact context packet.
        "fix_mode": "resume",
    },
    "limits": {
        "max_prompts_per_component": 3,   # hard-capped at 3
        "max_plan_prompts": 2,
        "max_components": 8,
        "check_output_lines": 60,
    },
    "checks": {
        "timeout_sec": 900,
        # First word of any check command the PLANNER proposes must be one of these.
        "allow": ["node", "npm", "npx", "python3", "python", "gradle", "./gradlew",
                  "luac", "java", "javac", "mvn", "go", "cargo"],
    },
}


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(os.environ.get("PIPELINE_CONFIG", ROOT / "config.toml"))
    if path.exists():
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f))
    data = os.environ.get("COMMISSION_DATA") or cfg["data_dir"]
    data_dir = Path(data).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    cfg["data_dir"] = data_dir
    cfg["jobs_dir"] = data_dir / "jobs"
    cfg["leads_file"] = data_dir / "leads.json"
    env_bin = os.environ.get("CLAUDE_BIN")
    if env_bin:
        cfg["claude"]["bin"] = env_bin
    lim = cfg["limits"]
    lim["max_prompts_per_component"] = max(1, min(3, int(lim["max_prompts_per_component"])))
    lim["max_plan_prompts"] = max(1, min(3, int(lim["max_plan_prompts"])))
    return cfg
