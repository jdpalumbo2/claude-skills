#!/usr/bin/env python3
"""Exploit+control checks for the `boundary-check` verb (task 2.4, debt #6).

The field failure: clodex-build §7 compared the tree against the AT-OPEN dirty
snapshot. In a repo with a concurrent session that snapshot is stale within
minutes — the CRE pilot's check printed `STOP — 9 path(s)` where none of the
nine was the implementer's, and §7's remedy would have reverted another
session's working files. The fix: classify against a PRE-INVOCATION baseline
captured immediately before the batch opens.
"""

import subprocess
import unittest

from clodex_harness import ClodexCheck, git, run_state


class BoundaryCheck(ClodexCheck):
    def boundary(self, run_dir, owned=(), baseline=None):
        args = ["boundary-check", str(run_dir)]
        for path in owned:
            args += ["--owned", path]
        if baseline is not None:
            args += ["--baseline", str(baseline)]
        return run_state(args)

    def capture_baseline(self, name="batch-1.pre"):
        raw = subprocess.run(
            ["git", "-C", str(self.repo), "status", "--porcelain", "-z",
             "--untracked-files=all"],
            capture_output=True, check=True,
        ).stdout
        path = self.repo / ".clodex" / "r-2026-08-16-a" / name
        path.write_bytes(raw)
        return path

    def test_exploit_concurrent_work_is_not_misattributed(self):
        run_dir = self.make_run()  # tree clean at open; dirty_at_start = []
        # A concurrent session works between open and the batch:
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "other_session.py").write_text("their work\n")
        # The pre-invocation baseline is captured, then the implementer runs:
        baseline = self.capture_baseline()
        (self.repo / "owned").mkdir()
        (self.repo / "owned" / "mine.py").write_text("the batch's work\n")

        # Old behavior (no baseline → at-open snapshot): their file reads as a
        # stray and the remedy targets their working tree.
        stale = self.boundary(run_dir, owned=["owned/"])
        self.assertEqual(stale.returncode, 1, stale.stdout)
        self.assertIn("scripts/other_session.py", stale.stdout)

        # Fixed behavior: the baseline acknowledges it; the contract held.
        result = self.boundary(run_dir, owned=["owned/"], baseline=baseline)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("acknowledged", result.stdout)
        self.assertIn("clean — the contract held", result.stdout)

    def test_control_a_real_stray_still_stops_the_run(self):
        run_dir = self.make_run()
        baseline = self.capture_baseline()
        (self.repo / "owned").mkdir()
        (self.repo / "owned" / "mine.py").write_text("fine\n")
        (self.repo / "sneaky.py").write_text("outside the contract\n")
        result = self.boundary(run_dir, owned=["owned/"], baseline=baseline)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("STRAY", result.stdout)
        self.assertIn("STOP — 1 path(s)", result.stdout)
        self.assertIn("sneaky.py", result.stdout)

    def test_control_owned_only_changes_are_clean(self):
        run_dir = self.make_run()
        baseline = self.capture_baseline()
        (self.repo / "owned").mkdir()
        (self.repo / "owned" / "mine.py").write_text("fine\n")
        result = self.boundary(run_dir, owned=["owned/"], baseline=baseline)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("clean — the contract held", result.stdout)

    def test_control_rename_origin_counts_against_the_contract(self):
        # A staged move OUT of an unowned path INTO an owned one must flag the
        # origin — otherwise the batch commits a file it never owned.
        run_dir = self.make_run()
        baseline = self.capture_baseline()
        (self.repo / "owned").mkdir()
        git(self.repo, "mv", "README.md", "owned/readme.md")
        result = self.boundary(run_dir, owned=["owned/"], baseline=baseline)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("README.md", result.stdout)

    def test_control_owned_paths_default_to_the_open_batch(self):
        run_dir = self.make_run()
        self.append(run_dir, {"e": "stage:plan:entered"})
        self.append(run_dir, {"e": "stage:build:entered"})
        result = self.append(
            run_dir, {"e": "batch:opened", "id": 1, "owned_paths": ["owned/"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        baseline = self.capture_baseline()
        (self.repo / "owned").mkdir()
        (self.repo / "owned" / "mine.py").write_text("fine\n")
        result = self.boundary(run_dir, baseline=baseline)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
