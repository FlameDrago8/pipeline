"""Runs done-when check commands inside a workspace. No shell: commands are
split with shlex, `&&` chains are run step by step, and commands proposed by
the planner must start with an allow-listed program."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

VALIDATORS = Path(__file__).resolve().parent / "validators.py"
SKIP = 77
FORBIDDEN = set(";|><`$")


@dataclass
class CheckResult:
    ok: bool = True
    skipped: list[str] = field(default_factory=list)
    failed_cmd: str = ""
    output: str = ""


def command_problem(cmd: str, allow: list[str]) -> str | None:
    """Return why a planner-proposed command is not allowed, or None."""
    if any(ch in FORBIDDEN for ch in cmd.replace("&&", "")) or "&" in cmd.replace("&&", ""):
        return f"shell operators are not allowed in check commands: {cmd!r}"
    for part in cmd.split("&&"):
        try:
            words = shlex.split(part)
        except ValueError as e:
            return f"cannot parse {cmd!r}: {e}"
        if not words:
            return f"empty step in {cmd!r}"
        if words[0] not in allow and words[0] != "{validators}":
            return f"'{words[0]}' is not in checks.allow (config.toml)"
        if any(w.startswith("/") or ".." in w for w in words[1:]):
            return f"check commands must stay inside the project: {cmd!r}"
    return None


def _expand(words: list[str]) -> list[str]:
    if words and words[0] == "{validators}":
        return [sys.executable, str(VALIDATORS)] + words[1:]
    if words and words[0] in ("python3", "python"):
        return [sys.executable] + words[1:]
    return words


def run_checks(cmds: list[str], cwd: Path, cfg: dict, tail: int | None = None) -> CheckResult:
    tail = tail or cfg["limits"]["check_output_lines"]
    res = CheckResult()
    for cmd in cmds:
        for part in cmd.split("&&"):
            words = _expand(shlex.split(part))
            if not shutil.which(words[0]) and not Path(cwd, words[0]).exists():
                res.skipped.append(f"{part.strip()} ({words[0]} not installed)")
                break
            try:
                p = subprocess.run(words, cwd=str(cwd), capture_output=True, text=True,
                                   timeout=cfg["checks"]["timeout_sec"])
                rc, out = p.returncode, (p.stdout + p.stderr)
            except subprocess.TimeoutExpired:
                rc, out = 1, f"timed out after {cfg['checks']['timeout_sec']}s"
            if rc == SKIP:
                res.skipped.append(f"{part.strip()}: {out.strip().splitlines()[-1] if out.strip() else 'skipped'}")
                break
            if rc != 0:
                lines = out.strip().splitlines()
                res.ok = False
                res.failed_cmd = part.strip()
                res.output = "\n".join(lines[-tail:])
                return res
    return res
