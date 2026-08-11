#!/usr/bin/env python3
"""The clodex result-envelope contract: export, assemble, validate.

`run-codex.sh` is the authority for every fact it can observe — the invocation
id, the role, exit metadata, the paths to full output, and the hashes of the
input artifacts. Codex's structured output covers only the model-authored part
(`$defs.model_report` in envelope.schema.json): the model's own completeness
assessment and its findings. This module exports that sub-schema for
`codex --output-schema`, folds the model's report into a complete envelope,
reconciles the final status against how the process actually ended, and
validates the whole document. The model is never trusted for a fact the runner
knows, and never for the status.

    python3 validate_envelope.py model-schema --out <path>
    python3 validate_envelope.py build <facts...> --out <path>   # prints status
    python3 validate_envelope.py validate <envelope.json>

`build` exits non-zero only when it cannot produce a valid envelope at all; a
`failed`/`partial`/`interrupted` envelope is still written, and the caller maps
the status it prints to its own exit code. `validate` exits non-zero on a
missing, malformed or schema-invalid envelope.

Stdlib only, Python 3.9+.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

SCHEMA_VERSION = 1
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "envelope.schema.json")
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class EnvelopeError(Exception):
    """Anything that makes an envelope untrustworthy."""


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #

def load_schema():
    try:
        with open(SCHEMA_PATH) as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise EnvelopeError("cannot load %s: %s" % (SCHEMA_PATH, exc))


_TYPE_NAMES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, name):
    if name == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool) and name in ("integer", "number"):
        return False
    expected = _TYPE_NAMES.get(name)
    if expected is None:
        raise EnvelopeError("schema uses unknown type %r" % name)
    return isinstance(value, expected)


def validate(value, schema, path="$"):
    """Check `value` against `schema`. Raises EnvelopeError on the first problem.

    Supports the keyword subset the envelope schema uses: type, enum, required,
    properties, additionalProperties, items.
    """
    types = schema.get("type")
    if types is not None:
        if isinstance(types, str):
            types = [types]
        if not any(_type_ok(value, name) for name in types):
            raise EnvelopeError(
                "%s: expected %s, got %s" % (path, "|".join(types), type(value).__name__)
            )
    if "enum" in schema and value not in schema["enum"]:
        raise EnvelopeError("%s: %r is not an allowed value" % (path, value))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise EnvelopeError("%s: missing required field %r" % (path, key))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    raise EnvelopeError("%s: unexpected field %r" % (path, key))
        for key, subschema in properties.items():
            if key in value:
                validate(value[key], subschema, "%s.%s" % (path, key))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], "%s[%d]" % (path, index))


def model_schema():
    """The model-authored sub-schema, standalone, for `codex --output-schema`."""
    schema = load_schema()
    try:
        report = schema["$defs"]["model_report"]
    except KeyError:
        raise EnvelopeError("%s has no $defs.model_report" % SCHEMA_PATH)
    standalone = {"$schema": JSON_SCHEMA_DIALECT, "title": "clodex codex model report"}
    standalone.update(json.loads(json.dumps(report)))
    return standalone


# --------------------------------------------------------------------------- #
# assembling an envelope
# --------------------------------------------------------------------------- #

def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EnvelopeError("cannot hash input artifact %s: %s" % (path, exc))
    return digest.hexdigest()


def read_model_report(path):
    """Return (report, error). `report` is None whenever it is not trustworthy."""
    if not path or not os.path.exists(path):
        return None, "codex wrote no result envelope at %s" % path
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError as exc:
        return None, "cannot read the result envelope at %s: %s" % (path, exc)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
    if not text:
        return None, "the result envelope at %s is empty" % path
    try:
        report = json.loads(text)
    except ValueError as exc:
        return None, "the result envelope at %s is not JSON: %s" % (path, exc)
    try:
        validate(report, load_schema()["$defs"]["model_report"], "$model_report")
    except EnvelopeError as exc:
        return None, "the result envelope at %s does not match the schema: %s" % (path, exc)
    return report, None


def reconcile_status(exit_code, signal, interrupted, model_status):
    """Decide the invocation's real status. The model never gets the last word."""
    if interrupted or signal:
        return "interrupted"
    if exit_code != 0:
        return "failed"
    if model_status == "partial":
        return "partial"
    if model_status == "complete":
        return "complete"
    return "failed"


def duration_ms(started_at, ended_at):
    try:
        start = datetime.strptime(started_at, TIMESTAMP_FORMAT)
        end = datetime.strptime(ended_at, TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return int((end - start).total_seconds() * 1000)


def build_envelope(args):
    """Assemble the full envelope from runner facts plus the model's report."""
    signal = args.exit_code - 128 if args.exit_code is not None and args.exit_code >= 128 else None
    report, error = read_model_report(args.model_report)
    model_status = report["status"] if report else None
    status = reconcile_status(args.exit_code, signal, args.interrupted, model_status)

    seen = set()
    inputs = []
    for path in args.input or []:
        if path in seen:
            continue
        seen.add(path)
        inputs.append({"path": path, "sha256": sha256_file(path)})

    findings = []
    for index, finding in enumerate(report["findings"] if report else [], start=1):
        findings.append({
            "id": "F%03d" % index,
            "severity": finding["severity"],
            "summary": finding["summary"],
            "detail": finding["detail"],
            "location": finding["location"],
        })

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "invocation_id": args.invocation_id,
        "role": args.role,
        "status": status,
        "model_status": model_status,
        "summary": report["summary"] if report else None,
        "error": error,
        "inputs": inputs,
        "findings": findings,
        "exit": {
            "code": args.exit_code,
            "signal": signal,
            "started_at": args.started_at,
            "ended_at": args.ended_at,
            "duration_ms": duration_ms(args.started_at, args.ended_at),
        },
        "codex": {
            "model": args.model,
            "effort": args.effort,
            "sandbox": args.sandbox,
            "session_id": args.session_id or None,
            "resumed": args.resumed,
        },
        "output": {
            "events": args.events,
            "stderr": args.stderr,
            "model_report": args.model_report,
            "state_dir": args.state_dir,
        },
    }
    validate(envelope, load_schema())
    return envelope, error


def write_json(payload, path):
    try:
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        raise EnvelopeError("cannot write %s: %s" % (path, exc))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    export = sub.add_parser("model-schema", help="write the model-authored sub-schema")
    export.add_argument("--out", required=True)

    build = sub.add_parser("build", help="assemble and validate an envelope")
    build.add_argument("--invocation-id", required=True)
    build.add_argument("--role", required=True)
    build.add_argument("--exit-code", type=int, required=True)
    build.add_argument("--interrupted", action="store_true")
    build.add_argument("--started-at", required=True)
    build.add_argument("--ended-at", required=True)
    build.add_argument("--model", required=True)
    build.add_argument("--effort", required=True)
    build.add_argument("--sandbox", required=True)
    build.add_argument("--session-id", default="")
    build.add_argument("--resumed", action="store_true")
    build.add_argument("--events", required=True)
    build.add_argument("--stderr", required=True)
    build.add_argument("--model-report", required=True)
    build.add_argument("--state-dir", required=True)
    build.add_argument("--input", action="append", default=[])
    build.add_argument("--out", required=True)

    check = sub.add_parser("validate", help="validate an existing envelope")
    check.add_argument("envelope")

    args = parser.parse_args(argv)

    if args.command == "model-schema":
        write_json(model_schema(), args.out)
        return 0

    if args.command == "build":
        envelope, error = build_envelope(args)
        write_json(envelope, args.out)
        if error:
            sys.stderr.write("%s\n" % error)
        sys.stdout.write("%s\n" % envelope["status"])
        return 0

    try:
        with open(args.envelope) as handle:
            envelope = json.load(handle)
    except OSError as exc:
        raise EnvelopeError("cannot read the envelope: %s" % exc)
    except ValueError as exc:
        raise EnvelopeError("the envelope is not valid JSON: %s" % exc)
    validate(envelope, load_schema())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except EnvelopeError as failure:
        sys.stderr.write("envelope error: %s\n" % failure)
        sys.exit(1)
