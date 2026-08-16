#!/usr/bin/env python3
"""The clodex run-state data contract: schemas, invariants, and the reduction.

`clodex_state.py` owns the files (event log, lock, snapshot) and the CLI; this
module owns what the data *means*. It ships alongside `schemas/` so that any
conforming implementation rebuilds identical state from the same events.

The reduction is pure — it reads no clock, no PID, no environment — so
`reduce_events(events)` is a function of the events alone, and every timestamp
in a snapshot came from an event, stamped once at append time.

Import via `clodex_state`, which re-exports everything a caller needs.
Stdlib only, Python 3.9+.
"""

import json
import os

SCHEMA_VERSION = 1

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

#: Stage order. A run never moves left through this list.
STAGES = ("open", "plan", "build", "verify", "ship", "closed")


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #

class ClodexStateError(Exception):
    """Any refusal to read or write run state."""


class ReducerInvariantError(ClodexStateError):
    """An event sequence violates an invariant the snapshot depends on."""


# --------------------------------------------------------------------------- #
# schema validation (the subset of JSON Schema these two schemas use)
# --------------------------------------------------------------------------- #

_SCHEMA_CACHE = {}


def load_schema(name):
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


def validate(value, schema, path="$"):
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
                validate(value[key], subschema, "%s.%s" % (path, key))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], "%s[%d]" % (path, index))


def release_states():
    """The allowed values of `release.state`, straight from the snapshot schema."""
    schema = load_schema("snapshot.schema.json")
    return schema["properties"]["release"]["properties"]["state"]["enum"]


# --------------------------------------------------------------------------- #
# the snapshot
# --------------------------------------------------------------------------- #

def base_snapshot():
    """The state of a run before any event."""
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


# --------------------------------------------------------------------------- #
# handler helpers
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# telemetry — what happened around an event, not a new kind of event
# --------------------------------------------------------------------------- #

#: Any event may carry these. They exist because the pilot could not answer,
#: from the manifest alone, how many review rounds ran, which invocation raised
#: a finding, what a round cost, or whether preflight ever passed — while the
#: event vocabulary is frozen at the 23 names in HANDLERS. So they are fields,
#: not names, and the buckets they fill are created on first use: a log that
#: carries none of them reduces to exactly the bytes it did before they existed.
TELEMETRY = ("preflight", "codex")


def _collect_telemetry(snap, event):
    preflight = event.get("preflight")
    if preflight is not None:
        if not isinstance(preflight, dict) or not preflight.get("status"):
            raise _violation(event, "preflight must be an object carrying a 'status'")
        snap.setdefault("preflight", []).append(
            dict(preflight, seq=event.get("seq"), t=event.get("t"))
        )

    codex = event.get("codex")
    if codex is not None:
        if not isinstance(codex, dict):
            raise _violation(event, "codex must be an object")
        # An invocation record that cannot be matched to an invocation is worse
        # than no record: it reads as evidence that a round happened.
        for key in ("invocation_id", "role"):
            if not codex.get(key):
                raise _violation(event, "codex block must carry a non-empty %r" % key)
        # One entry per leg, never merged. A resumed round overwrites its own
        # envelope on disk, so the interrupted leg's duration survives only here.
        snap.setdefault("invocations", []).append(
            dict(codex, seq=event.get("seq"), t=event.get("t"))
        )


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #

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
    # An amendment exists to supersede a hash. Without a real new one it would
    # revoke every approval and bind the plan to nothing in exchange.
    new_hash = event.get("hash")
    if not isinstance(new_hash, str) or not new_hash:
        raise _violation(event, "plan:amended must carry the new plan hash")
    if new_hash == superseded:
        raise _violation(event, "plan:amended does not supersede anything: the hash is unchanged")
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

    # An amendment supersedes the plan hash, which revokes every approval bound
    # to it. The approval stays in the snapshot carrying its revocation, so a
    # later skill can answer "what happened" from the manifest alone.
    for approval in snap["approvals"]:
        if approval["revoked"] is None and approval["plan_hash"] == superseded:
            approval["revoked"] = {
                "seq": event.get("seq"),
                "t": event.get("t"),
                "superseded_hash": superseded,
                "superseding_hash": plan["hash"],
            }


def _on_approval(snap, event):
    plan = snap["plan"]
    current = plan["hash"]
    plan_hash = event.get("plan_hash", current)
    # An approval bound to nothing could never be revoked by an amendment.
    if not plan_hash:
        raise _violation(
            event,
            "approval must bind to a plan hash; none given and no plan is recorded",
        )
    # And it must be the *current* hash, not merely one the log has seen. An
    # amendment's revocation sweep runs once, when that amendment is reduced,
    # so an approval arriving afterwards against a superseded hash would never
    # be swept — it would sit there looking live forever.
    if plan_hash != current:
        raise _violation(
            event,
            "approval binds to plan hash %r but the current plan hash is %r"
            % (plan_hash, current),
        )
    snap["approvals"].append({
        "t": event.get("t"),
        "scope": event.get("scope", "plan"),
        "by": event.get("by", "user"),
        "plan_version": event.get("plan_version", plan["version"]),
        "plan_hash": plan_hash,
        "actions": list(event.get("actions", [])),
        "accepted_debt": list(event.get("accepted_debt", [])),
        "revoked": None,
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
    # Which invocation reviewed it, when one did. Carried only when given: a
    # verdict reached without a Codex round says so by leaving this out.
    if "invocation" in event:
        batch["invocation"] = event["invocation"]


def _on_finding_recorded(snap, event):
    finding_id = event.get("id")
    if finding_id is None:
        raise _violation(event, "finding:recorded without an id")
    if any(finding["id"] == finding_id for finding in snap["findings"]):
        raise _violation(event, "finding %r already recorded" % (finding_id,))
    finding = {
        "id": finding_id,
        "source": event.get("source"),
        "disposition": event.get("disposition", "open"),
    }
    # Recorded only when given, so a log that set none of them is unchanged.
    # `round` and `invocation` are what let a reader see the severity trend
    # across rounds; `plan_hash` is which version the finding was raised
    # against, which the run's own id convention used to be the only trace of.
    # `location`/`detail`/`recommendation` are the envelope's own field names,
    # copied through so an overturn authority can rule from the manifest alone
    # — the first project to gate on accepted findings got one sentence each
    # from state while every envelope carried file:line.
    for key in ("severity", "summary", "location", "detail", "recommendation",
                "round", "invocation", "plan_hash"):
        if key in event:
            finding[key] = event[key]
    snap["findings"].append(finding)


def _on_finding_disposed(snap, event):
    finding = _find(snap["findings"], "id", event.get("id"), event, "finding")
    finding["disposition"] = event.get("disposition")
    # The disposition's grounds reach the snapshot too: acceptance grounds that
    # live only in the event log are invisible to the gate that reads the
    # manifest. Carried only when given, so old logs reduce unchanged.
    if "note" in event:
        finding["note"] = event["note"]


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
    if "state" in event and event["state"] not in release_states():
        raise _violation(event, "release state %r is not one of: %s" % (
            event["state"], ", ".join(release_states()),
        ))
    for key in ("state", "timestamp", "tag", "deployed", "verified_live"):
        if key in event:
            snap["release"][key] = event[key]


#: Event type -> handler. Kept in step with the `e` enum in event.schema.json.
HANDLERS = {
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


def reduce_events(events):
    """Fold events into a snapshot. Pure: same events in, same snapshot out.

    The result is validated against snapshot.schema.json before it is returned,
    so a payload that would produce an unwritable snapshot fails here — at the
    event that caused it — rather than at some later write.
    """
    snap = base_snapshot()
    for event in events:
        name = event.get("e")
        handler = HANDLERS.get(name)
        if handler is None:
            raise ClodexStateError("event %s: unknown event type %r" % (event.get("seq"), name))
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= snap["last_seq"]:
            raise ClodexStateError(
                "event log seq is not monotonic: %r follows %r" % (seq, snap["last_seq"])
            )
        handler(snap, event)
        _collect_telemetry(snap, event)
        snap["last_seq"] = seq

    try:
        validate(snap, load_schema("snapshot.schema.json"))
    except ReducerInvariantError:
        raise
    except ClodexStateError as exc:
        raise ReducerInvariantError("reduced snapshot violates the snapshot schema: %s" % exc)
    return snap
