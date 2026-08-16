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


if __name__ == "__main__":
    unittest.main()
