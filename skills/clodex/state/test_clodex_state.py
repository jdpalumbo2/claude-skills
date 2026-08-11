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
    break_lock,
    load_snapshot,
    rebuild,
)

# The one reducer instance clodex_state itself loaded, so the exception classes
# a test asserts on are the classes the code raises.
reducer = clodex_state.reducer

MODULE = str(HERE / "clodex_state.py")
TORN_LINE = '{"schema_version":1,"seq":2,"e":"stage'

HOLD_LOCK_SCRIPT = (
    "import sys; sys.path.insert(0, %r)\n"
    "import clodex_state\n"
    "with clodex_state.acquire_lock(sys.argv[1]):\n"
    "    print('locked', flush=True)\n"
    "    sys.stdin.readline()\n"
) % str(HERE)

# Independent processes racing for the same log with no session lock held.
CONCURRENT_APPEND_SCRIPT = (
    "import sys, time\n"
    "sys.path.insert(0, %r)\n"
    "import clodex_state\n"
    "run_dir, label, count = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
    "for index in range(count):\n"
    "    for attempt in range(400):\n"
    "        try:\n"
    "            clodex_state.append_event(run_dir, {'e': 'finding:recorded',\n"
    "                                               'id': '%%s-%%d' %% (label, index),\n"
    "                                               'source': 'race'})\n"
    "            break\n"
    "        except clodex_state.RunLocked:\n"
    "            time.sleep(0.005)\n"
    "    else:\n"
    "        raise SystemExit('gave up waiting for the lock: ' + label)\n"
) % str(HERE)

# Delegates of one session lock: they carry the token, so they never contend for
# the session lock at all. Only the write lock keeps them from colliding.
DELEGATE_APPEND_SCRIPT = (
    "import os, sys, time\n"
    "sys.path.insert(0, %r)\n"
    "import clodex_state\n"
    "run_dir, go, label, count = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])\n"
    "assert os.environ.get(clodex_state.LOCK_TOKEN_ENV), 'no delegated token inherited'\n"
    "print('ready', flush=True)\n"
    "while not os.path.exists(go):\n"
    "    time.sleep(0.002)\n"
    "for index in range(count):\n"
    "    clodex_state.append_event(run_dir, {'e': 'finding:recorded',\n"
    "                                        'id': '%%s-%%d' %% (label, index),\n"
    "                                        'source': 'delegate'})\n"
) % str(HERE)

IMPORT_BY_PATH_SCRIPT = (
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('cs', %r)\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "print(module.SCHEMA_VERSION)\n"
) % MODULE


class StateTestCase(unittest.TestCase):
    """Gives every test a real, empty run directory on disk."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_root = Path(tmp.name)
        self.run_dir = self.tmp_root / "r-2026-08-10-a"
        self.run_dir.mkdir()
        self.events = self.run_dir / "events.ndjson"
        self.snapshot = self.run_dir / "run.json"
        self.lock = self.run_dir / "lock.json"

    def event_lines(self):
        return [json.loads(line) for line in self.events.read_text().splitlines() if line.strip()]

    def append_torn_line(self):
        with open(self.events, "a") as handle:
            handle.write(TORN_LINE)

    def dead_pid(self):
        """A PID that is genuinely gone, not merely improbable."""
        finished = subprocess.Popen([sys.executable, "-c", "pass"])
        finished.wait(timeout=30)
        return finished.pid

    def write_foreign_lock(self, pid):
        self.lock.write_text(json.dumps({
            "pid": pid, "acquired_at": "2026-08-10T00:00:00Z", "token": "someone-elses-token",
        }))


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
        self.assertTrue(synced)
        self.assertEqual(self.event_lines()[0]["seq"], 1)

    def test_creating_the_log_fsyncs_its_directory(self):
        real_fsync_dir = clodex_state._fsync_dir
        synced = []

        def spy(path):
            synced.append(path)
            return real_fsync_dir(path)

        with mock.patch("clodex_state._fsync_dir", spy):
            append_event(self.run_dir, {"e": "run:opened"})
            self.assertEqual(synced, [str(self.run_dir)])  # new dirent made durable
            append_event(self.run_dir, {"e": "stage:plan:entered"})
            self.assertEqual(len(synced), 1)  # nothing new to make durable

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

    def test_append_after_a_newline_terminated_invalid_line_repairs_the_tail(self):
        # Read and write must reach the same verdict on the final line, or
        # appending pushes a line reads tolerate into the middle of the file.
        append_event(self.run_dir, {"e": "run:opened"})
        with open(self.events, "a") as handle:
            handle.write(TORN_LINE + "\n")

        with self.assertLogs("clodex.state", level="WARNING"):
            seq = append_event(self.run_dir, {"e": "stage:plan:entered"})

        self.assertEqual(seq, 2)
        self.assertEqual([r["seq"] for r in self.event_lines()], [1, 2])
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 2)

    def test_append_completes_a_final_line_that_only_lost_its_newline(self):
        append_event(self.run_dir, {"e": "run:opened"})
        raw = self.events.read_text()
        self.events.write_text(raw.rstrip("\n"))  # valid event, newline gone

        with self.assertLogs("clodex.state", level="WARNING"):
            seq = append_event(self.run_dir, {"e": "stage:plan:entered"})

        self.assertEqual(seq, 2)  # the complete record was kept, not discarded
        self.assertEqual([r["e"] for r in self.event_lines()],
                         ["run:opened", "stage:plan:entered"])

    def test_event_without_a_type_is_rejected_before_any_write(self):
        with self.assertRaises(ClodexStateError):
            append_event(self.run_dir, {"note": "no e field"})
        self.assertEqual(list(self.run_dir.iterdir()), [])  # not even a lockfile

    def test_unknown_event_type_is_rejected(self):
        with self.assertRaises(ClodexStateError):
            append_event(self.run_dir, {"e": "run:teleported"})
        self.assertFalse(self.events.exists())

    def test_event_vocabulary_matches_the_schema(self):
        schema = json.loads((HERE / "schemas" / "event.schema.json").read_text())
        self.assertEqual(sorted(reducer.HANDLERS), sorted(schema["properties"]["e"]["enum"]))

    def test_module_can_be_imported_by_path(self):
        # A directory with no reducer.py in it and nothing putting the state
        # directory on sys.path: a bare `import reducer` cannot resolve here.
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

        bare = subprocess.run(
            [sys.executable, "-c", "import reducer"], cwd=workdir.name, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertNotEqual(bare.returncode, 0)  # the environment really is hostile

        loaded = subprocess.run(
            [sys.executable, "-c", IMPORT_BY_PATH_SCRIPT], cwd=workdir.name, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual(loaded.stdout.strip(), str(clodex_state.SCHEMA_VERSION))


class ConcurrencyTests(StateTestCase):
    def assert_log_is_a_clean_run_of(self, total):
        seqs = [record["seq"] for record in self.event_lines()]
        self.assertEqual(seqs, list(range(1, total + 1)))  # unique and contiguous
        snap = rebuild(self.run_dir)  # would raise if any seq had been reused
        self.assertEqual(snap["last_seq"], total)
        self.assertEqual(len(snap["findings"]), total)

    def test_concurrent_appends_never_reuse_a_seq(self):
        writers, per_writer = 4, 5
        env = dict(os.environ)
        env.pop(clodex_state.LOCK_TOKEN_ENV, None)  # no delegated token: separate sessions

        processes = [
            subprocess.Popen(
                [sys.executable, "-c", CONCURRENT_APPEND_SCRIPT,
                 str(self.run_dir), "w%d" % index, str(per_writer)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
            )
            for index in range(writers)
        ]
        try:
            for process in processes:
                out, err = process.communicate(timeout=120)
                self.assertEqual(process.returncode, 0, err or out)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()

        self.assert_log_is_a_clean_run_of(writers * per_writer)
        self.assertFalse(self.lock.exists())

    def test_concurrent_delegates_of_one_session_never_reuse_a_seq(self):
        # The documented pattern: one session lock, several CLI-style children
        # carrying its token, running at the same time. They never contend for
        # the session lock, so only the write lock can serialize them.
        writers, per_writer = 4, 5
        go = self.tmp_root / "go"

        with acquire_lock(self.run_dir):
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", DELEGATE_APPEND_SCRIPT,
                     str(self.run_dir), str(go), "d%d" % index, str(per_writer)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for index in range(writers)
            ]
            try:
                for process in processes:  # everyone at the barrier before anyone starts
                    ready = process.stdout.readline().strip()
                    if ready != "ready":
                        raise AssertionError("delegate failed to start: %s" % process.stderr.read())
                go.write_text("go")
                for process in processes:
                    out, err = process.communicate(timeout=120)
                    self.assertEqual(process.returncode, 0, err or out)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()

            self.assertTrue(self.lock.exists())  # the session lock was ours throughout

        self.assert_log_is_a_clean_run_of(writers * per_writer)


class ReducerTests(StateTestCase):
    def append_all(self, *events):
        for event in events:
            append_event(self.run_dir, event)

    def assert_last_event_refused(self, *events):
        """Every event but the last is legal; the last must never reach the log."""
        for event in events[:-1]:
            append_event(self.run_dir, event)
        before = self.events.read_text() if self.events.exists() else ""

        with self.assertRaises(ReducerInvariantError):
            append_event(self.run_dir, events[-1])

        after = self.events.read_text() if self.events.exists() else ""
        self.assertEqual(after, before)  # append-only log untouched
        rebuild(self.run_dir)  # and the run is still readable

    def test_reducer_deterministic(self):
        # plan:recorded precedes the approval because an approval must bind to a
        # plan hash; the determinism assertion itself is unchanged.
        for event in [{"e": "run:opened"},
                      {"e": "stage:plan:entered"},
                      {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
                      {"e": "plan:approved"}]:
            append_event(self.run_dir, event)
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

    def test_stage_monotonicity_violation_refused(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "stage:build:entered"},
            {"e": "stage:plan:entered"},
        )

    def test_re_entering_the_same_stage_is_allowed(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "stage:build:entered"},
            {"e": "stage:build:entered"},
        )
        self.assertEqual(rebuild(self.run_dir)["stage"], "build")

    def test_only_one_open_release_step_at_a_time(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "release:step:pending", "step": "push", "op_id": "op-1"},
            {"e": "release:step:pending", "step": "tag", "op_id": "op-2"},
        )

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

    def test_closing_an_unknown_release_step_refused(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "release:step:done", "op_id": "never-opened"},
        )

    def test_release_state_outside_the_schema_is_refused(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "release:updated", "state": "banana"},
        )

    def test_approval_must_reference_the_current_plan_hash(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved", "plan_hash": "not-a-real-hash"},
        )

    def test_approval_against_a_superseded_hash_is_refused(self):
        # h1 is a hash the log has seen, so an "does this exist anywhere"
        # check passes it. But the amendment's revocation sweep has already
        # run, so this approval would keep revoked == null forever: a
        # live-looking approval bound to a plan that no longer applies.
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved"},
            {"e": "plan:amended", "version": 2, "hash": "h2", "note": "scope change"},
            {"e": "approval:granted", "scope": "release-authorization", "plan_hash": "h1"},
        )

        # The approval granted *before* the amendment is untouched by this
        # rule: it stays, marked revoked by the sweep.
        approvals = rebuild(self.run_dir)["approvals"]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["revoked"]["superseding_hash"], "h2")

        # An approval against the new hash is still legal.
        append_event(self.run_dir, {"e": "approval:granted", "scope": "release-authorization"})
        live = [a for a in rebuild(self.run_dir)["approvals"] if a["revoked"] is None]
        self.assertEqual([a["plan_hash"] for a in live], ["h2"])

    def test_live_approvals_are_always_bound_to_the_current_plan_hash(self):
        # The guarantee consumers get from the two rules together: approvals may
        # only bind to the current hash, and an amendment sweeps everything bound
        # to the hash it supersedes. So `revoked is None` alone is enough to know
        # an approval still applies — no hash comparison needed downstream.
        self.append_all(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved"},
            {"e": "plan:amended", "version": 2, "hash": "h2"},
            {"e": "approval:granted", "scope": "release-authorization"},
            {"e": "plan:amended", "version": 3, "hash": "h3"},
            {"e": "plan:approved"},
        )
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["plan"]["hash"], "h3")
        self.assertEqual(len(snap["approvals"]), 3)
        for approval in snap["approvals"]:
            if approval["revoked"] is None:
                self.assertEqual(approval["plan_hash"], snap["plan"]["hash"])
        self.assertEqual([a["plan_hash"] for a in snap["approvals"] if a["revoked"] is None],
                         ["h3"])

    def test_approval_bound_to_no_plan_is_refused(self):
        # An approval with no plan hash could never be revoked by an amendment.
        self.assert_last_event_refused({"e": "run:opened"}, {"e": "plan:approved"})

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
        self.assertIsNone(approvals[0]["revoked"])

    def test_amendment_revokes_approvals_bound_to_the_superseded_hash(self):
        self.append_all(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved"},
            {"e": "plan:amended", "version": 2, "hash": "h2", "note": "scope change"},
        )
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["plan"]["version"], 2)
        self.assertEqual(snap["plan"]["hash"], "h2")
        self.assertEqual(len(snap["plan"]["amendments"]), 1)
        self.assertEqual(snap["plan"]["amendments"][0]["from_hash"], "h1")

        # The approval is kept and marked, not dropped: the run must be able to
        # say what happened from the manifest alone.
        self.assertEqual(len(snap["approvals"]), 1)
        revoked = snap["approvals"][0]["revoked"]
        self.assertIsNotNone(revoked)
        self.assertEqual(revoked["superseded_hash"], "h1")
        self.assertEqual(revoked["superseding_hash"], "h2")
        self.assertEqual(revoked["seq"], 4)

        # An approval granted against the new hash stands.
        append_event(self.run_dir, {"e": "approval:granted", "scope": "release-authorization"})
        approvals = rebuild(self.run_dir)["approvals"]
        self.assertEqual([a["revoked"] is None for a in approvals], [False, True])

    def test_amendment_without_a_new_hash_is_refused(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:amended", "version": 2, "note": "forgot the hash"},
        )

    def test_amendment_that_supersedes_nothing_is_refused(self):
        # Same hash: it would revoke every approval and change nothing.
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "plan:recorded", "version": 1, "path": "docs/plans/x.md", "hash": "h1"},
            {"e": "plan:approved"},
            {"e": "plan:amended", "version": 2, "hash": "h1"},
        )

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

    def test_committing_an_unknown_batch_refused(self):
        self.assert_last_event_refused(
            {"e": "run:opened"},
            {"e": "batch:committed", "id": 7, "commit": "deadbee"},
        )

    def test_rebuild_of_an_empty_run_dir_is_the_base_snapshot(self):
        snap = rebuild(self.run_dir)
        self.assertEqual(snap["last_seq"], 0)
        self.assertIsNone(snap["stage"])
        self.assertEqual(snap["release"]["state"], "not-started")

    def test_rebuilt_snapshots_satisfy_the_snapshot_schema(self):
        self.append_all(
            {"e": "run:opened", "run": "r-1", "lane": "feature"},
            {"e": "batch:opened", "id": 1, "owned_paths": ["src/"]},
        )
        # consumers are handed something they can trust the schema for
        reducer.validate(rebuild(self.run_dir), reducer.load_schema("snapshot.schema.json"))

    def test_the_reducer_still_refuses_a_log_written_out_of_band(self):
        # append_event vets events now, but the reducer remains the authority
        # for a log something else wrote.
        append_event(self.run_dir, {"e": "run:opened"})
        with open(self.events, "a") as handle:
            handle.write(json.dumps({
                "schema_version": 1, "seq": 2, "t": "2026-08-10T00:00:00Z", "e": "plan:approved",
            }) + "\n")
        with self.assertRaises(ReducerInvariantError):
            rebuild(self.run_dir)


class LockTests(StateTestCase):
    def test_second_writer_blocked(self):
        with acquire_lock(self.run_dir):
            with self.assertRaises(RunLocked) as caught:
                acquire_lock(self.run_dir)

        self.assertEqual(caught.exception.pid, os.getpid())
        self.assertTrue(caught.exception.holder_alive)
        # holder timestamp is a parseable ISO-8601 instant
        datetime.fromisoformat(caught.exception.acquired_at.replace("Z", "+00:00"))

    def test_lock_is_released_on_exit(self):
        with acquire_lock(self.run_dir):
            self.assertTrue(self.lock.exists())
        self.assertFalse(self.lock.exists())
        self.assertNotIn(clodex_state.LOCK_TOKEN_ENV, os.environ)
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
                self.assertTrue(caught.exception.holder_alive)

                # the authoritative file is protected too, not just the snapshot
                with self.assertRaises(RunLocked):
                    append_event(self.run_dir, {"e": "run:opened"})
                self.assertFalse(self.events.exists())

                holder.stdin.write("release\n")
                holder.stdin.flush()
                self.assertEqual(holder.wait(timeout=30), 0)
            finally:
                if holder.poll() is None:
                    holder.kill()

        self.assertFalse(self.lock.exists())
        self.assertEqual(append_event(self.run_dir, {"e": "run:opened"}), 1)

    def test_writes_are_re_entrant_for_the_lock_holder(self):
        with acquire_lock(self.run_dir):
            append_event(self.run_dir, {"e": "run:opened"})
            append_event(self.run_dir, {"e": "stage:plan:entered"})
            atomic_write_snapshot(self.run_dir, rebuild(self.run_dir))
            self.assertTrue(self.lock.exists())  # still ours, never dropped mid-run

        self.assertFalse(self.lock.exists())
        self.assertEqual(load_snapshot(self.run_dir)["last_seq"], 2)

    def test_snapshot_write_refused_while_another_pid_holds_the_lock(self):
        pid = self.dead_pid()
        self.write_foreign_lock(pid)
        with self.assertRaises(RunLocked) as caught:
            atomic_write_snapshot(self.run_dir, rebuild(self.run_dir))
        self.assertEqual(caught.exception.pid, pid)
        self.assertFalse(caught.exception.holder_alive)
        self.assertFalse(self.snapshot.exists())

    def test_an_unreadable_lockfile_counts_as_locked(self):
        self.lock.write_text("{not json")
        with self.assertRaises(RunLocked):
            append_event(self.run_dir, {"e": "run:opened"})
        with self.assertRaises(RunLocked):
            atomic_write_snapshot(self.run_dir, rebuild(self.run_dir))
        self.assertFalse(self.events.exists())
        self.assertFalse(self.snapshot.exists())

    def test_an_unidentifiable_holder_is_unknown_not_dead(self):
        # A lockfile can be seen between its exclusive create and its payload
        # write. That holder is very much alive, so it must not read as dead.
        self.lock.write_text("{not json")

        with self.assertRaises(RunLocked) as caught:
            append_event(self.run_dir, {"e": "run:opened"})
        self.assertIsNone(caught.exception.holder_alive)

        with self.assertRaises(RunLocked):
            break_lock(self.run_dir)
        self.assertTrue(self.lock.exists())

        self.assertEqual(break_lock(self.run_dir, force=True), {})
        self.assertFalse(self.lock.exists())

    def test_a_dead_holders_lock_is_never_broken_implicitly(self):
        pid = self.dead_pid()
        self.write_foreign_lock(pid)

        with self.assertRaises(RunLocked) as caught:
            append_event(self.run_dir, {"e": "run:opened"})
        self.assertFalse(caught.exception.holder_alive)  # enough to decide resume-or-abort
        self.assertTrue(self.lock.exists())

        holder = break_lock(self.run_dir)  # the caller decides, explicitly
        self.assertEqual(holder["pid"], pid)
        self.assertFalse(self.lock.exists())
        self.assertEqual(append_event(self.run_dir, {"e": "run:opened"}), 1)

    def test_break_lock_refuses_a_live_holder_unless_forced(self):
        with acquire_lock(self.run_dir):
            with self.assertRaises(RunLocked):
                break_lock(self.run_dir)
            self.assertTrue(self.lock.exists())
            break_lock(self.run_dir, force=True)
            self.assertFalse(self.lock.exists())

    def test_break_lock_on_an_unlocked_run_is_a_no_op(self):
        self.assertIsNone(break_lock(self.run_dir))
        self.assertEqual(list(self.run_dir.iterdir()), [])

    def test_a_failed_lock_write_leaves_no_lockfile(self):
        def boom(fd, data):
            raise OSError("disk full")

        with mock.patch("clodex_state.os.write", boom):
            with self.assertRaises(OSError):
                acquire_lock(self.run_dir)
        self.assertFalse(self.lock.exists())
        with acquire_lock(self.run_dir):  # the run is not wedged
            pass


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
        # temp file replaced and the session lock released; write.lock persists
        # by design, so an flock is never held on a replaced inode.
        self.assertEqual(sorted(p.name for p in self.run_dir.iterdir()),
                         ["events.ndjson", "run.json", "write.lock"])

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

    def test_cli_append_works_under_the_callers_lock(self):
        # The child has a different PID; ownership travels by token instead.
        with acquire_lock(self.run_dir):
            result = self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1")
            self.assertEqual(json.loads(self.snapshot.read_text())["last_seq"], 1)
            self.assertTrue(self.lock.exists())  # the child did not steal or drop it

        self.assertFalse(self.lock.exists())

    def test_cli_append_refused_under_a_foreign_lock(self):
        self.write_foreign_lock(self.dead_pid())
        result = self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
        self.assertEqual(result.returncode, 1)
        self.assertIn("locked", result.stderr)
        self.assertFalse(self.events.exists())

    def test_cli_status_reports_a_live_lock(self):
        append_event(self.run_dir, {"e": "run:opened"})
        clean = self.cli("status", str(self.run_dir))
        self.assertNotIn("lock:", clean.stdout)

        with acquire_lock(self.run_dir):
            locked = self.cli("status", str(self.run_dir))
        self.assertEqual(locked.returncode, 0, locked.stderr)
        self.assertIn("lock:", locked.stdout)
        self.assertIn(str(os.getpid()), locked.stdout)
        self.assertIn("running", locked.stdout)

    def test_cli_unlock_removes_a_dead_holders_lock(self):
        pid = self.dead_pid()
        self.write_foreign_lock(pid)

        result = self.cli("unlock", str(self.run_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(pid), result.stdout)
        self.assertFalse(self.lock.exists())

        empty = self.cli("unlock", str(self.run_dir))
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertIn("no lock", empty.stdout)

    def test_cli_unlock_refuses_an_unidentifiable_holder(self):
        self.lock.write_text("{not json")
        result = self.cli("unlock", str(self.run_dir))
        self.assertEqual(result.returncode, 1)
        self.assertIn("liveness unknown", result.stderr)
        self.assertTrue(self.lock.exists())

        forced = self.cli("unlock", str(self.run_dir), "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertFalse(self.lock.exists())

    def test_cli_unlock_refuses_a_live_holder(self):
        with subprocess.Popen(
            [sys.executable, "-c", HOLD_LOCK_SCRIPT, str(self.run_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as holder:
            try:
                if holder.stdout.readline().strip() != "locked":
                    holder.kill()
                    self.fail("lock holder never started: %s" % holder.stderr.read())

                result = self.cli("unlock", str(self.run_dir))
                self.assertEqual(result.returncode, 1)
                self.assertIn("running", result.stderr)
                self.assertTrue(self.lock.exists())

                holder.stdin.write("release\n")
                holder.stdin.flush()
                self.assertEqual(holder.wait(timeout=30), 0)
            finally:
                if holder.poll() is None:
                    holder.kill()

    def test_cli_reports_bad_stdin_on_stderr(self):
        result = self.cli("append", str(self.run_dir), stdin="not json")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        self.assertFalse(self.events.exists())

    def test_cli_refuses_an_event_that_would_break_the_reducer(self):
        self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
        self.cli("append", str(self.run_dir), stdin='{"e": "stage:build:entered"}')
        result = self.cli("append", str(self.run_dir), stdin='{"e": "stage:plan:entered"}')

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        # the illegal event never entered the log, so the run stays readable
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 2)
        self.assertEqual(rebuild(self.run_dir)["stage"], "build")

    def test_cli_refuses_an_event_that_would_break_the_snapshot(self):
        self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
        result = self.cli("append", str(self.run_dir),
                          stdin='{"e": "release:updated", "state": "banana"}')

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        # a payload the snapshot schema rejects must not enter an append-only log
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 1)
        self.assertEqual(json.loads(self.snapshot.read_text())["last_seq"], 1)

        healthy = self.cli("append", str(self.run_dir), stdin='{"e": "stage:plan:entered"}')
        self.assertEqual(healthy.returncode, 0, healthy.stderr)

    def test_cli_append_signals_a_logged_event_with_a_stale_snapshot(self):
        # A non-zero exit must say whether retrying would double-append.
        self.cli("append", str(self.run_dir), stdin='{"e": "run:opened"}')
        self.snapshot.unlink()
        self.snapshot.mkdir()  # os.replace onto a directory fails, the append does not

        result = self.cli("append", str(self.run_dir), stdin='{"e": "stage:plan:entered"}')
        self.assertEqual(result.returncode, clodex_state.EXIT_PARTIAL)
        self.assertEqual(result.stdout.strip(), "")  # no seq: the command did not succeed
        self.assertIn("Do not retry", result.stderr)
        self.assertEqual(rebuild(self.run_dir)["last_seq"], 2)  # the event is durable


if __name__ == "__main__":
    unittest.main()
