#!/usr/bin/env python3
"""End-to-end tests of pipeline.py using a fake `claude`. Run: python3 tests/test_flow.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = Path(__file__).resolve().parent / "fake_claude.py"
sys.path.insert(0, str(ROOT))

from pipelib import config, planner  # noqa: E402
from pipelib.checks import command_problem, run_checks  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log = self.tmp / "calls.jsonl"
        self.env = dict(os.environ, COMMISSION_DATA=str(self.tmp / "data"),
                        CLAUDE_BIN=f"{sys.executable} {FAKE}", FAKE_LOG=str(self.log),
                        PIPELINE_CONFIG=str(self.tmp / "none.toml"))
        for k in ("FAKE_BROKEN", "FAKE_ALWAYS_BROKEN", "FAKE_BAD_PLAN", "FAKE_EMPTY"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, ok=True, **env):
        p = subprocess.run([sys.executable, str(ROOT / "pipeline.py"), *args], cwd=self.tmp,
                           capture_output=True, text=True, env=dict(self.env, **env), timeout=300)
        if ok and p.returncode != 0:
            self.fail(f"pipeline.py {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
        return p

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def job_dir(self, n=1):
        return self.tmp / "data" / "jobs" / str(n)

    def job(self, n=1):
        return json.loads((self.job_dir(n) / "job.json").read_text())

    def build_state(self, n=1):
        return json.loads((self.job_dir(n) / "build.json").read_text())

    def through_plan(self, jtype="chrome_extension", **env):
        self.run_cli("new", "Tab counter", "--type", jtype, "--brief", "count my tabs please")
        self.run_cli("spec", "1")
        self.run_cli("approve", "1")
        self.run_cli("plan", "1", **env)


class FlowTests(Base):
    def test_full_flow_chrome(self):
        self.run_cli("new", "Tab counter", "--type", "chrome_extension", "--brief", "count my tabs")
        out = self.run_cli("spec", "1").stdout
        self.assertIn("reply to send the client", out)
        self.assertIn("all windows", (self.job_dir() / "reply.md").read_text())
        self.assertIn("# Tab Counter", (self.job_dir() / "spec.md").read_text())
        self.assertIn("all windows", self.run_cli("reply", "1").stdout)
        self.run_cli("reply", "1", "--client", "all windows please")
        self.assertIn("all windows please", (self.job_dir() / "client_replies.md").read_text())
        self.run_cli("plan", "1", ok=False)  # not approved yet
        self.run_cli("approve", "1")
        self.run_cli("plan", "1")
        self.assertEqual(self.job()["status"], "planned")
        out = self.run_cli("build", "1").stdout
        self.assertIn(self.job()["status"], ("built", "built_unverified"), out)
        ws = self.job_dir() / "workspace"
        m = json.loads((ws / "manifest.json").read_text())
        self.assertEqual(m["action"]["default_popup"], "popup.html")
        self.assertIn("Components:", self.run_cli("status", "1").stdout)
        self.assertIn("Tab counter", self.run_cli("status").stdout)
        self.run_cli("package", "1")
        self.assertTrue((self.job_dir() / "deliver" / "tab-counter.zip").exists())

    def test_each_component_gets_its_own_chat_and_text_stages_have_no_tools(self):
        self.through_plan()
        self.run_cli("build", "1")
        calls = self.calls()
        for c in calls:
            if c["stage"] in ("spec", "plan"):
                i = c["argv"].index("--tools")
                self.assertEqual(c["argv"][i + 1], "", "text stages must run without tools")
            self.assertIn("--strict-mcp-config", c["argv"])
        builds = [c for c in calls if c["stage"] == "build"]
        self.assertEqual({c["component"] for c in builds}, {"c1", "c2"})
        sessions = {}
        for c in builds:
            argv = c["argv"]
            flag = "--session-id" if "--session-id" in argv else "--resume"
            sessions.setdefault(c["component"], set()).add(argv[argv.index(flag) + 1])
        self.assertEqual(len(sessions["c1"]), 1)
        self.assertTrue(sessions["c1"].isdisjoint(sessions["c2"]), "components must not share a chat")
        tools = builds[0]["argv"][builds[0]["argv"].index("--tools") + 1]
        self.assertNotIn("Bash", tools)

    def test_fix_prompt_resumes_same_chat(self):
        self.through_plan()
        self.run_cli("build", "1", FAKE_BROKEN="c1")
        st = self.build_state()["components"]["c1"]
        self.assertEqual(st["status"][:4], "done")
        self.assertEqual(st["prompts"], 2)
        c1 = [c for c in self.calls() if c["component"] == "c1"]
        self.assertIn("--session-id", c1[0]["argv"])
        self.assertIn("--resume", c1[1]["argv"])
        self.assertEqual(c1[0]["argv"][c1[0]["argv"].index("--session-id") + 1],
                         c1[1]["argv"][c1[1]["argv"].index("--resume") + 1])

    def test_prompt_cap_and_blocking(self):
        self.through_plan()
        self.run_cli("build", "1", FAKE_ALWAYS_BROKEN="c1")
        comps = self.build_state()["components"]
        self.assertEqual(comps["c1"]["status"], "failed")
        self.assertEqual(comps["c1"]["prompts"], 3)
        self.assertEqual(comps["c2"]["status"], "blocked")
        self.assertEqual(self.job()["status"], "build_failed")
        self.assertEqual(len([c for c in self.calls() if c["component"] == "c1"]), 3)
        # --retry gives c1 a fresh chat; this time the fake is fixed
        self.run_cli("build", "1", "--retry")
        self.assertIn(self.job()["status"], ("built", "built_unverified"))

    def test_fresh_fix_mode(self):
        (self.tmp / "fresh.toml").write_text('[claude]\nfix_mode = "fresh"\n')
        self.env["PIPELINE_CONFIG"] = str(self.tmp / "fresh.toml")
        self.through_plan()
        self.run_cli("build", "1", FAKE_BROKEN="c1")
        c1 = [c for c in self.calls() if c["component"] == "c1"]
        self.assertEqual(len(c1), 2)
        self.assertTrue(all("--resume" not in c["argv"] for c in c1))

    def test_invalid_plan_gets_one_fix_prompt(self):
        self.through_plan(FAKE_BAD_PLAN="1")
        plans = [c for c in self.calls() if c["stage"] == "plan"]
        self.assertEqual(len(plans), 2)
        self.assertIn("--resume", plans[1]["argv"])
        self.assertTrue((self.job_dir() / "plan.json").exists())

    def test_python_job_runs_unit_tests(self):
        self.through_plan("other")
        self.run_cli("build", "1", FAKE_BROKEN="core")
        self.assertEqual(self.job()["status"], "built")
        self.assertEqual(self.build_state()["components"]["core"]["prompts"], 2)

    def test_go_one_prompt(self):
        p = self.run_cli("go", "A python tool that adds two numbers", "--type", "other", "--yes")
        self.assertIn("built", self.job()["status"], p.stdout)
        stages = [c["stage"] for c in self.calls()]
        self.assertEqual(stages[:2], ["spec", "plan"])

    def test_empty_reply_is_an_error(self):
        self.run_cli("new", "x", "--type", "other", "--brief", "x")
        p = self.run_cli("spec", "1", ok=False, FAKE_EMPTY="1")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("empty reply", p.stderr)

    def test_doctor(self):
        self.assertIn("OK", self.run_cli("doctor", "--live").stdout)


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()

    def plan(self, comps):
        return {"project_summary": "x", "components": comps}

    def comp(self, cid, deps=(), files=None, **kw):
        return dict({"id": cid, "title": cid, "instructions": "do", "depends_on": list(deps),
                     "files": files or [f"{cid}.js"]}, **kw)

    def test_valid_plan(self):
        p = self.plan([self.comp("c2", ["c1"]), self.comp("c1")])
        self.assertEqual(planner.validate(p, self.cfg), [])
        self.assertEqual([c["id"] for c in planner.topo_order(p["components"])], ["c1", "c2"])

    def test_cycle_unknown_dep_dupe_owner_bad_path(self):
        self.assertTrue(any("cycle" in e for e in planner.validate(
            self.plan([self.comp("a", ["b"]), self.comp("b", ["a"])]), self.cfg)))
        self.assertTrue(any("unknown" in e for e in planner.validate(
            self.plan([self.comp("a", ["zz"])]), self.cfg)))
        self.assertTrue(any("owned by both" in e for e in planner.validate(
            self.plan([self.comp("a", files=["x.js"]), self.comp("b", files=["x.js"])]), self.cfg)))
        self.assertTrue(any("bad path" in e for e in planner.validate(
            self.plan([self.comp("a", files=["../x.js"])]), self.cfg)))

    def test_too_many_components(self):
        p = self.plan([self.comp(f"c{i}") for i in range(20)])
        self.assertTrue(any("limit" in e for e in planner.validate(p, self.cfg)))

    def test_check_allowlist(self):
        allow = self.cfg["checks"]["allow"]
        self.assertIsNone(command_problem("node --check a.js", allow))
        self.assertIsNone(command_problem("npm install && npm test", allow))
        self.assertIsNotNone(command_problem("rm -rf /", allow))
        self.assertIsNotNone(command_problem("node a.js; curl x", allow))
        self.assertIsNotNone(command_problem("node a.js | sh", allow))
        self.assertIsNotNone(command_problem("python3 /etc/x.py", allow))

    def test_extract_json(self):
        self.assertEqual(planner.extract_json('blah ```json\n{"a": 1}\n``` blah'), {"a": 1})
        self.assertEqual(planner.extract_json('sure {"a": {"b": 2}} done'), {"a": {"b": 2}})

    def test_validators(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "manifest.json").write_text(json.dumps({"manifest_version": 2, "name": "x", "version": "1"}))
            self.assertFalse(run_checks(["{validators} manifest"], ws, self.cfg).ok)
            (ws / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": "x", "version": "1",
                                                          "action": {"default_popup": "p.html"}}))
            self.assertFalse(run_checks(["{validators} manifest"], ws, self.cfg).ok)
            self.assertTrue(run_checks(["{validators} manifest --lenient"], ws, self.cfg).ok)
            (ws / "p.html").write_text("<p>")
            self.assertTrue(run_checks(["{validators} manifest"], ws, self.cfg).ok)
            # Fake token assembled at runtime so secret scanners don't flag this file.
            fake = ".".join(["MTA4NzY1NDMyMTA5ODc2NTQzMg", "GaBcDe", "abcdefghijklmnopqrstuvwxyz0123456"])
            (ws / "bot.js").write_text(f"const t = '{fake}';\n")
            self.assertFalse(run_checks(["{validators} secrets"], ws, self.cfg).ok)

    def test_scaffolds_are_valid(self):
        from pipelib.jobtypes import TYPES, scaffold_files
        for jt in TYPES:
            files = scaffold_files(jt, "My Cool Thing 2")
            self.assertTrue(files, jt)
            for path, body in files.items():
                if path.endswith(".json"):
                    json.loads(body)
        with tempfile.TemporaryDirectory() as d:
            for path, body in scaffold_files("paper", "My Cool Thing").items():
                p = Path(d, path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body)
            self.assertTrue(run_checks(["{validators} plugin_yml"], Path(d), self.cfg).ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
