#!/usr/bin/env python3
"""Tests for leads.py. Run: python3 tests/test_leads.py"""
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


class LeadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, COMMISSION_DATA=str(self.tmp / "data"),
                        CLAUDE_BIN=f"{sys.executable} {FAKE}", PIPELINE_CONFIG=str(self.tmp / "none.toml"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, script="leads.py", ok=True):
        p = subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True,
                           env=self.env, cwd=self.tmp, timeout=120)
        if ok and p.returncode != 0:
            self.fail(f"{script} {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
        return p

    def leads(self):
        return json.loads((self.tmp / "data" / "leads.json").read_text())

    def add(self, title="Custom ranks plugin", seen="10m", budget="$150"):
        self.run_cli("add", "--source", "Discord: #commissions", "--title", title, "--type", "paper",
                     "--budget", budget, "--seen", seen)

    def test_add_list_open(self):
        self.add()
        self.add("Old one")
        self.run_cli("status", "2", "dead")
        out = self.run_cli("list", "--open").stdout
        self.assertIn("Custom ranks", out)
        self.assertNotIn("Old one", out)
        self.assertIn("Old one", self.run_cli("list").stdout)

    def test_pitch_with_claude_and_offline(self):
        self.add()
        self.assertIn("server version", self.run_cli("pitch", "1").stdout)
        self.assertEqual(self.leads()[0]["status"], "pitched")
        out = self.run_cli("pitch", "1", "--offline").stdout
        self.assertIn("quote", out)
        self.assertNotIn("token", out.lower())

    def test_replied_and_stats(self):
        self.add(seen="10m")
        self.add("Second", seen="30m", budget="$200")
        self.run_cli("replied", "1")
        self.run_cli("replied", "2")
        l = self.leads()
        self.assertEqual(l[0]["status"], "replied")
        self.run_cli("status", "1", "won", "--price", "$180")
        self.run_cli("status", "2", "lost")
        out = self.run_cli("stats").stdout
        self.assertIn("Median reply time: 20 min", out)
        self.assertIn("Win rate: 50%", out)
        self.assertIn("$180 total", out)

    def test_replied_keeps_first_time(self):
        self.add()
        self.run_cli("replied", "1")
        first = self.leads()[0]["replied_at"]
        self.run_cli("replied", "1")
        self.assertEqual(self.leads()[0]["replied_at"], first)

    def test_lead_to_job(self):
        self.add()
        self.run_cli("job", "1")
        self.assertEqual(self.leads()[0]["job_id"], 1)
        brief = (self.tmp / "data" / "jobs" / "1" / "brief.md").read_text()
        self.assertIn("Custom ranks plugin", brief)

    def test_bad_seen(self):
        p = self.run_cli("add", "--source", "x", "--title", "y", "--seen", "soon", ok=False)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
