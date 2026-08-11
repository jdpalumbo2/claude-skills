#!/usr/bin/env python3
"""clodex run state: append-only event log, deterministic reducer, lock, snapshot.

A run owns a directory (in real use `.clodex/<run-id>/`) holding three files:

    events.ndjson   append-only log, one JSON object per line — authoritative
    run.json        snapshot: the reduction over events.ndjson — derived
    lock.json       the single-writer lockfile, carrying PID + ISO timestamp

Events are the truth. The snapshot is a convenience that is rebuilt from the
events whenever it fails to load, fails schema validation, or lags the log.
`rebuild()` reads the wall clock nowhere, so `rebuild(d) == rebuild(d)`: every
timestamp in a snapshot came from an event, stamped once at append time.

Library use:

    seq  = append_event(run_dir, {"e": "run:opened", "lane": "feature"})
    snap = rebuild(run_dir)
    snap = load_snapshot(run_dir)          # validates, else rebuilds
    with acquire_lock(run_dir):            # raises RunLocked if held
        atomic_write_snapshot(run_dir, snap)

CLI use (prompts and payloads travel by stdin, never argv):

    echo '{"e": "run:opened"}' | python3 clodex_state.py append <run_dir>
    python3 clodex_state.py rebuild <run_dir>
    python3 clodex_state.py status  <run_dir>

Stdlib only, Python 3.9+.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

SCHEMA_VERSION = 1

EVENTS_FILE = "events.ndjson"
SNAPSHOT_FILE = "run.json"
LOCK_FILE = "lock.json"

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

#: Stage order. A run never moves left through this list.
STAGES = ("open", "plan", "build", "verify", "ship", "closed")

_LOG = logging.getLogger("clodex.state")


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #

class ClodexStateError(Exception):
    """Any refusal to read or write run state."""


class ReducerInvariantError(ClodexStateError):
    """An event sequence violates an invariant the snapshot depends on."""


class RunLocked(ClodexStateError):
    """Another writer holds the run lock."""

    def __init__(self, run_dir, pid=None, acquired_at=None):
        self.run_dir = str(run_dir)
        self.pid = pid
        self.acquired_at = acquired_at
        super().__init__(
            "run %s is locked by pid %s since %s" % (self.run_dir, pid, acquired_at)
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


# --------------------------------------------------------------------------- #
# schema validation (the subset of JSON Schema these two schemas use)
# --------------------------------------------------------------------------- #

_SCHEMA_CACHE = {}


def _load_schema(name):
    if name not in _SCHEMA_CACHE:
        with open(os.path.join(SCHEMA_DIR, name), "r", encoding="utf-8") as handle:
            _SCHEMA_CACHE[name] = json.load(handle)
    return _SCHEMA_CACHE[name]


def _type_ok(value, type_name):
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    raise ClodexStateError("schema uses unsupported type %r" % (type_name,))


def _validate(value, schema, path="$"):
    """Check `value` against `schema`. Raises ClodexStateError on the first problem."""
    types = schema.get("type")
    if types is not None:
        if isinstance(types, str):
            types = [types]
        if not any(_type_ok(value, name) for name in types):
            raise ClodexStateError(
                "%s: expected %s, got %s" % (path, "|".join(types), type(value).__name__)
            )
    if "enum" in schema and value not in schema["enum"]:
        raise ClodexStateError("%s: %r is not an allowed value" % (path, value))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ClodexStateError("%s: missing required field %r" % (path, key))
        for key, subschema in schema.get("properties", {}).items():
            if key in value:
                _validate(value[key], subschema, "%s.%s" % (path, key))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], "%s[%d]" % (path, index))


# --------------------------------------------------------------------------- #
# event log
# --------------------------------------------------------------------------- #

def _repair_torn_tail(path):
    """Drop an unterminated final line so the next append cannot fuse onto it.

    A line without its newline is a torn write by definition: append_event
    writes record and newline in a single call. This is the truncate-on-recovery
    the contract calls for — it happens only when writing, never on a read.
    """
    size = os.path.getsize(path)
    if size == 0:
        return
    with open(path, "rb") as handle:
        handle.seek(-1, os.SEEK_END)
        if handle.read(1) == b"\n":
            return
        handle.seek(0)
        data = handle.read()
    keep = data.rfind(b"\n") + 1
    os.truncate(path, keep)
    _LOG.warning("truncated torn final line in %s (%d bytes dropped)", path, size - keep)


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
    _validate(record, _load_schema("event.schema.json"))
    return record


def append_event(run_dir, event):
    """Append one event to the log and fsync it. Returns the assigned seq.

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
    if os.path.exists(path):
        _repair_torn_tail(path)
        seq = _last_seq(_read_events(run_dir)) + 1
    else:
        seq = 1

    record = _stamp(event, seq, _now_iso())
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"

    os.makedirs(run_dir, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return seq


# --------------------------------------------------------------------------- #
# reducer
# --------------------------------------------------------------------------- #

def _base_snapshot():
    return {
        "schema_version": SCHEMA_VERSION,
        "run": None,
        "parent": None,
        "repo": None,
        "branch": None,
        "git": {"start_head": None, "dirty_at_start": []},
        "brief": None,
        "lane": None,
        "plan": {"version": None, "path": None, "hash": None, "amendments": []},
        "stage": None,
        "batches": [],
        "findings": [],
        "verification": {"declared": [], "evidence": [], "debt": []},
        "release": {
            "state": "not-started",
            "steps": [],
            "timestamp": None,
            "tag": None,
            "deployed": None,
            "verified_live": None,
        },
        "approvals": [],
        "last_seq": 0,
    }


def _violation(event, message):
    return ReducerInvariantError("event %s (%s): %s" % (event.get("seq"), event.get("e"), message))


def _set_stage(snap, stage, event):
    current = snap["stage"]
    if current is not None and STAGES.index(stage) < STAGES.index(current):
        raise _violation(event, "stage would move backwards, %s -> %s" % (current, stage))
    snap["stage"] = stage


def _pick(snap, event, keys):
    for key in keys:
        if key in event:
            snap[key] = event[key]


def _find(items, key, value, event, what):
    for item in items:
        if item.get(key) == value:
            return item
    raise _violation(event, "no such %s: %r" % (what, value))


def _known_plan_hashes(snap):
    plan = snap["plan"]
    hashes = set()
    if plan["hash"]:
        hashes.add(plan["hash"])
    for amendment in plan["amendments"]:
        for key in ("from_hash", "to_hash"):
            if amendment.get(key):
                hashes.add(amendment[key])
    return hashes


def _on_run_opened(snap, event):
    _set_stage(snap, "open", event)
    _pick(snap, event, ("run", "parent", "repo", "branch", "brief", "lane"))
    git = event.get("git") or {}
    if "start_head" in git:
        snap["git"]["start_head"] = git["start_head"]
    if "dirty_at_start" in git:
        snap["git"]["dirty_at_start"] = list(git["dirty_at_start"])


def _on_run_closed(snap, event):
    _set_stage(snap, "closed", event)


def _stage_entered(stage):
    def handler(snap, event):
        _set_stage(snap, stage, event)
    return handler


def _on_plan_recorded(snap, event):
    plan = snap["plan"]
    if plan["hash"] is not None and event.get("hash") != plan["hash"]:
        raise _violation(event, "a plan is already recorded; supersede it with plan:amended")
    for key in ("version", "path", "hash"):
        if key in event:
            plan[key] = event[key]


def _on_plan_amended(snap, event):
    plan = snap["plan"]
    superseded = plan["hash"]
    if superseded is None:
        raise _violation(event, "amendment before any plan was recorded")
    plan["amendments"].append({
        "seq": event.get("seq"),
        "t": event.get("t"),
        "from_hash": superseded,
        "to_hash": event.get("hash"),
        "version": event.get("version"),
        "note": event.get("note"),
        "required_review": list(event.get("required_review", [])),
    })
    for key in ("version", "path", "hash"):
        if key in event:
            plan[key] = event[key]
    # An amendment supersedes the plan hash, which revokes every approval bound to it.
    snap["approvals"] = [a for a in snap["approvals"] if a.get("plan_hash") != superseded]


def _on_approval(snap, event):
    plan = snap["plan"]
    plan_hash = event.get("plan_hash", plan["hash"])
    if plan_hash is not None and plan_hash not in _known_plan_hashes(snap):
        raise _violation(event, "approval references unknown plan hash %r" % (plan_hash,))
    snap["approvals"].append({
        "t": event.get("t"),
        "scope": event.get("scope", "plan"),
        "by": event.get("by", "user"),
        "plan_version": event.get("plan_version", plan["version"]),
        "plan_hash": plan_hash,
        "actions": list(event.get("actions", [])),
        "accepted_debt": list(event.get("accepted_debt", [])),
    })


def _on_batch_opened(snap, event):
    batch_id = event.get("id")
    if batch_id is None:
        raise _violation(event, "batch:opened without an id")
    if any(batch["id"] == batch_id for batch in snap["batches"]):
        raise _violation(event, "batch %r is already open" % (batch_id,))
    snap["batches"].append({
        "id": batch_id,
        "owned_paths": list(event.get("owned_paths", [])),
        "commit": None,
        "delta_review": None,
    })


def _on_batch_committed(snap, event):
    _find(snap["batches"], "id", event.get("id"), event, "batch")["commit"] = event.get("commit")


def _on_batch_reviewed(snap, event):
    batch = _find(snap["batches"], "id", event.get("id"), event, "batch")
    batch["delta_review"] = event.get("delta_review")


def _on_finding_recorded(snap, event):
    finding_id = event.get("id")
    if finding_id is None:
        raise _violation(event, "finding:recorded without an id")
    if any(finding["id"] == finding_id for finding in snap["findings"]):
        raise _violation(event, "finding %r already recorded" % (finding_id,))
    snap["findings"].append({
        "id": finding_id,
        "source": event.get("source"),
        "disposition": event.get("disposition", "open"),
    })


def _on_finding_disposed(snap, event):
    finding = _find(snap["findings"], "id", event.get("id"), event, "finding")
    finding["disposition"] = event.get("disposition")


def _verification_bucket(bucket):
    def handler(snap, event):
        if "item" not in event:
            raise _violation(event, "verification event without an 'item'")
        snap["verification"][bucket].append(event["item"])
    return handler


def _on_release_step_pending(snap, event):
    step, op_id = event.get("step"), event.get("op_id")
    if not step or not op_id:
        raise _violation(event, "release step needs both 'step' and 'op_id'")
    steps = snap["release"]["steps"]
    open_step = next((s for s in steps if s["status"] == "pending"), None)
    if open_step is not None:
        raise _violation(event, "release step %r is still open" % (open_step["step"],))
    if any(s["op_id"] == op_id for s in steps):
        raise _violation(event, "op_id %r was already used" % (op_id,))
    steps.append({"step": step, "op_id": op_id, "status": "pending", "reconciled": False})
    snap["release"]["state"] = "in-progress"


def _release_step_closed(status):
    def handler(snap, event):
        step = _find(snap["release"]["steps"], "op_id", event.get("op_id"), event, "release step")
        if step["status"] != "pending":
            raise _violation(event, "release step %r is %s, not pending" % (step["step"], step["status"]))
        step["status"] = status
    return handler


def _on_release_step_reconciled(snap, event):
    step = _find(snap["release"]["steps"], "op_id", event.get("op_id"), event, "release step")
    step["reconciled"] = True


def _on_release_updated(snap, event):
    for key in ("state", "timestamp", "tag", "deployed", "verified_live"):
        if key in event:
            snap["release"][key] = event[key]


#: Event type -> handler. Kept in step with the `e` enum in event.schema.json.
_HANDLERS = {
    "run:opened": _on_run_opened,
    "run:closed": _on_run_closed,
    "stage:plan:entered": _stage_entered("plan"),
    "stage:build:entered": _stage_entered("build"),
    "stage:verify:entered": _stage_entered("verify"),
    "stage:ship:entered": _stage_entered("ship"),
    "plan:recorded": _on_plan_recorded,
    "plan:amended": _on_plan_amended,
    "plan:approved": _on_approval,
    "approval:granted": _on_approval,
    "batch:opened": _on_batch_opened,
    "batch:committed": _on_batch_committed,
    "batch:reviewed": _on_batch_reviewed,
    "finding:recorded": _on_finding_recorded,
    "finding:disposed": _on_finding_disposed,
    "verification:declared": _verification_bucket("declared"),
    "verification:evidence": _verification_bucket("evidence"),
    "verification:debt": _verification_bucket("debt"),
    "release:step:pending": _on_release_step_pending,
    "release:step:done": _release_step_closed("done"),
    "release:step:failed": _release_step_closed("failed"),
    "release:step:reconciled": _on_release_step_reconciled,
    "release:updated": _on_release_updated,
}


def _reduce(events):
    """Fold events into a snapshot. Pure: same events in, same snapshot out."""
    snap = _base_snapshot()
    for event in events:
        name = event.get("e")
        handler = _HANDLERS.get(name)
        if handler is None:
            raise ClodexStateError("event %s: unknown event type %r" % (event.get("seq"), name))
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= snap["last_seq"]:
            raise ClodexStateError(
                "event log seq is not monotonic: %r follows %r" % (seq, snap["last_seq"])
            )
        handler(snap, event)
        snap["last_seq"] = seq
    return snap


def rebuild(run_dir):
    """Rebuild the snapshot from the event log. Never writes."""
    return _reduce(_read_events(run_dir))


# --------------------------------------------------------------------------- #
# lock
# --------------------------------------------------------------------------- #

def _read_lock(run_dir):
    try:
        with open(lock_path(run_dir), "r", encoding="utf-8") as handle:
            holder = json.load(handle)
    except (OSError, ValueError):
        return None
    return holder if isinstance(holder, dict) else {}


class Lock:
    """The run's single-writer lock. Acquired on construction, released on exit.

    Raises RunLocked if anyone already holds it — another process, or this one.
    """

    def __init__(self, run_dir):
        self.run_dir = str(run_dir)
        self.path = lock_path(self.run_dir)
        self.pid = os.getpid()
        self.acquired_at = _now_iso()
        self._held = False

        os.makedirs(self.run_dir, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            holder = _read_lock(self.run_dir) or {}
            raise RunLocked(self.run_dir, holder.get("pid"), holder.get("acquired_at"))
        try:
            payload = {"pid": self.pid, "acquired_at": self.acquired_at}
            os.write(fd, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._held = True

    def release(self):
        if not self._held:
            return
        self._held = False
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


# --------------------------------------------------------------------------- #
# snapshot
# --------------------------------------------------------------------------- #

def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_snapshot(run_dir, snap):
    """Validate, then replace run.json atomically. Refuses to write under someone else's lock."""
    run_dir = str(run_dir)
    _validate(snap, _load_schema("snapshot.schema.json"))

    holder = _read_lock(run_dir)
    if holder is not None and holder.get("pid") != os.getpid():
        raise RunLocked(run_dir, holder.get("pid"), holder.get("acquired_at"))

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
        _validate(snap, _load_schema("snapshot.schema.json"))
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

    # Dry-run the reduction first: an event that would break the run never
    # enters the log, so a bad caller cannot leave the run unreadable.
    existing = _read_events(args.run_dir)
    _reduce(existing + [_stamp(event, _last_seq(existing) + 1, _now_iso())])

    print(append_event(args.run_dir, event))
    atomic_write_snapshot(args.run_dir, rebuild(args.run_dir))


def _cmd_rebuild(args):
    print(json.dumps(rebuild(args.run_dir), sort_keys=True, indent=2))


def _cmd_status(args):
    snap = load_snapshot(args.run_dir)
    plan = snap["plan"]
    release = snap["release"]
    open_step = next((s["step"] for s in release["steps"] if s["status"] == "pending"), None)
    open_findings = [f for f in snap["findings"] if f["disposition"] == "open"]

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
    print("approvals: %d" % len(snap["approvals"]))

    # A live lock is what a second invocation needs in order to offer resume-or-abort.
    holder = _read_lock(args.run_dir)
    if holder is not None:
        print("lock:      held by pid %s since %s" % (holder.get("pid"), holder.get("acquired_at")))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="clodex_state.py",
        description="Read and write clodex run state. Event payloads arrive on stdin.",
    )
    subcommands = parser.add_subparsers(dest="command")
    for name, handler, help_text in (
        ("append", _cmd_append, "append one JSON event read from stdin; prints the assigned seq"),
        ("rebuild", _cmd_rebuild, "print the snapshot rebuilt from the event log"),
        ("status", _cmd_status, "print a short summary of the run"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("run_dir", help="the run's directory")
        sub.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_usage(sys.stderr)
        return 2
    try:
        args.handler(args)
    except (ClodexStateError, OSError) as exc:
        print("clodex-state: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="clodex-state: %(message)s")
    sys.exit(main())
