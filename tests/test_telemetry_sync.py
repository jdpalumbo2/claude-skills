#!/usr/bin/env python3
"""Exploit+control checks for the `telemetry-sync` verb (task 2.5).

The field failure: seven completed implementer invocations (~1 h of Codex
work) never got a `codex` block appended — the attach-to-the-next-event
discipline fails under load — and where blocks did exist, `duration_s` was
estimated (700/900/1500 against envelope actuals of 326/201/436) and `status`
asserted. The verb makes the disk the source of truth: orphans are printed as
ready-to-attach blocks with every field copied from the envelope.
"""

import json
import unittest

from clodex_harness import ClodexCheck, run_state


def synthetic_envelope(runner_dir, invocation_id, role="implementer",
                       status="partial", duration_ms=326000):
    role_dir = runner_dir / role
    role_dir.mkdir(parents=True, exist_ok=True)
    path = role_dir / ("%s.envelope.json" % invocation_id)
    path.write_text(json.dumps({
        "schema_version": 1,
        "invocation_id": invocation_id,
        "role": role,
        "status": status,
        "inputs": [{"path": "batch-1.contract.md", "sha256": "cafe" * 16}],
        "findings": [],
        "exit": {"code": 0, "signal": None, "started_at": "t0", "ended_at": "t1",
                 "duration_ms": duration_ms},
        "codex": {"model": "m", "effort": "high", "sandbox": "workspace-write",
                  "session_id": "s", "resumed": False},
        "output": {"events": "e", "stderr": "s", "model_report": "r",
                   "state_dir": str(role_dir)},
    }))
    return path


class TelemetrySync(ClodexCheck):
    def sync(self, run_dir, runner_dir):
        return run_state(["telemetry-sync", str(run_dir), str(runner_dir)])

    def test_exploit_orphaned_envelope_is_printed_with_copied_fields(self):
        run_dir = self.make_run()
        runner_dir = self.repo / ".clodex" / "runner"
        # One invocation the log knows about…
        recorded = "implementer-20260815T120000Z-aaaaaa"
        synthetic_envelope(runner_dir, recorded)
        self.append(run_dir, {
            "e": "stage:plan:entered",
            "codex": {"invocation_id": recorded, "role": "implementer",
                      "status": "partial", "duration_s": 326.0},
        })
        # …and one that finished but never got a block (the 7-orphan gap).
        orphan = "implementer-20260815T130000Z-bbbbbb"
        synthetic_envelope(runner_dir, orphan, status="partial",
                           duration_ms=201000)

        result = self.sync(run_dir, runner_dir)
        self.assertEqual(result.returncode, 1, result.stderr)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, result.stdout)
        block = json.loads(lines[0])["codex"]
        self.assertEqual(block["invocation_id"], orphan)
        # Copied, never estimated / asserted:
        self.assertEqual(block["duration_s"], 201.0)
        self.assertEqual(block["status"], "partial")
        self.assertEqual(block["input_hashes"], ["cafe" * 16])

    def test_control_attaching_the_block_reaches_zero_diff(self):
        run_dir = self.make_run()
        runner_dir = self.repo / ".clodex" / "runner"
        orphan = "code-reviewer-20260815T140000Z-cccccc"
        synthetic_envelope(runner_dir, orphan, role="code-reviewer",
                           status="complete", duration_ms=436000)

        first = self.sync(run_dir, runner_dir)
        self.assertEqual(first.returncode, 1)
        block = json.loads(first.stdout.splitlines()[0])
        event = dict(block, e="stage:plan:entered")
        result = self.append(run_dir, event)
        self.assertEqual(result.returncode, 0, result.stderr)

        second = self.sync(run_dir, runner_dir)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(second.stdout.strip(), "")

    def test_control_lost_envelope_warns_but_does_not_fail(self):
        run_dir = self.make_run()
        runner_dir = self.repo / ".clodex" / "runner"
        runner_dir.mkdir(parents=True)
        self.append(run_dir, {
            "e": "stage:plan:entered",
            "codex": {"invocation_id": "advisor-gone-dddddd", "role": "advisor"},
        })
        result = self.sync(run_dir, runner_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("advisor-gone-dddddd", result.stderr)
        self.assertIn("no envelope", result.stderr)


if __name__ == "__main__":
    unittest.main()
