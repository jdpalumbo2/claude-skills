#!/usr/bin/env python3
"""Shared harness for the clodex exploit+control checks.

Every check drives the real artifacts — `skills/clodex/state/clodex_state.py`,
`skills/clodex/runner/run-codex.sh` — against a synthetic git repo built in a
temp dir, and asserts exit codes and file states. Nothing here mocks the
engine; a check that passes here passes against what a run actually executes.

The check vocabulary (from the 2026-08-11 fixes, committed this time):

* an **exploit** reproduces a failure the way it happened in the field. Before
  its fix lands the exploit FAILS (old behavior reproduces); after, it passes.
* a **control** proves the neighbouring legitimate behavior still works, so a
  fix cannot overcorrect silently.

Stdlib only, Python 3.9+.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parent.parent
STATE = CATALOGUE / "skills" / "clodex" / "state" / "clodex_state.py"
RUNNER = CATALOGUE / "skills" / "clodex" / "runner" / "run-codex.sh"


def run_state(args, stdin=None, cwd=None, env=None):
    """Run the state CLI exactly the way a skill does. Returns CompletedProcess."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(STATE)] + [str(a) for a in args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
    )


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )


class ClodexCheck(unittest.TestCase):
    """Base: a synthetic git repo per test, torn down afterwards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="clodex-check-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "check@clodex.test")
        git(self.repo, "config", "user.name", "clodex check")
        (self.repo / "README.md").write_text("synthetic repo\n")
        # The router's ignore remedy, pre-applied: run state never shows up in
        # `git status`, exactly as in a bootstrapped real repo.
        (self.repo / ".gitignore").write_text(".clodex/*\n!.clodex/profile.json\n")
        git(self.repo, "add", "README.md", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "init")

    def head(self):
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def make_run(self, run_id="r-2026-08-16-a", open_event=True):
        """Create the run dir the way the router does (mkdir first), and
        optionally record `run:opened` naming this repo and run id."""
        run_dir = self.repo / ".clodex" / run_id
        run_dir.mkdir(parents=True)
        if open_event:
            event = {
                "e": "run:opened",
                "run": run_id,
                "repo": str(self.repo),
                "branch": "main",
                "lane": "feature",
                "brief": "synthetic check run",
                "git": {"start_head": self.head(), "dirty_at_start": []},
            }
            result = self.append(run_dir, event)
            assert result.returncode == 0, (
                "harness could not open its own run: %s" % result.stderr
            )
        return run_dir

    def append(self, run_dir, event, cwd=None, extra_args=()):
        return run_state(
            ["append", str(run_dir)] + list(extra_args),
            stdin=json.dumps(event),
            cwd=cwd,
        )

    def rebuild(self, run_dir):
        result = run_state(["rebuild", str(run_dir)])
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
