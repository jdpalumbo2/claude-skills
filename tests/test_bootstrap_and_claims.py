#!/usr/bin/env python3
"""Checks for the multi-lane bootstrap ritual (task 4.1) and the shared-claims
ledger (task 4.5): the nested ignore remedy's semantics, the committed-profile
probe lanes gate on, and the claims-collision preflight.
"""

import json
import re
import subprocess
import sys
import textwrap
import unittest

from clodex_harness import CATALOGUE, ClodexCheck, git

ROUTER = CATALOGUE / "skills" / "clodex" / "SKILL.md"


def extract_claims_check():
    """§1 check 8's snippet, dedented, straight out of the router."""
    text = ROUTER.read_text()
    for match in re.finditer(r"<<'PY'\n(.*?)\n\s*PY\n", text, re.S):
        if "no claims ledger" in match.group(1):
            return textwrap.dedent(match.group(1))
    raise AssertionError("cannot find the claims check in clodex/SKILL.md")


def check_ignore(repo, path):
    """git check-ignore's exit code: 0 = ignored, 1 = not ignored."""
    return subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", path],
        capture_output=True,
    ).returncode


class NestedIgnoreRemedy(ClodexCheck):
    """§1 check 3's preferred remedy, exactly as the skill prints it."""

    def setUp(self):
        super().setUp()
        # This repo uses the NESTED remedy, not the harness's root rules.
        (self.repo / ".gitignore").write_text("")
        clodex = self.repo / ".clodex"
        clodex.mkdir(exist_ok=True)
        (clodex / ".gitignore").write_text(
            "*\n!.gitignore\n!profile.json\n!claims.json\n")

    def test_exploit_nested_remedy_covers_all_probes(self):
        self.assertEqual(check_ignore(self.repo, ".clodex/ANY-RUN-ID/events.ndjson"), 0,
                         "run state is not ignored under the nested remedy")
        self.assertEqual(check_ignore(self.repo, ".clodex/profile.json"), 1,
                         "the profile is ignored — it must be committable")
        self.assertEqual(check_ignore(self.repo, ".clodex/.gitignore"), 1,
                         "the nested file ignores itself — the remedy cannot be committed")
        self.assertEqual(check_ignore(self.repo, ".clodex/claims.json"), 1,
                         "the claims ledger is ignored — it must be committable")

    def test_control_without_self_exemption_the_remedy_swallows_itself(self):
        # The `!.gitignore` line is load-bearing: without it the carrier is
        # ignored and a worktree never inherits the remedy.
        (self.repo / ".clodex" / ".gitignore").write_text("*\n!profile.json\n")
        self.assertEqual(check_ignore(self.repo, ".clodex/.gitignore"), 0)


class BootstrapProbe(ClodexCheck):
    """§1 check 7: a worktree lane requires the committed profile."""

    def probe(self, cwd):
        return subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".clodex/profile.json"],
            capture_output=True, cwd=str(cwd),
        ).returncode

    def test_exploit_unbootstrapped_worktree_fails_the_probe(self):
        git(self.repo, "branch", "feature/lane")
        worktree = self.repo.parent / "wt-boot"
        git(self.repo, "worktree", "add", "-q", str(worktree), "feature/lane")
        self.assertNotEqual(self.probe(worktree), 0,
                            "probe passed with no committed profile — the lane would interview")

    def test_control_bootstrapped_worktree_passes(self):
        clodex = self.repo / ".clodex"
        clodex.mkdir(exist_ok=True)
        (clodex / "profile.json").write_text("{}")
        git(self.repo, "add", ".clodex/profile.json")
        git(self.repo, "commit", "-q", "-m", "chore(clodex): repo profile",
            "--", ".clodex/profile.json")
        git(self.repo, "branch", "feature/lane")
        worktree = self.repo.parent / "wt-boot2"
        git(self.repo, "worktree", "add", "-q", str(worktree), "feature/lane")
        self.assertEqual(self.probe(worktree), 0)


class ClaimsCheck(ClodexCheck):
    """§1 check 8, run exactly as the router prints it."""

    def run_check(self, needed, ledger=None):
        path = self.repo / ".clodex" / "claims.json"
        if ledger is not None:
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(ledger))
        return subprocess.run(
            [sys.executable, "-", str(path)] + list(needed),
            input=extract_claims_check(), capture_output=True, text=True,
        )

    def test_exploit_held_claim_fails_the_lane(self):
        # Three lanes once independently claimed migration 008; the check
        # makes the collision a preflight stop instead of merge-time archaeology.
        result = self.run_check(
            ["migration-008"],
            {"claims": [{"resource": "migration-008", "holder": "lane-C",
                         "note": "room-liveness schema"}]},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CLAIMED", result.stdout)
        self.assertIn("lane-C", result.stdout)

    def test_control_free_resource_passes(self):
        result = self.run_check(
            ["migration-009"],
            {"claims": [{"resource": "migration-008", "holder": "lane-C"}]},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("free", result.stdout)

    def test_control_no_ledger_is_not_a_failure(self):
        result = self.run_check(["migration-008"], ledger=None)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no claims ledger", result.stdout)


if __name__ == "__main__":
    unittest.main()
