#!/usr/bin/env python3
"""clodex run state: append-only event log, deterministic reducer, lock, snapshot.

A run owns a directory (in real use `.clodex/<run-id>/`):

    events.ndjson   append-only log, one JSON object per line — authoritative
    run.json        snapshot: the reduction over events.ndjson — derived
    lock.json       session lock: who owns this run (identity, liveness)
    write.lock      write lock: an flock serializing the writes themselves

Events are the truth. The snapshot is a convenience that is rebuilt from the
events whenever it fails to load, fails schema validation, or lags the log.
The reduction lives in `reducer.py`, which must sit beside this file; it is
imported by path, not by name, so neither module needs to be on sys.path.

Two locks, two jobs
-------------------
They have different lifetimes, so they are different mechanisms:

* **`lock.json` — the session lock.** Who owns this run. Held across many
  writes, carries the holder's PID and ISO timestamp, reports whether that
  holder is still running, and is only ever removed explicitly (`break_lock`,
  `unlock`). A writer that finds someone else's session lock raises `RunLocked`
  rather than writing; resume-or-abort is the caller's decision. Ownership is
  re-entrant for the holder and is delegated to child processes through the
  `CLODEX_LOCK_TOKEN` environment variable.

* **`write.lock` — the write lock.** An advisory `fcntl.flock` held for the
  duration of every write, taken unconditionally: by the session-lock holder
  and by every token-carrying delegate alike. Contention here is normal and
  brief, so it waits (up to `WRITE_LOCK_TIMEOUT`) instead of refusing. This is
  what actually serializes writers, so the session lock never has to designate
  a writer *set* that can race with itself.

Because of the write lock, delegates may run concurrently:

    with acquire_lock(run_dir):                       # this session owns the run
        append_event(run_dir, {"e": "run:opened"})
        atomic_write_snapshot(run_dir, rebuild(run_dir))
        subprocess.run([... "clodex_state.py", "append", run_dir], ...)   # any number,
        subprocess.run([... "clodex_state.py", "append", run_dir], ...)   # in parallel

Nothing an ordinary call can do puts an unreadable event into the log:
`append_event` reduces the log plus the candidate event *before* writing, so an
event that would break the run is refused while the log is still clean.

Library use:

    seq  = append_event(run_dir, {"e": "run:opened", "lane": "feature"})
    snap = rebuild(run_dir)          # pure reduction; rebuild(d) == rebuild(d)
    snap = load_snapshot(run_dir)    # validates, else rebuilds

CLI use (payloads travel by stdin by default; `-e` takes one inline event):

    echo '{"e": "run:opened"}' | python3 clodex_state.py append <run_dir>
    python3 clodex_state.py append <run_dir> -e '{"e": "stage:plan:entered"}'
    python3 clodex_state.py rebuild <run_dir>
    python3 clodex_state.py status  <run_dir>
    python3 clodex_state.py boundary-check <run_dir> [--owned <path>]... [--baseline <file>]
    python3 clodex_state.py telemetry-sync <run_dir> <runner_dir>
    python3 clodex_state.py unlock  <run_dir>

CLI exit codes:

    0  success. For `append`, the event is in the log AND run.json is current;
       the assigned seq is on stdout.
    1  refused, nothing written. Safe to retry.
    2  usage error.
    3  `append` only: the event is durably in the log but run.json was not
       refreshed. DO NOT retry the append — it would double-write an
       append-only log. `rebuild` still reports correct state.

Stdlib only, Python 3.9+. POSIX (uses fcntl).
"""

import argparse
import errno
import fcntl
import importlib.util
import json
import logging
import os
import secrets
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone


def _import_sibling(name):
    """Import a module shipped beside this file, by path.

    Not `import <name>`: that only resolves when this directory happens to be
    on sys.path (true for `python3 clodex_state.py`, false when this module is
    loaded by path), and it would happily bind to any other module of the same
    generic name that reached sys.path first.
    """
    module_name = "clodex_state_" + name
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("clodex state engine is incomplete: %s is missing" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


reducer = _import_sibling("reducer")

# Re-exported so callers need only import this module.
SCHEMA_VERSION = reducer.SCHEMA_VERSION
STAGES = reducer.STAGES
ClodexStateError = reducer.ClodexStateError
ReducerInvariantError = reducer.ReducerInvariantError
load_schema = reducer.load_schema
validate = reducer.validate
reduce_events = reducer.reduce_events

#: The surface the clodex skills depend on.
__all__ = [
    "SCHEMA_VERSION", "STAGES",
    "ClodexStateError", "ReducerInvariantError", "RunLocked",
    "append_event", "rebuild", "load_snapshot", "atomic_write_snapshot",
    "acquire_lock", "break_lock", "Lock",
    "events_path", "snapshot_path", "lock_path", "write_lock_path",
    "load_schema", "validate", "reduce_events",
]

EVENTS_FILE = "events.ndjson"
SNAPSHOT_FILE = "run.json"
LOCK_FILE = "lock.json"
WRITE_LOCK_FILE = "write.lock"

#: Set while a session Lock is held; lets a child process act as the same owner.
LOCK_TOKEN_ENV = "CLODEX_LOCK_TOKEN"

#: Writes are short, so waiting is right; this only bounds a pathological wait.
WRITE_LOCK_TIMEOUT = 30.0

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3

_LOG = logging.getLogger("clodex.state")


class RunLocked(ClodexStateError):
    """Another writer holds the run's session lock."""

    def __init__(self, run_dir, pid=None, acquired_at=None, holder_alive=None):
        self.run_dir = str(run_dir)
        self.pid = pid
        self.acquired_at = acquired_at
        #: True or False when the holder's liveness is known, None when it is not.
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


def write_lock_path(run_dir):
    return os.path.join(str(run_dir), WRITE_LOCK_FILE)


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
# write lock — mutual exclusion between writers
# --------------------------------------------------------------------------- #

#: realpath -> [fd, depth]. flock is per open file description, so a second
#: flock from this same process would block against our own first one.
_WRITE_LOCKS = {}

_WOULD_BLOCK = (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)


def _flock_until(fd, run_dir, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in _WOULD_BLOCK:
                raise
            if time.monotonic() >= deadline:
                raise ClodexStateError(
                    "timed out after %gs waiting to write %s; another writer is not finishing"
                    % (timeout, run_dir)
                )
            time.sleep(0.005)


@contextmanager
def _write_lock(run_dir, timeout=WRITE_LOCK_TIMEOUT):
    """Serialize writers: the session-lock holder and its delegates alike.

    The lockfile is never unlinked. Removing it would let one process hold an
    flock on an inode another process has already replaced.
    """
    key = os.path.realpath(str(run_dir))
    held = _WRITE_LOCKS.get(key)
    if held is not None:  # already ours: re-enter rather than deadlock on our own flock
        held[1] += 1
        try:
            yield
        finally:
            held[1] -= 1
        return

    os.makedirs(key, exist_ok=True)
    fd = os.open(write_lock_path(key), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        _flock_until(fd, key, timeout)
    except BaseException:
        os.close(fd)
        raise

    _WRITE_LOCKS[key] = [fd, 1]
    try:
        yield
    finally:
        del _WRITE_LOCKS[key]
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# --------------------------------------------------------------------------- #
# session lock — who owns the run
# --------------------------------------------------------------------------- #

def _read_lock(run_dir):
    """The session-lock holder: None if there is no lockfile, else a dict.

    A lockfile that exists but cannot be read yields `{}` — present, holder
    unknown — never None. Reporting an unreadable lock as "no lock" would let a
    write proceed where `O_EXCL` would still refuse.
    """
    try:
        with open(lock_path(run_dir), "r", encoding="utf-8") as handle:
            holder = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return holder if isinstance(holder, dict) else {}


def _holder_liveness(holder):
    """True / False / None — None when the holder cannot be identified at all.

    An unidentifiable holder is *unknown*, never "not running": a lockfile can
    be observed in the window between its exclusive create and its payload
    write, and that holder is very much alive.
    """
    pid = (holder or {}).get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
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
        holder_alive=_holder_liveness(holder),
    )


class Lock:
    """The run's session lock. Acquired on construction, released on exit.

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
        # Under the write lock so that break_lock cannot read a holder and then
        # unlink the different lock we create in between.
        with _write_lock(self.run_dir):
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
    """Take the run's session lock, or raise RunLocked carrying the holder's PID and time."""
    return Lock(run_dir)


@contextmanager
def _writer(run_dir):
    """Everything a write needs: the run's session lock, plus mutual exclusion.

    The session lock says this run is ours (taking it if nobody holds it); the
    write lock serializes this write against every other writer, including the
    concurrent delegates that share our session token.
    """
    if _holds_lock(_read_lock(run_dir)):
        with _write_lock(run_dir):
            yield None
        return
    lock = Lock(run_dir)
    try:
        with _write_lock(run_dir):
            yield lock
    finally:
        lock.release()


def break_lock(run_dir, force=False):
    """Remove the run's session lock. Returns the holder it removed, or None.

    Refuses unless the holder is known to be gone — a live holder, or one that
    cannot be identified, is the caller's resume-or-abort decision, never this
    module's. `force` overrides, and is a last resort.
    """
    if _read_lock(run_dir) is None:
        return None
    # Under the write lock: read and unlink must not straddle another acquire.
    with _write_lock(run_dir):
        holder = _read_lock(run_dir)
        if holder is None:
            return None
        if _holder_liveness(holder) is not False and not force:
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


#: Codex roles: a finding from one of these has an envelope, and the join to it
#: is the `invocation` field. (The enum lives in the runner's envelope schema;
#: repeated here because the state engine must not read runner files to append.)
_CODEX_ROLES = ("plan-reviewer", "implementer", "code-reviewer", "advisor")


def _vet_new_event(event):
    """Rules that bind NEW appends only — never the reducer, so a log written
    before a rule existed still reduces unchanged.

    `finding:recorded`: a finding with no severity or no summary is
    content-free — it cannot be disposed on its merits, reviewed by an overturn
    authority, or counted in a severity trend. And a finding from a Codex role
    without its `invocation` has lost the join to the envelope that carries its
    location and detail. Both shapes shipped in the field; neither is a record.
    """
    if event.get("e") != "finding:recorded":
        return
    for key in ("severity", "summary"):
        value = event.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ClodexStateError(
                "finding:recorded needs a non-empty %r — a content-free finding "
                "cannot be disposed on its merits" % key
            )
    source = event.get("source")
    if source in _CODEX_ROLES:
        invocation = event.get("invocation")
        if not isinstance(invocation, str) or not invocation.strip():
            raise ClodexStateError(
                "finding:recorded from Codex role %r needs its 'invocation' — "
                "without it the join to the envelope (location, detail) is lost"
                % source
            )


def append_event(run_dir, event):
    """Append one event to the log and fsync it. Returns the assigned seq.

    Refuses, without writing, any event the reducer could not then read: the
    log plus the candidate is reduced first, so an ordinary call can never
    leave a run unreadable. Raises ReducerInvariantError in that case.

    Runs under the run lock, so reading the last seq and writing the new line
    are atomic against other writers; raises RunLocked if another session owns
    the run. The caller supplies the payload and `e`; seq, schema_version and
    (unless given) `t` are stamped here. The write is durable before this
    returns, so a dependent snapshot replacement or external action can follow.
    """
    if not isinstance(event, dict):
        raise ClodexStateError("event must be a JSON object, got %s" % type(event).__name__)
    if not event.get("e"):
        raise ClodexStateError("event is missing its 'e' (event type) field")
    _vet_new_event(event)

    run_dir = str(run_dir)
    path = events_path(run_dir)
    with _writer(run_dir):
        created = not os.path.exists(path)
        if created:
            events = []
        else:
            _repair_torn_tail(path)
            events = _read_events(run_dir)

        seq = _last_seq(events) + 1
        record = _stamp(event, seq, _now_iso())
        reduce_events(events + [record])  # refuse before the log is touched

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

def _check_run_dir_identity(run_dir):
    """Refuse an append that would fork run state. Returns an error string or None.

    Two guards, both born of one field incident (an append with a relative
    RUN_DIR from the wrong cwd created a parallel empty run directory):

    * the run dir must already exist — creation belongs solely to the router's
      open step, so a path that resolves to nothing is a wrong path, never a
      request to create one;
    * once the log records `run:opened`, the dir must BE that run's directory:
      its resolved path must equal `<recorded repo>/.clodex/<recorded run id>`.
      A copied or wrongly-resolved run dir refuses instead of silently
      diverging from the log it was cloned from.
    """
    if not os.path.isdir(run_dir):
        return (
            "run dir does not exist: %s — append never creates one; "
            "the router's open step owns mkdir" % run_dir
        )
    snap = rebuild(run_dir)
    repo, run_id = snap.get("repo"), snap.get("run")
    if repo and run_id:
        expected = os.path.join(repo, ".clodex", run_id)
        if os.path.realpath(run_dir) != os.path.realpath(expected):
            return (
                "run dir %s is not this run's directory: run:opened records %s "
                "— refusing to fork run state; append from the recorded location"
                % (run_dir, expected)
            )
    return None


def _cmd_append(args):
    problem = _check_run_dir_identity(args.run_dir)
    if problem is not None:
        print("clodex-state: %s" % problem, file=sys.stderr)
        return EXIT_USAGE

    inline = getattr(args, "event", None)
    raw = inline if inline is not None else sys.stdin.read()
    source = "-e payload" if inline is not None else "stdin"
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise ClodexStateError("%s is not a valid JSON event: %s" % (source, exc))
    if not isinstance(event, dict):
        raise ClodexStateError("%s must hold one JSON object" % source)

    # One writer for the pair, so no other writer lands between the event and
    # the snapshot that describes it. append_event does its own vetting.
    with _writer(args.run_dir):
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


# --------------------------------------------------------------------------- #
# telemetry sync — every envelope on disk has a codex block in the log
# --------------------------------------------------------------------------- #

def _cmd_telemetry_sync(args):
    """Diff envelopes on disk against the log's `codex` blocks.

    Every orphan — a completed invocation whose telemetry never reached the
    log — is printed as one ready-to-attach JSON block per line, every field
    copied from the envelope: `status` is never asserted and `duration_s` is
    `exit.duration_ms`, never an estimate. A block in the log with no envelope
    on disk is warned about on stderr (the envelope was lost, not the record).
    Exit 0 when the log and the disk agree; 1 when orphans were printed.
    """
    snap = rebuild(args.run_dir)
    recorded = {
        leg.get("invocation_id")
        for leg in snap.get("invocations") or []
        if leg.get("invocation_id")
    }

    runner_dir = args.runner_dir
    if not os.path.isdir(runner_dir):
        print("clodex-state: runner dir does not exist: %s" % runner_dir, file=sys.stderr)
        return EXIT_USAGE

    on_disk = {}
    for root, _dirs, files in os.walk(runner_dir):
        for name in sorted(files):
            if not name.endswith(".envelope.json"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    envelope = json.load(handle)
            except (OSError, ValueError) as exc:
                print("clodex-state: skipping unreadable envelope %s: %s" % (path, exc),
                      file=sys.stderr)
                continue
            invocation_id = envelope.get("invocation_id")
            if invocation_id:
                on_disk[invocation_id] = (path, envelope)

    orphans = 0
    for invocation_id in sorted(set(on_disk) - recorded):
        path, envelope = on_disk[invocation_id]
        duration_ms = (envelope.get("exit") or {}).get("duration_ms")
        block = {
            "codex": {
                "invocation_id": invocation_id,
                "role": envelope.get("role"),
                "round": None,
                "status": envelope.get("status"),
                "envelope": path,
                "input_hashes": [i.get("sha256") for i in envelope.get("inputs") or []],
                "duration_s": (duration_ms / 1000.0) if duration_ms is not None else None,
                "resumed": (envelope.get("codex") or {}).get("resumed"),
            }
        }
        print(json.dumps(block, sort_keys=True, separators=(",", ":")))
        orphans += 1

    for invocation_id in sorted(recorded - set(on_disk)):
        print(
            "clodex-state: logged invocation %s has no envelope under %s "
            "(the record stands; the envelope is gone)" % (invocation_id, runner_dir),
            file=sys.stderr,
        )

    if orphans:
        print("clodex-state: %d orphaned invocation(s) — attach each block to "
              "your next append" % orphans, file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


# --------------------------------------------------------------------------- #
# boundary check — did the tree stay inside the contract?
# --------------------------------------------------------------------------- #

def _under(path, prefix):
    """True when `path` IS `prefix` or sits inside it (prefix as a directory)."""
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _git_changed_paths(repo, raw=None):
    """Every path `git status --porcelain -z --untracked-files=all` reports,
    including rename/copy ORIGIN paths — a move out of an unowned path into an
    owned one must count against the origin too.
    """
    if raw is None:
        import subprocess
        raw = subprocess.check_output(
            ["git", "-C", repo, "status", "--porcelain", "-z", "--untracked-files=all"],
        ).decode("utf-8", "surrogateescape")
    fields, i, out = raw.split("\0"), 0, []
    while i < len(fields) and fields[i]:
        entry = fields[i]
        i += 1
        out.append((entry[:2], entry[3:]))
        if entry[0] in ("R", "C"):
            out.append((entry[:2], fields[i]))  # the rename's origin path
            i += 1
    return out


def _cmd_boundary_check(args):
    """Classify every changed path: owned / acknowledged / profile / STRAY.

    Replaces the hand-written §7 loop the build skill used to carry. The
    acknowledged set comes from `--baseline` (a pre-invocation
    `git status --porcelain -z --untracked-files=all` capture) when given —
    the at-open `dirty_at_start` snapshot is stale within minutes in a repo
    with a concurrent session, and comparing against it misattributes the
    other session's work to the implementer. Without `--baseline` it falls
    back to `git.dirty_at_start`, ancestors resolved (an acknowledged
    directory covers every file inside it).
    """
    snap = rebuild(args.run_dir)
    repo = snap.get("repo")
    if not repo or not os.path.isdir(repo):
        print("clodex-state: run records no usable repo path: %r" % (repo,), file=sys.stderr)
        return EXIT_USAGE

    owned = list(args.owned or [])
    if not owned:
        batches = snap.get("batches") or []
        if not batches:
            print(
                "clodex-state: no --owned paths given and no batch is open; "
                "boundary-check needs the batch contract's owned paths",
                file=sys.stderr,
            )
            return EXIT_USAGE
        owned = list(batches[-1].get("owned_paths") or [])

    if args.baseline is not None:
        try:
            with open(args.baseline, "r", encoding="utf-8") as handle:
                acknowledged = [path for _, path in _git_changed_paths(repo, handle.read())]
        except OSError as exc:
            print("clodex-state: cannot read baseline %s: %s" % (args.baseline, exc),
                  file=sys.stderr)
            return EXIT_USAGE
    else:
        acknowledged = list(snap["git"]["dirty_at_start"])

    strays = []
    for xy, path in _git_changed_paths(repo):
        if any(_under(path, o) for o in owned):
            label = "owned"
        elif any(_under(path, a) for a in acknowledged):
            label = "acknowledged"
        elif path == ".clodex/profile.json":
            # The one file the ignore rules let through: a router repair or a
            # user edit. Never staged by a run, never a restore target.
            label = "profile"
        else:
            label = "STRAY"
            strays.append(path)
        print("%-12s [%s] %s" % (label, xy, path))

    strays = sorted(set(strays))
    if strays:
        print("STOP — %d path(s) the contract does not allow: %s"
              % (len(strays), " ".join(strays)))
        return EXIT_REFUSED
    print("clean — the contract held")
    return EXIT_OK


def _plural(count, noun):
    return "%d %s%s" % (count, noun, "" if count == 1 else "s")


def _severity_tally(findings):
    """`  high 3, medium 5` — empty when nothing recorded a severity.

    Ordered worst first where the grade is one this project's roles use, then
    anything else alphabetically, because the source owns its own vocabulary.
    """
    known = ["blocker", "critical", "high", "important", "medium", "low", "minor", "info"]
    counts = {}
    for finding in findings:
        severity = finding.get("severity")
        if severity:
            counts[severity] = counts.get(severity, 0) + 1
    if not counts:
        return ""
    order = sorted(counts, key=lambda s: (known.index(s) if s in known else len(known), s))
    return "  " + ", ".join("%s %d" % (s, counts[s]) for s in order)


def _invocation_lines(invocations):
    """One line per Codex role: rounds, legs, and the time the legs really took."""
    roles = []
    for leg in invocations:
        role = leg.get("role")
        if role not in roles:
            roles.append(role)

    lines = []
    for role in roles:
        legs = [leg for leg in invocations if leg.get("role") == role]
        rounds = {leg.get("round") for leg in legs if leg.get("round") is not None}
        seconds = sum(leg.get("duration_s") or 0 for leg in legs)
        parts = []
        if rounds:
            parts.append(_plural(len(rounds), "round"))
        parts.append(_plural(len(legs), "leg"))
        if seconds:
            parts.append("%gs" % seconds)
        interrupted = [leg for leg in legs if leg.get("status") not in (None, "complete")]
        if interrupted:
            parts.append("%d not complete" % len(interrupted))
        lines.append("%s %s" % (role, ", ".join(parts)))
    return lines


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
    preflight = snap.get("preflight") or []
    if preflight:
        last = preflight[-1]
        print("preflight: %s (%d checks)%s" % (
            last["status"], len(last.get("checks") or []),
            ", %d runs" % len(preflight) if len(preflight) > 1 else "",
        ))

    print("findings:  %d (%d open)%s" % (
        len(snap["findings"]), len(open_findings), _severity_tally(snap["findings"]),
    ))
    print("verify:    %d evidence, %d debt" % (
        len(snap["verification"]["evidence"]),
        len(snap["verification"]["debt"]),
    ))
    print("release:   %s%s" % (release["state"], " (%s pending)" % open_step if open_step else ""))
    print("approvals: %d live, %d revoked" % (
        len(live_approvals), len(snap["approvals"]) - len(live_approvals),
    ))
    for line in _invocation_lines(snap.get("invocations") or []):
        print("codex:     %s" % line)

    # A live lock is what a second invocation needs in order to offer resume-or-abort.
    holder = _read_lock(args.run_dir)
    if holder is not None:
        liveness = {True: "running", False: "not running", None: "liveness unknown"}
        print("lock:      held by pid %s (%s) since %s" % (
            holder.get("pid"), liveness[_holder_liveness(holder)], holder.get("acquired_at"),
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
        ("boundary-check", _cmd_boundary_check,
         "classify every changed path in the run's repo: owned / acknowledged / "
         "profile / STRAY; exit 1 on strays"),
        ("telemetry-sync", _cmd_telemetry_sync,
         "print a ready-to-attach codex block for every envelope the log has "
         "no record of; exit 1 when any was printed"),
        ("unlock", _cmd_unlock, "remove the session lock of a holder that is no longer running"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("run_dir", help="the run's directory")
        if name == "append":
            sub.add_argument(
                "-e", "--event", metavar="JSON",
                help="the event as an inline JSON argument instead of stdin — "
                     "for single events that would otherwise need a temp file; "
                     "payloads containing quotes are still safer as files",
            )
        if name == "telemetry-sync":
            sub.add_argument(
                "runner_dir",
                help="the runner state root holding <role>/<id>.envelope.json files",
            )
        if name == "boundary-check":
            sub.add_argument(
                "--owned", action="append", metavar="PATH",
                help="an owned path of the batch under check (repeatable); "
                     "defaults to the last opened batch's owned_paths",
            )
            sub.add_argument(
                "--baseline", metavar="FILE",
                help="a pre-invocation `git status --porcelain -z "
                     "--untracked-files=all` capture; the acknowledged set comes "
                     "from here instead of the at-open dirty_at_start snapshot",
            )
        if name == "unlock":
            sub.add_argument(
                "--force", action="store_true",
                help="break the lock even though the holder is running or unidentifiable",
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
