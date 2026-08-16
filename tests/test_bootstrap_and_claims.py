#!/usr/bin/env python3
"""Checks for the multi-lane bootstrap ritual (task 4.1) and the shared-claims
ledger (task 4.5): the nested ignore remedy's semantics, the committed-profile
probe lanes gate on, and the claims-collision preflight.
"""

import subprocess
import unittest

from clodex_harness import ClodexCheck, git


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
        (clodex / ".gitignore").write_text("*\n!.gitignore\n!profile.json\n")

    def test_exploit_nested_remedy_covers_all_three_probes(self):
        self.assertEqual(check_ignore(self.repo, ".clodex/ANY-RUN-ID/events.ndjson"), 0,
                         "run state is not ignored under the nested remedy")
        self.assertEqual(check_ignore(self.repo, ".clodex/profile.json"), 1,
                         "the profile is ignored — it must be committable")
        self.assertEqual(check_ignore(self.repo, ".clodex/.gitignore"), 1,
                         "the nested file ignores itself — the remedy cannot be committed")

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


if __name__ == "__main__":
    unittest.main()
