#!/usr/bin/env python3
"""clodex run state: append-only event log, deterministic reducer, lock, snapshot.

A run owns a directory (in real use `.clodex/<run-id>/`) holding three files:

    events.ndjson   append-only log, one JSON object per line — authoritative
    run.json        snapshot: the reduction over events.ndjson — derived
    lock.json       the single-writer lockfile: PID, ISO timestamp, token

Events are the truth. The snapshot is a convenience that is rebuilt from the
events whenever it fails to load, fails schema validation, or lags the log.
The reduction lives in `reducer.py`, which must sit beside this file.

Single writer
-------------
Every write — appending an event *and* replacing the snapshot — happens while
this process holds the run lock. `append_event` takes the lock itself, so the
read-last-seq/write-event pair is atomic and two concurrent appends can never
be handed the same seq. A writer that finds someone else's live lock raises
`RunLocked` rather than writing; resume-or-abort is the caller's decision.

Holding the lock across several operations is re-entrant for the holder, and is
delegated to child processes through the `CLODEX_LOCK_TOKEN` environment
variable, so this works:

    with acquire_lock(run_dir):                       # one writer, many writes
        append_event(run_dir, {"e": "run:opened"})
        atomic_write_snapshot(run_dir, rebuild(run_dir))
        subprocess.run([... "clodex_state.py", "append", run_dir], ...)  # inherits it

A lock is never broken implicitly, not even a dead holder's: `RunLocked` and
`status` report whether the holder is still running, and `break_lock()` /
`unlock` remove it once the caller has decided.

Library use:

    seq  = append_event(run_dir, {"e": "run:opened", "lane": "feature"})
    snap = rebuild(run_dir)          # pure reduction; rebuild(d) == rebuild(d)
    snap = load_snapshot(run_dir)    # validates, else rebuilds

CLI use (payloads travel by stdin, never argv):

    echo '{"e": "run:opened"}' | python3 clodex_state.py append <run_dir>
    python3 clodex_state.py rebuild <run_dir>
    python3 clodex_state.py status  <run_dir>
    python3 clodex_state.py unlock  <run_dir>

CLI exit codes:

    0  success. For `append`, the event is in the log AND run.json is current;
       the assigned seq is on stdout.
    1  refused, nothing written. Safe to retry.
    2  usage error.
    3  `append` only: the event is durably in the log but run.json was not
       refreshed. DO NOT retry the append — it would double-write an
       append-only log. `rebuild` still reports correct state.

Stdlib only, Python 3.9+.
"""

import argparse
import json
import logging
import os
import secrets
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone

from reducer import (  # re-exported: five skills import the API from this module
    SCHEMA_VERSION,
    STAGES,
    ClodexStateError,
    ReducerInvariantError,
    load_schema,
    reduce_events,
    validate,
)

#: The surface the clodex skills depend on. The reducer lives in reducer.py;
#: its names are re-exported here so callers need only import this module.
__all__ = [
    "SCHEMA_VERSION", "STAGES",
    "ClodexStateError", "ReducerInvariantError", "RunLocked",
    "append_event", "rebuild", "load_snapshot", "atomic_write_snapshot",
    "acquire_lock", "break_lock", "Lock",
    "events_path", "snapshot_path", "lock_path",
    "load_schema", "validate", "reduce_events",
]

EVENTS_FILE = "events.ndjson"
SNAPSHOT_FILE = "run.json"
LOCK_FILE = "lock.json"

#: Set while a Lock is held; lets a child process act as the same writer.
LOCK_TOKEN_ENV = "CLODEX_LOCK_TOKEN"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3

_LOG = logging.getLogger("clodex.state")


class RunLocked(ClodexStateError):
    """Another writer holds the run lock."""

    def __init__(self, run_dir, pid=None, acquired_at=None, holder_alive=None):
        self.run_dir = str(run_dir)
        self.pid = pid
        self.acquired_at = acquired_at
        #: True/False when the holder's liveness is known, None when it is not.
        self.holder_alive = holder_alive
        liveness = {True: "running", False: "not running", None: "liveness unknown"}[holder_alive]
        super().__init__(
            "run %s is locked by pid %s (%s) since %s"
            % (self.run_dir, pid, liveness, acquired_at)
        )


# --------------------------------------------------------------------------- #
# paths and time
# --------------------------------------------------------------------------- #

def events_path(run_dir):
    return os.path.join(str(run_dir), EVENTS_FILE)


def snapshot_path(run_dir):
    return os.path.join(str(run_dir), SNAPSHOT_FILE)


def lock_path(run_dir):
    return os.path.join(str(run_dir), LOCK_FILE)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _fsync_dir(path):
    """Make a create/rename in `path` durable, not just the file's contents."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# lock
# --------------------------------------------------------------------------- #

def _read_lock(run_dir):
    """The lock holder: None if there is no lockfile, else a dict.

    A lockfile that exists but cannot be read yields `{}` — present, holder
    unknown — never None. Reporting an unreadable lock as "no lock" would let a
    snapshot write proceed where `O_EXCL` would still refuse.
    """
    try:
        with open(lock_path(run_dir), "r", encoding="utf-8") as handle:
            holder = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return holder if isinstance(holder, dict) else {}


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process, but it is running
    return True


def _holds_lock(holder):
    """True when this process, or the process that delegated to it, owns `holder`."""
    if not holder:
        return False
    if holder.get("pid") == os.getpid():
        return True
    token = os.environ.get(LOCK_TOKEN_ENV)
    return bool(token) and holder.get("token") == token


def _locked_error(run_dir, holder):
    holder = holder or {}
    return RunLocked(
        run_dir,
        holder.get("pid"),
        holder.get("acquired_at"),
        holder_alive=_pid_alive(holder.get("pid")),
    )


class Lock:
    """The run's single-writer lock. Acquired on construction, released on exit.

    Raises RunLocked if anyone already holds it — another process, or this one.
    """

    def __init__(self, run_dir):
        self.run_dir = str(run_dir)
        self.path = lock_path(self.run_dir)
        self.pid = os.getpid()
        self.acquired_at = _now_iso()
        self.token = secrets.token_hex(16)
        self._held = False
        self._restore_token = None

        os.makedirs(self.run_dir, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise _locked_error(self.run_dir, _read_lock(self.run_dir))

        payload = {"pid": self.pid, "acquired_at": self.acquired_at, "token": self.token}
        try:
            try:
                os.write(fd, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            # We created the file; if we could not fill it, we must not leave it.
            try:
                os.unlink(self.path)
            except OSError:
                pass
            raise

        self._restore_token = os.environ.get(LOCK_TOKEN_ENV)
        os.environ[LOCK_TOKEN_ENV] = self.token
        self._held = True

    def release(self):
        if not self._held:
            return
        self._held = False
        if self._restore_token is None:
            os.environ.pop(LOCK_TOKEN_ENV, None)
        else:
            os.environ[LOCK_TOKEN_ENV] = self._restore_token
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def acquire_lock(run_dir):
    """Take the run lock, or raise RunLocked carrying the holder's PID and time."""
    return Lock(run_dir)


@contextmanager
def _writer(run_dir):
    """Hold the run lock for one write, unless this writer already holds it."""
    if _holds_lock(_read_lock(run_dir)):
        yield None
        return
    lock = Lock(run_dir)
    try:
        yield lock
    finally:
        lock.release()


def break_lock(run_dir, force=False):
    """Remove the run's lockfile. Returns the holder it removed, or None.

    Refuses while the holder process is still running unless `force` is set —
    a live lock is the caller's resume-or-abort decision, never this module's.
    """
    holder = _read_lock(run_dir)
    if holder is None:
        return None
    if _pid_alive(holder.get("pid")) and not force:
        raise _locked_error(run_dir, holder)
    try:
        os.unlink(lock_path(run_dir))
    except FileNotFoundError:
        pass
    return holder


# --------------------------------------------------------------------------- #
# event log
# --------------------------------------------------------------------------- #

def _is_event_line(raw):
    try:
        return isinstance(json.loads(raw), dict)
    except ValueError:
        return False


def _repair_torn_tail(path):
    """Make the log's tail safe to append to, by the same rule reads use.

    Reads drop an unparseable final line. Writes must reach the same verdict, or
    appending would push that line into the middle of the file where it becomes
    permanent corruption. So: an unparseable final line is truncated, and a
    parseable one that merely lost its newline is completed rather than dropped.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if not data:
        return

    if data.endswith(b"\n"):
        start = data.rfind(b"\n", 0, len(data) - 1) + 1
        tail = data[start:-1]
        if not tail.strip() or _is_event_line(tail):
            return
        os.truncate(path, start)
        _LOG.warning("dropped invalid final line in %s (%d bytes)", path, len(data) - start)
        return

    start = data.rfind(b"\n") + 1
    tail = data[start:]
    if _is_event_line(tail):
        with open(path, "ab") as handle:
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _LOG.warning("completed unterminated final line in %s", path)
        return
    os.truncate(path, start)
    _LOG.warning("truncated torn final line in %s (%d bytes dropped)", path, len(data) - start)


def _read_events(run_dir):
    """Return every complete event in the log, oldest first.

    A torn (invalid JSON) final line is dropped and logged — never guessed at.
    An invalid line anywhere else is real corruption and raises.
    """
    path = events_path(run_dir)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        lines = [line for line in handle.read().splitlines() if line.strip()]

    events = []
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            if index == len(lines) - 1:
                _LOG.warning("dropping torn final line in %s: %.80s", path, line)
                break
            raise ClodexStateError("%s: line %d is not valid JSON" % (path, index + 1))
        if not isinstance(event, dict):
            raise ClodexStateError("%s: line %d is not a JSON object" % (path, index + 1))
        events.append(event)
    return events


def _last_seq(events):
    if not events:
        return 0
    seq = events[-1].get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise ClodexStateError("last event has a non-integer seq: %r" % (seq,))
    return seq


def _stamp(event, seq, timestamp):
    record = dict(event)
    record["schema_version"] = SCHEMA_VERSION
    record["seq"] = seq
    record.setdefault("t", timestamp)
    validate(record, load_schema("event.schema.json"))
    return record


def append_event(run_dir, event):
    """Append one event to the log and fsync it. Returns the assigned seq.

    Held under the run lock, so reading the last seq and writing the new line
    are atomic against other writers; raises RunLocked if someone else holds it.
    The caller supplies the payload and `e`; seq, schema_version and (unless
    given) `t` are stamped here. The write is durable before this returns, so a
    dependent snapshot replacement or external action can safely follow.
    """
    if not isinstance(event, dict):
        raise ClodexStateError("event must be a JSON object, got %s" % type(event).__name__)
    if not event.get("e"):
        raise ClodexStateError("event is missing its 'e' (event type) field")

    run_dir = str(run_dir)
    path = events_path(run_dir)
    with _writer(run_dir):
        created = not os.path.exists(path)
        if created:
            seq = 1
        else:
            _repair_torn_tail(path)
            seq = _last_seq(_read_events(run_dir)) + 1

        record = _stamp(event, seq, _now_iso())
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"

        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            _fsync_dir(run_dir)  # the new dirent, not just its contents
    return seq


def rebuild(run_dir):
    """Rebuild the snapshot from the event log. Never writes."""
    return reduce_events(_read_events(run_dir))


# --------------------------------------------------------------------------- #
# snapshot
# --------------------------------------------------------------------------- #

def atomic_write_snapshot(run_dir, snap):
    """Validate, then replace run.json atomically, under the run lock."""
    run_dir = str(run_dir)
    validate(snap, load_schema("snapshot.schema.json"))

    with _writer(run_dir):
        os.makedirs(run_dir, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".run-", suffix=".json", dir=run_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(snap, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, snapshot_path(run_dir))
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise
        _fsync_dir(run_dir)


def load_snapshot(run_dir):
    """Return run.json if it is valid and current, else rebuild from the events."""
    path = snapshot_path(run_dir)
    if not os.path.exists(path):
        return rebuild(run_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            snap = json.load(handle)
        validate(snap, load_schema("snapshot.schema.json"))
    except (OSError, ValueError, ClodexStateError) as exc:
        _LOG.warning("snapshot %s is unusable (%s); rebuilding from events", path, exc)
        return rebuild(run_dir)

    logged = _last_seq(_read_events(run_dir))
    if snap.get("last_seq") != logged:
        _LOG.warning(
            "snapshot %s is stale (last_seq %s, log %s); rebuilding from events",
            path, snap.get("last_seq"), logged,
        )
        return rebuild(run_dir)
    return snap


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _cmd_append(args):
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise ClodexStateError("stdin is not a valid JSON event: %s" % exc)
    if not isinstance(event, dict):
        raise ClodexStateError("stdin must hold one JSON object")

    with _writer(args.run_dir):
        # Dry-run the reduction first. reduce_events validates the snapshot it
        # produces, so an event that would make this run unwritable never
        # enters the log.
        existing = _read_events(args.run_dir)
        reduce_events(existing + [_stamp(event, _last_seq(existing) + 1, _now_iso())])

        seq = append_event(args.run_dir, event)
        try:
            atomic_write_snapshot(args.run_dir, rebuild(args.run_dir))
        except (ClodexStateError, OSError) as exc:
            print(
                "clodex-state: event %d is durably in the log but run.json was not "
                "refreshed (%s). Do not retry the append; rebuild reports true state."
                % (seq, exc),
                file=sys.stderr,
            )
            return EXIT_PARTIAL

    # Printed only once the event is logged and the snapshot is current, so a
    # seq on stdout always means the whole command succeeded.
    print(seq)
    return EXIT_OK


def _cmd_rebuild(args):
    print(json.dumps(rebuild(args.run_dir), sort_keys=True, indent=2))
    return EXIT_OK


def _cmd_status(args):
    snap = load_snapshot(args.run_dir)
    plan = snap["plan"]
    release = snap["release"]
    open_step = next((s["step"] for s in release["steps"] if s["status"] == "pending"), None)
    open_findings = [f for f in snap["findings"] if f["disposition"] == "open"]
    live_approvals = [a for a in snap["approvals"] if a["revoked"] is None]

    print("run:       %s (lane %s)" % (snap["run"] or "-", snap["lane"] or "-"))
    print("stage:     %s   last_seq %d" % (snap["stage"] or "-", snap["last_seq"]))
    if plan["hash"] is None:
        print("plan:      none recorded")
    else:
        print("plan:      v%s %s (%d amendments)" % (
            plan["version"], plan["path"] or "-", len(plan["amendments"]),
        ))
    print("batches:   %d (%d committed)" % (
        len(snap["batches"]),
        sum(1 for b in snap["batches"] if b["commit"]),
    ))
    print("findings:  %d (%d open)" % (len(snap["findings"]), len(open_findings)))
    print("verify:    %d evidence, %d debt" % (
        len(snap["verification"]["evidence"]),
        len(snap["verification"]["debt"]),
    ))
    print("release:   %s%s" % (release["state"], " (%s pending)" % open_step if open_step else ""))
    print("approvals: %d live, %d revoked" % (
        len(live_approvals), len(snap["approvals"]) - len(live_approvals),
    ))

    # A live lock is what a second invocation needs in order to offer resume-or-abort.
    holder = _read_lock(args.run_dir)
    if holder is not None:
        alive = _pid_alive(holder.get("pid"))
        print("lock:      held by pid %s (%s) since %s" % (
            holder.get("pid"), "running" if alive else "not running", holder.get("acquired_at"),
        ))
    return EXIT_OK


def _cmd_unlock(args):
    holder = break_lock(args.run_dir, force=args.force)
    if holder is None:
        print("no lock held")
    else:
        print("removed lock held by pid %s since %s" % (
            holder.get("pid"), holder.get("acquired_at"),
        ))
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="clodex_state.py",
        description="Read and write clodex run state. Event payloads arrive on stdin.",
        epilog="exit codes: 0 ok; 1 refused, nothing written; 2 usage; "
               "3 append only — event logged but run.json not refreshed, do not retry.",
    )
    subcommands = parser.add_subparsers(dest="command")
    for name, handler, help_text in (
        ("append", _cmd_append, "append one JSON event read from stdin; prints the assigned seq"),
        ("rebuild", _cmd_rebuild, "print the snapshot rebuilt from the event log"),
        ("status", _cmd_status, "print a short summary of the run"),
        ("unlock", _cmd_unlock, "remove the lockfile of a holder that is no longer running"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("run_dir", help="the run's directory")
        if name == "unlock":
            sub.add_argument(
                "--force", action="store_true",
                help="break the lock even though the holder is still running",
            )
        sub.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    try:
        return args.handler(args)
    except (ClodexStateError, OSError) as exc:
        print("clodex-state: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="clodex-state: %(message)s")
    sys.exit(main())
