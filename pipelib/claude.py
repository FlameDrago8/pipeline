"""Runs `claude -p` in plain-text mode. Every call is logged to the job's calls.jsonl.

Context control:
  * text stages (spec, plan, pitch) run with `--tools ""` so no tool schemas load;
  * build stages only get the file tools they need (no Bash, no MCP);
  * each component gets its own session id, so chats never share history.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path


class ClaudeError(RuntimeError):
    pass


def _bin(cfg) -> list[str]:
    return shlex.split(cfg["claude"]["bin"])


def run(prompt: str, *, cfg: dict, cwd: Path, stage: str, log_path: Path | None = None,
        tools: list[str] | None = None, session: str | None = None, resume: bool = False,
        component: str = "", prompt_no: int = 1, job_type: str = "") -> str:
    c = cfg["claude"]
    cmd = _bin(cfg) + ["-p", "--output-format", "text"]
    if c.get("model"):
        cmd += ["--model", c["model"]]
    if tools is None:
        cmd += ["--tools", "", "--max-turns", str(c["max_turns_text"])]
    else:
        joined = ",".join(tools)
        cmd += ["--tools", joined, "--allowedTools", joined,
                "--permission-mode", "acceptEdits", "--max-turns", str(c["max_turns_build"])]
    if session:
        cmd += ["--resume", session] if resume else ["--session-id", session]
    cmd += list(c.get("extra_args", []))

    env = dict(os.environ, PIPELINE_STAGE=stage, PIPELINE_COMPONENT=component,
               PIPELINE_PROMPT_NO=str(prompt_no), PIPELINE_JOB_TYPE=job_type)
    start = time.time()
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              cwd=str(cwd), timeout=c["timeout_sec"], env=env)
        rc, out, err = proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        raise ClaudeError(f"Claude Code not found ({cmd[0]}). Install it or set claude.bin in config.toml.")
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", f"timed out after {c['timeout_sec']}s"
    secs = round(time.time() - start, 1)

    if log_path is not None:
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": stage, "component": component,
               "prompt_no": prompt_no, "session": session, "resumed": resume, "seconds": secs,
               "prompt_chars": len(prompt), "output_chars": len(out), "exit": rc}
        with open(log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    if rc != 0:
        raise ClaudeError(f"claude exited {rc}: {(err or out)[-800:]}")
    if not out and tools is None:
        raise ClaudeError("claude returned an empty reply. Run `python3 pipeline.py doctor --live` "
                          "to check that Claude Code is signed in. stderr: " + err[-400:])
    return out
