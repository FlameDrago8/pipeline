#!/usr/bin/env python3
"""Stand-in for `claude -p` used by the tests. Reads the stage from env vars the
pipeline sets, writes files into the cwd like a build would, and logs argv.

FAKE_LOG          append one JSON line per call
FAKE_BROKEN=c1    component c1's first prompt writes broken code, the fix prompt repairs it
FAKE_ALWAYS_BROKEN=c1   c1 never gets fixed
FAKE_BAD_PLAN=1   first plan reply is invalid JSON
FAKE_EMPTY=1      reply with nothing
"""
import json
import os
import sys
from pathlib import Path

stage = os.environ.get("PIPELINE_STAGE", "")
comp = os.environ.get("PIPELINE_COMPONENT", "")
n = int(os.environ.get("PIPELINE_PROMPT_NO", "1"))
jtype = os.environ.get("PIPELINE_JOB_TYPE", "")
prompt = sys.stdin.read()

if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"stage": stage, "component": comp, "prompt_no": n, "argv": sys.argv[1:],
                            "prompt_chars": len(prompt)}) + "\n")

if os.environ.get("FAKE_EMPTY"):
    sys.exit(0)

SPEC = """=== SPEC ===
# Tab Counter
## Summary
Shows how many tabs are open.
## Features
1. Badge shows the tab count.
## Out of scope
Sync.
## Tech and versions
MV3.
## Done when
Manifest validates.
## Open questions
- Which browsers?
=== REPLY ===
Hey! I can build this. Should it count tabs in all windows or just the current one?"""

PLANS = {
    "chrome_extension": {
        "project_summary": "A Chrome extension that counts tabs.",
        "components": [
            {"id": "c1", "title": "Manifest and background", "depends_on": [],
             "files": ["background.js"], "touches": ["manifest.json"],
             "instructions": "Write the service worker and register it.", "provides": "badge updates"},
            {"id": "c2", "title": "Popup", "depends_on": ["c1"], "files": ["popup.html", "popup.js"],
             "touches": ["manifest.json"], "instructions": "Popup listing the count.", "provides": "",
             "check": "node --check popup.js"},
        ],
    },
    "other": {
        "project_summary": "A Python tool that adds numbers.",
        "components": [
            {"id": "core", "title": "Core", "depends_on": [], "files": ["app/__init__.py", "app/core.py"],
             "instructions": "add(a, b)", "provides": "app.core.add(a, b) -> int"},
            {"id": "cli", "title": "CLI and tests", "depends_on": ["core"],
             "files": ["main.py", "tests/test_core.py"], "instructions": "CLI + tests", "provides": ""},
        ],
    },
}


def write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def broken():
    if os.environ.get("FAKE_ALWAYS_BROKEN") == comp:
        return True
    return os.environ.get("FAKE_BROKEN") == comp and n == 1


if stage in ("spec", "revise"):
    print(SPEC)
elif stage == "plan":
    if os.environ.get("FAKE_BAD_PLAN") and n == 1:
        print("Here is the plan: {not json")
    else:
        print("```json\n" + json.dumps(PLANS[jtype], indent=1) + "\n```")
elif stage == "pitch":
    print("Hey! I can build that. Which server version are you on?")
elif stage == "doctor":
    print("OK")
elif stage in ("build", "integrate"):
    if jtype == "chrome_extension":
        try:
            m = json.loads(Path("manifest.json").read_text())
        except json.JSONDecodeError:
            m = {"manifest_version": 3, "name": "Tab counter", "version": "1.0.0"}
        if comp == "c1":
            write("background.js", "chrome.tabs.onCreated.addListener(() => {});\n")
            m["background"] = {"service_worker": "background.js"}
            if broken():
                write("manifest.json", "{ broken json")
                print("wrote c1")
                sys.exit(0)
        if comp == "c2":
            write("popup.html", "<script src='popup.js'></script>\n")
            write("popup.js", "const x = ;\n" if broken() else "document.title = 'tabs';\n")
            m["action"] = {"default_popup": "popup.html"}
        write("manifest.json", json.dumps(m, indent=2))
    elif jtype == "other":
        if comp == "core":
            write("app/__init__.py", "")
            write("app/core.py", "def add(a, b)\n    return a + b\n" if broken() else
                  "def add(a, b):\n    return a + b\n")
        if comp == "cli":
            write("main.py", "import sys\nfrom app.core import add\n\nif __name__ == '__main__':\n"
                             "    print(add(*map(int, sys.argv[1:3])))\n")
            write("tests/test_core.py", "import unittest\nfrom app.core import add\n\n\n"
                                        "class T(unittest.TestCase):\n    def test_add(self):\n"
                                        "        self.assertEqual(add(2, 3), 5)\n")
    print(f"built {comp} (prompt {n})")
else:
    print("ok")
