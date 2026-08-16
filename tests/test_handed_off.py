#!/usr/bin/env python3
"""Exploit+control checks for the `handed-off` terminal state (task 3.2) and
its §10 guards — the orchestrated-lane shape becoming legal instead of four
successful lanes recording `release: abandoned` with "by design" prose.
"""

import json
import re
import subprocess
import sys
import unittest

from clodex_harness import CATALOGUE, ClodexCheck

SHIP = CATALOGUE / "skills" / "clodex-ship" / "SKILL.md"
STATE = CATALOGUE / "skills" / "clodex" / "state" / "clodex_state.py"

PLAN_HASH = "ab" * 32


def extract_exit_script():
    """Ship §10's exit script, straight out of the document."""
    text = SHIP.read_text()
    for match in re.finditer(r"<<'PY'\n(.*?)\nPY\n", text, re.S):
        if "SHIP COMPLETE" in match.group(1):
            return match.group(1)
    raise AssertionError("cannot find the §10 exit script in clodex-ship/SKILL.md")


def base_profile(**overrides):
    profile = {
        "schema_version": 1,
        "commands": {"install": None, "build": None, "test": None,
                     "lint": None, "typecheck": None},
        "version": {"source": "VERSION", "field": None, "bump_rule": "semver"},
        "branch": {"default": "main", "work_on_default": False,
                   "naming": "feature/<slug>"},
        "tag": {"enabled": False, "format": None},
        "changelog": None,
        "docs": {"architecture": [], "plans_dir": "docs/plans"},
        "deploy": None,
        "evidence": {"default_classes": ["tests"]},
        "runtimes": [],
        "required_env": [],
        "actions": [],
    }
    profile.update(overrides)
    return profile


class HandedOff(ClodexCheck):
    def open_through_ship(self, run_dir, handoff=True):
        """The external-owner lane's event sequence, open → ship."""
        events = [
            {"e": "stage:plan:entered"},
            {"e": "plan:recorded", "version": 1,
             "path": "docs/plans/2026-08-16-lane.md", "hash": PLAN_HASH},
            {"e": "plan:approved", "scope": "plan", "by": "user",
             "plan_version": 1, "plan_hash": PLAN_HASH},
            {"e": "stage:build:entered"},
            {"e": "stage:verify:entered"},
            {"e": "stage:ship:entered"},
            {"e": "approval:granted", "scope": "release-authorization",
             "by": "user", "plan_version": 1, "plan_hash": PLAN_HASH,
             "actions": [], "accepted_debt": []},
        ]
        if handoff:
            events.append(
                {"e": "approval:granted", "scope": "handoff", "by": "user",
                 "plan_version": 1, "plan_hash": PLAN_HASH,
                 "actions": [{"artifact": ".clodex/r-2026-08-16-a/handoff.md",
                              "branch": "feature/lane", "base": "deadbeef"}]}
            )
        for event in events:
            result = self.append(run_dir, event)
            assert result.returncode == 0, (event, result.stderr)

    def run_exit_script(self, run_dir):
        return subprocess.run(
            [sys.executable, "-", str(STATE), str(run_dir),
             str(self.repo / ".clodex" / "profile.json")],
            input=extract_exit_script(), capture_output=True, text=True,
            cwd=self.repo,
        )

    def test_exploit_external_lane_closes_handed_off(self):
        # Pre-3.2 this state was refused at append: the enum had no such name,
        # and the only escape for a fully successful lane was `abandoned`.
        run_dir = self.make_run()
        (self.repo / ".clodex" / "profile.json").write_text(
            json.dumps(base_profile(release_owner="external")))
        self.open_through_ship(run_dir)
        result = self.append(run_dir, {
            "e": "release:updated", "state": "handed-off",
            "deployed": "handoff: .clodex/r-2026-08-16-a/handoff.md",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.append(run_dir, {"e": "run:closed"})
        self.assertEqual(result.returncode, 0, result.stderr)

        snap = self.rebuild(run_dir)
        self.assertEqual(snap["release"]["state"], "handed-off")
        self.assertEqual(snap["stage"], "closed")
        handoff = [a for a in snap["approvals"]
                   if a["scope"] == "handoff" and a["revoked"] is None]
        self.assertEqual(len(handoff), 1)
        # actions[] persisted verbatim — the artifact pointer survives.
        self.assertEqual(handoff[0]["actions"][0]["artifact"],
                         ".clodex/r-2026-08-16-a/handoff.md")

        exit_check = self.run_exit_script(run_dir)
        self.assertIn("SHIP COMPLETE — release handed-off", exit_check.stdout,
                      exit_check.stdout + exit_check.stderr)

    def test_control_handed_off_without_external_owner_blocks(self):
        run_dir = self.make_run()
        (self.repo / ".clodex" / "profile.json").write_text(
            json.dumps(base_profile()))  # release_owner absent => "run"
        self.open_through_ship(run_dir)
        self.append(run_dir, {"e": "release:updated", "state": "handed-off",
                              "deployed": "handoff: x"})
        self.append(run_dir, {"e": "run:closed"})
        exit_check = self.run_exit_script(run_dir)
        self.assertIn("NOT DONE", exit_check.stdout, exit_check.stdout)
        self.assertIn("release_owner", exit_check.stdout)

    def test_control_handed_off_without_an_artifact_blocks(self):
        run_dir = self.make_run()
        (self.repo / ".clodex" / "profile.json").write_text(
            json.dumps(base_profile(release_owner="external")))
        self.open_through_ship(run_dir, handoff=False)
        self.append(run_dir, {"e": "release:updated", "state": "handed-off",
                              "deployed": "handoff: x"})
        self.append(run_dir, {"e": "run:closed"})
        exit_check = self.run_exit_script(run_dir)
        self.assertIn("NOT DONE", exit_check.stdout, exit_check.stdout)
        self.assertIn("handoff approval", exit_check.stdout)

    def test_control_run_owned_terminals_unchanged(self):
        # A release_owner: "run" repo behaves as v0.2.0: unknown states still
        # refuse, and the ordinary terminal still closes.
        run_dir = self.make_run()
        bad = self.append(run_dir, {"e": "release:updated", "state": "shipped-it"})
        self.assertEqual(bad.returncode, 1)
        ok = self.append(run_dir, {
            "e": "release:updated", "state": "not-deployed",
            "deployed": "skipped: push | no remote in this synthetic repo"})
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.rebuild(run_dir)["release"]["state"], "not-deployed")


if __name__ == "__main__":
    unittest.main()
