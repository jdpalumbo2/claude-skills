#!/usr/bin/env python3
"""Exploit+control checks for the state engine CLI (`clodex_state.py`).

Subjects: the append path (stray-dir refusal, inline payload, finding
validation) and the run-dir identity guard. Run via `tests/run.sh`.
"""

import unittest

from clodex_harness import ClodexCheck


class SmokeOpenAppendRebuild(ClodexCheck):
    """Control for the whole harness: the ordinary open→append→rebuild path."""

    def test_control_open_append_rebuild(self):
        run_dir = self.make_run()
        result = self.append(run_dir, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 0, result.stderr)
        snap = self.rebuild(run_dir)
        self.assertEqual(snap["stage"], "plan")
        self.assertEqual(snap["repo"], str(self.repo))
        self.assertEqual(snap["last_seq"], 2)
        self.assertTrue((run_dir / "run.json").exists())


class AppendNeverCreatesARunDir(ClodexCheck):
    """2.2 — the CRE stray-dir incident: an append with a relative RUN_DIR from
    the wrong cwd silently created a parallel empty run directory (a state
    fork). Creation belongs solely to the router's open step."""

    def test_exploit_append_to_missing_dir_is_refused_and_creates_nothing(self):
        ghost = self.repo / "dashboard" / ".clodex" / "r-2026-08-16-a"
        result = self.append(ghost, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(str(ghost), result.stderr)
        self.assertFalse(ghost.exists(), "append created a stray run dir")
        self.assertFalse((self.repo / "dashboard").exists())

    def test_exploit_append_to_relocated_run_dir_is_refused(self):
        # The other half of the fork: the wrongly-resolved path EXISTS and
        # holds a copied log whose run:opened records a different location.
        import shutil

        run_dir = self.make_run()
        fork = self.repo / "dashboard" / ".clodex" / "r-2026-08-16-a"
        fork.parent.mkdir(parents=True)
        shutil.copytree(run_dir, fork)
        result = self.append(fork, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(".clodex", result.stderr)
        # And the true run dir still accepts the event.
        result = self.append(run_dir, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_control_run_closed_on_empty_log_in_existing_dir(self):
        # Router §2's stray-dir remedy: close an empty run whose dir exists.
        run_dir = self.make_run(open_event=False)
        result = self.append(run_dir, {"e": "run:closed"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rebuild(run_dir)["stage"], "closed")

    def test_control_append_at_the_recorded_location_still_works(self):
        run_dir = self.make_run()
        result = self.append(run_dir, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 0, result.stderr)


class InlineEventPayload(ClodexCheck):
    """2.3 — `append -e '<json>'`: single events stop needing the
    heredoc-to-temp-file ceremony. stdin remains the default."""

    def test_exploit_inline_payload_is_accepted(self):
        import json as _json
        from clodex_harness import run_state

        run_dir = self.make_run()
        result = run_state(
            ["append", str(run_dir), "-e",
             _json.dumps({"e": "stage:plan:entered"})],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rebuild(run_dir)["stage"], "plan")

    def test_exploit_inline_payload_error_names_its_source(self):
        from clodex_harness import run_state

        run_dir = self.make_run()
        result = run_state(["append", str(run_dir), "-e", "not json"])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("-e payload", result.stderr)

    def test_control_stdin_remains_the_default(self):
        run_dir = self.make_run()
        result = self.append(run_dir, {"e": "stage:plan:entered"})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
