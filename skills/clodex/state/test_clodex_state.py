#!/usr/bin/env python3
"""Contract tests for the clodex state engine.

Stdlib only. Run with either:

    python3 -m unittest discover -s skills/clodex/state -v
    python3 skills/clodex/state/test_clodex_state.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import clodex_state  # noqa: E402
from clodex_state import (  # noqa: E402
    ClodexStateError,
    ReducerInvariantError,
    RunLocked,
    acquire_lock,
    append_event,
    atomic_write_snapshot,
    load_snapshot,
    rebuild,
)

MODULE = str(HERE / "clodex_state.py")
TORN_LINE = '{"schema_version":1,"seq":2,"e":"stage'


class StateTestCase(unittest.TestCase):
    """Gives every test a real, empty run directory on disk."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / "r-2026-08-10-a"
        self.run_dir.mkdir()
        self.events = self.run_dir / "events.ndjson"
        self.snapshot = self.run_dir / "run.json"
        self.lock = self.run_dir / "lock.json"

    def event_lines(self):
        return [json.loads(line) for line in self.events.read_text().splitlines() if line.strip()]

    def append_torn_line(self):
        with open(self.events, "a") as handle:
            handle.write(TORN_LINE)


class EventLogTests(StateTestCase):
    def test_seq_monotonic_and_fsynced(self):
        s1 = append_event(self.run_dir, {"e": "run:opened"})
        s2 = append_event(self.run_dir, {"e": "stage:plan:entered"})
        self.assertEqual((s1, s2), (1, 2))

        records = self.event_lines()
        self.assertEqual([r["seq"] for r in records], [1, 2])
        self.assertEqual([r["e"] for r in records], ["run:opened", "stage:plan:entered"])
        for record in records:
            self.assertEqual(record["schema_version"], clodex_state.SCHEMA_VERSION)
            self.assertTrue(record["t"].endswith("Z"), record["t"])

    def test_append_fsyncs_before_returning(self):
        real_fsync = os.fsync
        synced = []

        def spy(fd):
            synced.append(fd)
            return real_fsync(fd)

        with mock.patch("clodex_state.os.fsync", spy):
            append_event(self.run_dir, {"e": "run:opened"})

        # The durable write happened before append_event returned, not lazily at GC.
        self.assertEqual(len(synced), 1)
        self.assertEqual(self.event_lines()[0]["seq"], 1)

    def test_torn_final_line_truncated(self):
        append_event(self.run_dir, {"e": "run:opened"})
        self.append_torn_line()

        with self.assertLogs("clodex.state", level="WARNING") as logged:
            snap = rebuild(self.run_dir)

        self.assertEqual(snap["last_seq"], 1)  # torn line dropped, logged
        self.assertIn("torn", "\n".join(logged.output).lower())
        # rebuild is a read: it must not rewrite the caller's event log.
        self.assertTrue(self.events.read_text().endswith(TORN_LINE))

    def test_append_after_torn_line_repairs_the_tail(self):
        append_event(self.run_dir, {"e": "run:opened"})
        self.append_torn_line()

        with self.assertLogs("clodex.state", level="WARNING"):
            seq = append_event(self.run_dir, {"e": "stage:plan:entered"})

        self.assertEqual(seq, 2)
        self.assertEqual([r["seq"] for r in self.event_lines()], [1, 2])
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 2)

    def test_event_without_a_type_is_rejected_before_any_write(self):
        with self.assertRaises(ClodexStateError):
            append_event(self.run_dir, {"note": "no e field"})
        self.assertFalse(self.events.exists())

    def test_unknown_event_type_is_rejected(self):
        with self.assertRaises(ClodexStateError):
            append_event(self.run_dir, {"e": "run:teleported"})
        self.assertFalse(self.events.exists())

    def test_event_vocabulary_matches_the_schema(self):
        schema = json.loads((HERE / "schemas" / "event.schema.json").read_text())
        self.assertEqual(sorted(clodex_state._HANDLERS), sorted(schema["properties"]["e"]["enum"]))


class ReducerTests(StateTestCase):
    def append_all(self, *events):
        for event in events:
            append_event(self.run_dir, event)

    def test_reducer_deterministic(self):
        for e in ["run:opened", "stage:plan:entered", "plan:approved"]:
            append_event(self.run_dir, {"e": e})
        self.assertEqual(rebuild(self.run_dir), rebuild(self.run_dir))

    def test_run_opened_populates_the_snapshot(self):
        append_event(self.run_dir, {
            "e": "run:opened",
            "run": "r-2026-08-10-a",
            "repo": "/repo",
            "branch": "main",
            "brief": "make it work",
            "lane": "feature",
            "git": {"start_head": "abc123", "dirty_at_start": ["notes.md"]},
        })
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["stage"], "open")
        self.assertEqual(snap["run"], "r-2026-08-10-a")
        self.assertEqual(snap["lane"], "feature")
        self.assertEqual(snap["git"], {"start_head": "abc123", "dirty_at_start": ["notes.md"]})
        self.assertEqual(snap["last_seq"], 1)

    def test_stage_monotonicity_violation_raises(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "stage:build:entered"},
            {"e": "stage:plan:entered"},
        )
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)

    def test_re_entering_the_same_stage_is_allowed(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "stage:build:entered"},
            {"e": "stage:build:entered"},
        )
        self.assertEqual(rebuild(self.run_dir)["stage"], "build")

    def test_only_one_open_release_step_at_a_time(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "release:step:pending", "step": "push", "op_id": "op-1"},
            {"e": "release:step:pending", "step": "tag", "op_id": "op-2"},
        )
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)

    def test_release_step_closes_then_a_new_one_opens(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "release:step:pending", "step": "push", "op_id": "op-1"},
            {"e": "release:step:reconciled", "op_id": "op-1"},
            {"e": "release:step:done", "op_id": "op-1"},
            {"e": "release:step:pending", "step": "deploy", "op_id": "op-2"},
            {"e": "release:updated", "state": "in-progress", "tag": "v0.1.0"},
        )
        release = rebuild(self.run_dir)["release"]
        self.assertEqual(release["state"], "in-progress")
        self.assertEqual(release["tag"], "v0.1.0")
        self.assertEqual(
            release["steps"],
            [
                {"step": "push", "op_id": "op-1", "status": "done", "reconciled": True},
                {"step": "deploy", "op_id": "op-2", "status": "pending", "reconciled": False},
            ],
        )

    def test_closing_an_unknown_release_step_raises(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "release:step:done", "op_id": "never-opened"},
        )
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)

    def test_approval_must_reference_an_existing_plan_hash(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved", "plan_hash": "not-a-real-hash"},
        )
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)

    def test_approval_binds_to_the_current_plan_hash(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved", "by": "user"},
        )
        approvals = rebuild(self.run_dir)["approvals"]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["plan_hash"], "h1")
        self.assertEqual(approvals[0]["plan_version"], 1)
        self.assertEqual(approvals[0]["scope"], "plan")

    def test_amendment_revokes_approvals_bound_to_the_superseded_hash(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved"},
            {"e": "plan:amended", "version": 2, "hash": "h2", "note": "scope change"},
        )
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["approvals"], [])
        self.assertEqual(snap["plan"]["version"], 2)
        self.assertEqual(snap["plan"]["hash"], "h2")
        self.assertEqual(len(snap["plan"]["amendments"]), 1)
        self.assertEqual(snap["plan"]["amendments"][0]["from_hash"], "h1")

    def test_batches_and_findings_track_by_id(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "batch:opened", "id": 1, "owned_paths": ["src/x/"]},
            {"e": "batch:committed", "id": 1, "commit": "deadbee"},
            {"e": "batch:reviewed", "id": 1, "delta_review": "pass"},
            {"e": "finding:recorded", "id": "F1", "source": "plan-review"},
            {"e": "finding:disposed", "id": "F1", "disposition": "fixed"},
            {"e": "verification:declared", "item": {"class": "unit-tests"}},
            {"e": "verification:evidence", "item": {"class": "unit-tests", "result": "pass"}},
            {"e": "verification:debt", "item": {"class": "live-check", "why": "no staging"}},
        )
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["batches"], [
            {"id": 1, "owned_paths": ["src/x/"], "commit": "deadbee", "delta_review": "pass"},
        ])
        self.assertEqual(snap["findings"], [
            {"id": "F1", "source": "plan-review", "disposition": "fixed"},
        ])
        self.assertEqual(len(snap["verification"]["declared"]), 1)
        self.assertEqual(len(snap["verification"]["evidence"]), 1)
        self.assertEqual(len(snap["verification"]["debt"]), 1)

    def test_committing_an_unknown_batch_raises(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "batch:committed", "id": 7, "commit": "deadbee"},
        )
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)

    def test_rebuild_of_an_empty_run_dir_is_the_base_snapshot(self):
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["last_seq"], 0)
        self.assertIsNone(snap["stage"])
        self.assertEqual(snap["release"]["state"], "not-started")


class LockTests(StateTestCase):
    def test_second_writer_blocked(self):
        with acquire_lock(self.run_dir):
            with self.assertRaises(RunLocked) as caught:
                acquire_lock(self.run_dir)

        self.assertEqual(caught.exception.pid, os.getpid())
        # holder timestamp is a parseable ISO-8601 instant
        datetime.fromisoformat(caught.exception.acquired_at.replace("Z", "+00:00"))

    def test_lock_is_released_on_exit(self):
        with acquire_lock(self.run_dir):
            self.assertTrue(self.lock.exists())
        self.assertFalse(self.lock.exists())
        with acquire_lock(self.run_dir):  # a later run may take it
            pass

    def test_second_writer_blocked_across_processes(self):
        with subprocess.Popen(
            [sys.executable, "-c", HOLD_LOCK_SCRIPT, str(self.run_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as holder:
            try:
                if holder.stdout.readline().strip() != "locked":
                    holder.kill()  # kill first: reading stderr of a live child deadlocks
                    self.fail("lock holder never started: %s" % holder.stderr.read())

                with self.assertRaises(RunLocked) as caught:
                    acquire_lock(self.run_dir)
                self.assertEqual(caught.exception.pid, holder.pid)

                holder.stdin.write("release\n")
                holder.stdin.flush()
                self.assertEqual(holder.wait(timeout=10), 0)
            finally:
                if holder.poll() is None:
                    holder.kill()

        self.assertFalse(self.lock.exists())
        with acquire_lock(self.run_dir):
            pass

    def test_snapshot_write_refused_while_another_pid_holds_the_lock(self):
        self.lock.write_text(json.dumps({"pid": 999999, "acquired_at": "2026-08-10T00:00:00Z"}))
        with self.assertRaises(RunLocked) as caught:
            atomic_write_snapshot(self.run_dir, rebuild(self.run_dir))
        self.assertEqual(caught.exception.pid, 999999)
        self.assertFalse(self.snapshot.exists())


HOLD_LOCK_SCRIPT = (
    "import sys; sys.path.insert(0, %r)\n"
    "import clodex_state\n"
    "with clodex_state.acquire_lock(sys.argv[1]):\n"
    "    print('locked', flush=True)\n"
    "    sys.stdin.readline()\n"
) % str(HERE)


class SnapshotTests(StateTestCase):
    def test_invalid_snapshot_falls_back_to_rebuild(self):
        append_event(self.run_dir, {"e": "run:opened"})
        self.snapshot.write_text("{corrupt")
        with self.assertLogs("clodex.state", level="WARNING"):
            snap = load_snapshot(self.run_dir)
        self.assertEqual(snap["stage"], "open")

    def test_snapshot_missing_required_field_falls_back_to_rebuild(self):
        append_event(self.run_dir, {"e": "run:opened"})
        self.snapshot.write_text(json.dumps({"schema_version": 1, "stage": "ship"}))
        with self.assertLogs("clodex.state", level="WARNING"):
            snap = load_snapshot(self.run_dir)
        self.assertEqual(snap["stage"], "open")

    def test_atomic_write_snapshot_round_trip(self):
        append_event(self.run_dir, {"e": "run:opened"})
        append_event(self.run_dir, {"e": "stage:plan:entered"})
        snap = rebuild(self.run_dir)
        atomic_write_snapshot(self.run_dir, snap)

        self.assertEqual(load_snapshot(self.run_dir), snap)
        self.assertEqual(json.loads(self.snapshot.read_text()), snap)
        # temp file replaced, not left behind
        self.assertEqual(sorted(p.name for p in self.run_dir.iterdir()),
                         ["events.ndjson", "run.json"])

    def test_stale_snapshot_falls_back_to_rebuild(self):
        append_event(self.run_dir, {"e": "run:opened"})
        atomic_write_snapshot(self.run_dir, rebuild(self.run_dir))
        append_event(self.run_dir, {"e": "stage:plan:entered"})

        with self.assertLogs("clodex.state", level="WARNING"):
            snap = load_snapshot(self.run_dir)
        self.assertEqual(snap["stage"], "plan")
        self.assertEqual(snap["last_seq"], 2)

    def test_snapshot_that_fails_schema_is_never_written(self):
        snap = rebuild(self.run_dir)
        del snap["release"]
        with self.assertRaises(ClodexStateError):
            atomic_write_snapshot(self.run_dir, snap)
        self.assertFalse(self.snapshot.exists())
        self.assertEqual(list(self.run_dir.iterdir()), [])


class CliTests(StateTestCase):
    def cli(self, *args, **kwargs):
        return subprocess.run(
            [sys.executable, MODULE] + list(args),
            input=kwargs.get("stdin", ""),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_cli_round_trip(self):
        first = self.cli("append", str(self.run_dir), stdin='{"e": "run:opened", "lane": "feature"}')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "1")

        second = self.cli("append", str(self.run_dir), stdin='{"e": "stage:plan:entered"}')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "2")

        rebuilt = self.cli("rebuild", str(self.run_dir))
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
        snap = json.loads(rebuilt.stdout)
        self.assertEqual(snap["stage"], "plan")
        self.assertEqual(snap["last_seq"], 2)
        # append refreshed the snapshot after fsyncing the event
        self.assertEqual(json.loads(self.snapshot.read_text()), snap)

        status = self.cli("status", str(self.run_dir))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("plan", status.stdout)
        self.assertIn("feature", status.stdout)

    def test_cli_status_reports_a_live_lock(self):
        append_event(self.run_dir, {"e": "run:opened"})
        clean = self.cli("status", str(self.run_dir))
        self.assertNotIn("lock:", clean.stdout)

        with acquire_lock(self.run_dir):
            locked = self.cli("status", str(self.run_dir))
        self.assertEqual(locked.returncode, 0, locked.stderr)
        self.assertIn("lock:", locked.stdout)
        self.assertIn(str(os.getpid()), locked.stdout)

    def test_cli_reports_bad_stdin_on_stderr(self):
        result = self.cli("append", str(self.run_dir), stdin="not json")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())
        self.assertFalse(self.events.exists())

    def test_cli_refuses_an_event_that_would_break_the_reducer(self):
        self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
        self.cli("append", str(self.run_dir), stdin='{"e": "stage:build:entered"}')
        result = self.cli("append", str(self.run_dir), stdin='{"e": "stage:plan:entered"}')

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())
        # the illegal event never entered the log, so the run stays readable
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 2)
        self.assertEqual(rebuild(self.run_dir)["stage"], "build")


if __name__ == "__main__":
    unittest.main()
