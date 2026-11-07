#!/usr/bin/env python3
"""Built-in done-when checks. Run inside a job workspace:

    python3 validators.py <check> [--lenient] [args]

Exit codes: 0 pass, 1 fail, 77 skipped (a needed tool is not installed).
--lenient turns "referenced file missing" into a warning; it is used for the
per-component check, because a later component may create that file.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKIP = 77
IGNORE_DIRS = {"node_modules", ".git", "build", ".gradle", "dist", "out", "venv", ".venv",
               "__pycache__", "target", "run"}
LENIENT = False
problems: list[str] = []


def fail(msg: str):
    problems.append(msg)


def missing(path: str, what: str):
    if LENIENT:
        print(f"warning: {what} '{path}' does not exist yet")
    else:
        fail(f"{what} '{path}' does not exist")


def walk(exts: tuple[str, ...]):
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.endswith(exts):
                yield Path(root, f)


def run(cmd: list[str], timeout=900) -> int:
    print("$ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout + p.stderr).strip()
    if out:
        print(out[-6000:])
    return p.returncode


# ---------------------------------------------------------------- checks

def check_manifest():
    """Chrome extension Manifest V3."""
    p = Path("manifest.json")
    if not p.exists():
        return fail("manifest.json missing")
    try:
        m = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        return fail(f"manifest.json is not valid JSON: {e}")
    if m.get("manifest_version") != 3:
        fail("manifest_version must be 3")
    for key in ("name", "version"):
        if not m.get(key):
            fail(f"manifest.json needs '{key}'")
    if m.get("version") and not re.fullmatch(r"\d+(\.\d+){0,3}", str(m["version"])):
        fail("version must be 1-4 dot-separated integers")
    refs: list[str] = []
    bg = m.get("background") or {}
    if "scripts" in bg or "page" in bg:
        fail("MV3 uses background.service_worker, not background.scripts/page")
    if bg.get("service_worker"):
        refs.append(bg["service_worker"])
    action = m.get("action") or {}
    if "browser_action" in m or "page_action" in m:
        fail("MV3 uses 'action', not browser_action/page_action")
    if action.get("default_popup"):
        refs.append(action["default_popup"])
    for icon_set in (m.get("icons") or {}, action.get("default_icon") if isinstance(action.get("default_icon"), dict) else {}):
        refs += list(icon_set.values())
    if m.get("options_page"):
        refs.append(m["options_page"])
    if (m.get("options_ui") or {}).get("page"):
        refs.append(m["options_ui"]["page"])
    if (m.get("side_panel") or {}).get("default_path"):
        refs.append(m["side_panel"]["default_path"])
    for cs in m.get("content_scripts") or []:
        if not cs.get("matches"):
            fail("each content_scripts entry needs 'matches'")
        refs += cs.get("js", []) + cs.get("css", [])
    for war in m.get("web_accessible_resources") or []:
        if isinstance(war, dict):
            refs += [r for r in war.get("resources", []) if "*" not in r]
    for r in refs:
        if not Path(r.lstrip("/")).exists():
            missing(r, "manifest references")
    if "<all_urls>" in (m.get("permissions") or []):
        fail("'<all_urls>' belongs in host_permissions, not permissions")


def check_fxmanifest():
    """FiveM resource."""
    p = Path("fxmanifest.lua")
    if not p.exists():
        return fail("fxmanifest.lua missing")
    text = p.read_text()
    for key in ("fx_version", "game"):
        if not re.search(rf"^\s*{key}\s", text, re.M):
            fail(f"fxmanifest.lua needs {key}")
    keys = r"(client_scripts?|server_scripts?|shared_scripts?|ui_page|files|loadscreen)"
    for m in re.finditer(keys + r"\s*\{([^}]*)\}|" + keys + r"\s+['\"]([^'\"]+)['\"]", text):
        body = m.group(2) if m.group(2) is not None else m.group(4)
        for ref in re.findall(r"['\"]([^'\"]+)['\"]", body) if m.group(2) is not None else [body]:
            if ref.startswith("@") or "*" in ref:
                continue
            if not Path(ref).exists():
                missing(ref, "fxmanifest references")
    luac = shutil.which("luac") or shutil.which("luac5.4")
    if luac:
        for f in walk((".lua",)):
            if run([luac, "-p", str(f)]) != 0:
                fail(f"Lua syntax error in {f}")
    else:
        print("note: luac not installed, Lua syntax not checked")


def _java_class_exists(fqcn: str) -> bool:
    rel = fqcn.replace(".", "/") + ".java"
    return any(Path(base, rel).exists() for base in ("src/main/java", "src/main/kotlin"))


def check_plugin_yml():
    """Paper/Spigot plugin.yml."""
    p = Path("src/main/resources/plugin.yml")
    if not p.exists():
        p = Path("src/main/resources/paper-plugin.yml")
    if not p.exists():
        return fail("src/main/resources/plugin.yml missing")
    text = p.read_text()
    vals = dict(re.findall(r"^(name|main|version|api-version)\s*:\s*['\"]?([^'\"\n#]+)", text, re.M))
    for key in ("name", "main", "version"):
        if key not in vals:
            fail(f"plugin.yml needs '{key}'")
    if "main" in vals and not _java_class_exists(vals["main"].strip()):
        fail(f"main class {vals['main'].strip()} not found under src/main/java")


def check_fabric_json():
    p = Path("src/main/resources/fabric.mod.json")
    if not p.exists():
        return fail("src/main/resources/fabric.mod.json missing")
    try:
        m = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        return fail(f"fabric.mod.json is not valid JSON: {e}")
    for key in ("id", "version", "schemaVersion"):
        if key not in m:
            fail(f"fabric.mod.json needs '{key}'")
    for side, entries in (m.get("entrypoints") or {}).items():
        for e in entries:
            cls = e if isinstance(e, str) else e.get("value", "")
            if not _java_class_exists(cls.split("::")[0]):
                missing(cls, f"{side} entrypoint class")


def check_mods_toml():
    p = Path("src/main/resources/META-INF/mods.toml")
    if not p.exists():
        return fail("src/main/resources/META-INF/mods.toml missing")
    m = re.search(r"modId\s*=\s*\"([^\"]+)\"", p.read_text())
    if not m:
        return fail("mods.toml needs modId")
    mod_id = m.group(1)
    found = any(re.search(r"@Mod\(\s*(\"" + re.escape(mod_id) + r"\"|[A-Z_a-z.]+)\s*\)", f.read_text(errors="ignore"))
                for f in walk((".java",)))
    if not found:
        missing(f"@Mod(\"{mod_id}\")", "mod class")


def check_jsyntax():
    files = list(walk((".js", ".mjs", ".cjs")))
    if not files:
        return print("no JavaScript files")
    node = shutil.which("node")
    if not node:
        print("node not installed")
        sys.exit(SKIP)
    for f in files:
        if run([node, "--check", str(f)]) != 0:
            fail(f"syntax error in {f}")


def check_pysyntax():
    for f in walk((".py",)):
        try:
            compile(f.read_bytes(), str(f), "exec")
        except (SyntaxError, ValueError) as e:
            fail(f"syntax error in {f}: {e}")


def check_unittest():
    if not Path("tests").is_dir():
        return print("no tests/ folder")
    if run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]) != 0:
        fail("unit tests failed")


def check_npm_install():
    if not Path("package.json").exists():
        return print("no package.json")
    npm = shutil.which("npm")
    if not npm:
        print("npm not installed")
        sys.exit(SKIP)
    nm = Path("node_modules")
    if nm.exists() and nm.stat().st_mtime >= Path("package.json").stat().st_mtime:
        return print("node_modules up to date")
    if run([npm, "install", "--no-audit", "--no-fund"]) != 0:
        return fail("npm install failed")
    nm.mkdir(exist_ok=True)
    os.utime(nm)


def check_npm_test():
    if not Path("package.json").exists():
        return print("no package.json")
    scripts = json.loads(Path("package.json").read_text()).get("scripts", {})
    if not scripts.get("test") or "no test specified" in scripts["test"]:
        return print("no npm test script")
    npm = shutil.which("npm")
    if not npm:
        sys.exit(SKIP)
    if run([npm, "test", "--silent"]) != 0:
        fail("npm test failed")


def check_gradle(task: str = "build"):
    wrapper = Path("gradlew")
    if wrapper.exists():
        wrapper.chmod(0o755)
        cmd = ["./gradlew"]
    elif shutil.which("gradle"):
        cmd = ["gradle"]
    else:
        print("gradle not installed (brew install gradle)")
        sys.exit(SKIP)
    if run(cmd + ["--console=plain", "-q", task]) != 0:
        fail(f"gradle {task} failed")


SECRET_PATTERNS = {
    "Discord bot token": r"[MNO][A-Za-z\d_-]{23,27}\.[\w-]{6}\.[\w-]{27,40}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI-style key": r"\bsk-[A-Za-z0-9]{32,}",
    "AWS key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def check_secrets():
    for f in walk((".js", ".ts", ".mjs", ".cjs", ".py", ".java", ".lua", ".json", ".yml",
                   ".yaml", ".toml", ".properties", ".env", ".cfg", ".html", ".kt")):
        if f.name in ("package-lock.json",):
            continue
        text = f.read_text(errors="ignore")
        for label, pat in SECRET_PATTERNS.items():
            if re.search(pat, text):
                fail(f"{f} looks like it contains a hardcoded {label}")
    if Path(".env").exists():
        fail(".env must not be shipped; use .env.example")


CHECKS = {
    "manifest": check_manifest, "fxmanifest": check_fxmanifest, "plugin_yml": check_plugin_yml,
    "fabric_json": check_fabric_json, "mods_toml": check_mods_toml, "jsyntax": check_jsyntax,
    "pysyntax": check_pysyntax, "unittest": check_unittest, "npm_install": check_npm_install,
    "npm_test": check_npm_test, "gradle": check_gradle, "secrets": check_secrets,
}


def main(argv: list[str]) -> int:
    global LENIENT
    args = [a for a in argv if a != "--lenient"]
    LENIENT = len(args) != len(argv)
    if not args or args[0] not in CHECKS:
        print("usage: validators.py {" + ",".join(CHECKS) + "} [--lenient] [args]")
        return 2
    CHECKS[args[0]](*args[1:])
    for p in problems:
        print("FAIL: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
