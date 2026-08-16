#!/usr/bin/env python3
"""Exploit+control checks for the archive-on-close recipe (task 3.4, F-9).

The field failure: 61 MB of run state — evidence, envelopes, the deploy-window
action file the release record pointed at — lived only in disposable
worktrees, one `git worktree prune` from destruction. The recipe (extracted
from the router SKILL.md, so a drifted doc fails here) copies the core to the
main checkout on close.
"""

import json
import re
import subprocess
import sys
import unittest

from clodex_harness import CATALOGUE, ClodexCheck, git

ROUTER = CATALOGUE / "skills" / "clodex" / "SKILL.md"
STATE = CATALOGUE / "skills" / "clodex" / "state" / "clodex_state.py"


def extract_archive_recipe():
    # The terminator match tolerates indentation so a heredoc inside an
    # indented markdown list elsewhere in the file ends at ITS own PY line
    # instead of swallowing every block up to the next unindented one.
    import textwrap

    text = ROUTER.read_text()
    for match in re.finditer(r"<<'PY'\n(.*?)\n[ \t]*PY\n", text, re.S):
        body = textwrap.dedent(match.group(1))
        if "archived %d item(s)" in body:
            return body
    raise AssertionError("cannot find the archive recipe in clodex/SKILL.md")


class ArchiveOnClose(ClodexCheck):
    def run_recipe(self, run_dir):
        return subprocess.run(
            [sys.executable, "-", str(STATE), str(run_dir)],
            input=extract_archive_recipe(), capture_output=True, text=True,
        )

    def test_exploit_worktree_run_core_survives_in_the_main_checkout(self):
        git(self.repo, "branch", "feature/lane")
        worktree = self.repo.parent / "wt-lane"
        git(self.repo, "worktree", "add", "-q", str(worktree), "feature/lane")

        run_id = "r-2026-08-16-a"
        run_dir = worktree / ".clodex" / run_id
        run_dir.mkdir(parents=True)
        result = self.append(run_dir, {
            "e": "run:opened", "run": run_id, "repo": str(worktree),
            "branch": "feature/lane", "lane": "feature", "brief": "lane run",
            "git": {"start_head": self.head(), "dirty_at_start": []},
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        # An envelope on disk, recorded in the manifest, plus a raw transcript
        # that must NOT be archived.
        role_dir = worktree / ".clodex" / "runner" / run_id / "implementer"
        role_dir.mkdir(parents=True)
        envelope = role_dir / "implementer-x.envelope.json"
        envelope.write_text(json.dumps({"invocation_id": "implementer-x"}))
        (role_dir / "implementer-x.events.ndjson").write_text("{}\n" * 1000)
        self.append(run_dir, {
            "e": "stage:plan:entered",
            "codex": {"invocation_id": "implementer-x", "role": "implementer",
                      "envelope": str(envelope)},
        })
        (run_dir / "handoff.md").write_text("# Handoff\n")
        (run_dir / "evidence").mkdir()
        (run_dir / "evidence" / "shot.png").write_bytes(b"png")
        self.append(run_dir, {"e": "run:closed"})

        result = self.run_recipe(run_dir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dest = self.repo / ".clodex" / "archive" / run_id
        for expected in ("events.ndjson", "run.json", "handoff.md",
                         "evidence/shot.png",
                         "runner/implementer/implementer-x.envelope.json"):
            self.assertTrue((dest / expected).exists(), expected)
        self.assertFalse(
            list(dest.rglob("*.events.ndjson.raw")) or
            (dest / "runner" / "implementer" / "implementer-x.events.ndjson").exists(),
            "raw runner transcript was archived",
        )
        # And the archive stays out of git.
        check = subprocess.run(
            ["git", "-C", str(self.repo), "check-ignore",
             str(dest / "run.json")], capture_output=True)
        self.assertEqual(check.returncode, 0, "archive path is not ignored")

    def test_control_main_checkout_run_archives_nothing(self):
        run_dir = self.make_run()
        self.append(run_dir, {"e": "run:closed"})
        result = self.run_recipe(run_dir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", result.stdout)
        self.assertFalse((self.repo / ".clodex" / "archive").exists())


if __name__ == "__main__":
    unittest.main()
