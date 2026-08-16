#!/usr/bin/env python3
"""Exploit+control checks for clodex-ship §5's authorization validator
(task 2.10, F-12).

The validator is extracted from the SKILL.md itself — the document's own
script is the subject, so a drifted doc fails here, not in a run. The field
failure: with a changelog/version configured, the bookkeeping check demanded a
descriptor even when the step was legitimately in the authorization's `cut`
list, printing a known-spurious `DO NOT APPEND` the operator had to talk past.
"""

import json
import re
import subprocess
import sys
import unittest

from clodex_harness import CATALOGUE, ClodexCheck

SHIP = CATALOGUE / "skills" / "clodex-ship" / "SKILL.md"
PROFILE_SCHEMA = CATALOGUE / "skills" / "clodex" / "profile.schema.json"
STATE = CATALOGUE / "skills" / "clodex" / "state" / "clodex_state.py"


def extract_validator():
    """The §5 validator's python body, straight out of the document."""
    text = SHIP.read_text()
    match = re.search(
        r'"\$RUN_DIR/authorization\.json" <<\'PY\'\n(.*?)\nPY\n', text, re.S
    )
    assert match, "cannot find the §5 validator heredoc in clodex-ship/SKILL.md"
    return match.group(1)


class ShipValidatorCutAware(ClodexCheck):
    def setUp(self):
        super().setUp()
        (self.repo / "VERSION").write_text("1.0.0\n")
        from clodex_harness import git
        git(self.repo, "add", "VERSION")
        git(self.repo, "commit", "-q", "-m", "version file")
        self.run_dir = self.make_run()
        (self.repo / ".clodex" / "profile.json").write_text(json.dumps({
            "schema_version": 1,
            "commands": {"install": None, "build": None, "test": None,
                         "lint": None, "typecheck": None},
            "version": {"source": "VERSION", "field": None, "bump_rule": "semver"},
            "branch": {"default": "main", "work_on_default": True, "naming": None},
            "tag": {"enabled": False, "format": None},
            "changelog": None,
            "docs": {"architecture": [], "plans_dir": "docs/plans"},
            "deploy": None,
            "evidence": {"default_classes": ["tests"]},
            "runtimes": [],
            "required_env": [],
            "actions": [],
        }))

    def run_validator(self, payload):
        (self.repo / ".clodex" / "r-2026-08-16-a" / "authorization.json").write_text(
            json.dumps(payload)
        )
        return subprocess.run(
            [sys.executable, "-", str(STATE), str(self.run_dir),
             str(self.repo / ".clodex" / "profile.json"), str(PROFILE_SCHEMA),
             str(self.repo / ".clodex" / "r-2026-08-16-a" / "authorization.json")],
            input=extract_validator(), capture_output=True, text=True,
            cwd=self.repo,
        )

    def test_exploit_cut_bookkeeping_is_not_a_spurious_problem(self):
        # The orchestrated-lane shape: VERSION/changelog owned by an external
        # release flow, so bookkeeping and commit are cut in writing.
        result = self.run_validator({
            "e": "approval:granted", "scope": "release-authorization",
            "by": "user",
            "actions": [],
            "accepted_debt": [],
            "cut": [
                {"step": "bookkeeping",
                 "why": "VERSION and changelog are owned by the external release flow"},
                {"step": "commit",
                 "why": "nothing to commit once bookkeeping is cut"},
            ],
        })
        self.assertIn("AUTHORIZATION VALID", result.stdout,
                      result.stdout + result.stderr)
        self.assertNotIn("expected exactly one bookkeeping descriptor",
                         result.stdout)

    def test_control_undescribed_uncut_step_still_blocks(self):
        # The guard the exemption must not swallow: a step neither described
        # nor cut is still a problem.
        result = self.run_validator({
            "e": "approval:granted", "scope": "release-authorization",
            "by": "user",
            "actions": [], "accepted_debt": [], "cut": [],
        })
        self.assertIn("DO NOT APPEND", result.stdout,
                      result.stdout + result.stderr)
        self.assertIn("no `cut` entry", result.stdout)

    def test_control_cut_without_a_reason_still_blocks(self):
        result = self.run_validator({
            "e": "approval:granted", "scope": "release-authorization",
            "by": "user",
            "actions": [], "accepted_debt": [],
            "cut": [{"step": "bookkeeping", "why": ""},
                    {"step": "commit", "why": "external flow"}],
        })
        self.assertIn("DO NOT APPEND", result.stdout,
                      result.stdout + result.stderr)
        self.assertIn("no `why`", result.stdout)


if __name__ == "__main__":
    unittest.main()
