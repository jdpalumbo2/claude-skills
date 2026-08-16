#!/usr/bin/env bash
# clodex — the shared Codex runner. Every Codex call clodex makes goes through
# this script; no skill runs `codex` itself.
#
# Adapted from the TRIP workflow by PiLastDigit (upstream: PiLastDigit/
# TRIP-workflow, MIT) — the start/resume handling, the per-target state-file
# layout and the model/effort defaults of its codex-* skill scripts. Reworked
# here into one role-parameterized runner that fails closed on a machine-
# checked result envelope.
#
# Usage:
#   run-codex.sh --role <plan-reviewer|implementer|code-reviewer|advisor> \
#                --repo <repo root> --prompt-file <path> [--input <path>]... \
#                [--run-id <run-id>] [--detach]
#   run-codex.sh --role <role> --repo <repo root> --resume <invocation-id> \
#                [--prompt-file <path>] [--input <path>]... [--run-id <run-id>]
#
# The prompt is never passed as a shell argument: codex reads it from stdin.
# `--input` declares an artifact the invocation is working from (a plan, a
# diff); the runner hashes each one into the envelope. The prompt file is
# always an input. On --resume the prompt path is read back from the
# invocation's meta when not given, so `--resume <id>` works alone.
#
# Run state belongs to the repo being worked on, never to the skill catalogue.
# Each role gets its own directory — keyed by run id when one is given, so two
# runs in one repo never interleave their envelopes:
#
#   <repo>/.clodex/runner/<role>/<invocation-id>.*              (no --run-id)
#   <repo>/.clodex/runner/<run-id>/<role>/<invocation-id>.*     (--run-id)
#
# Override the root with CLODEX_RUNNER_STATE_DIR. Per invocation:
#   <id>.envelope.json   the result envelope; the only thing callers may trust
#   <id>.events.ndjson   codex --json event stream (full output, progress)
#   <id>.stderr.log      codex stderr
#   <id>.runner.log      the runner's own narration: heartbeats, the status
#                        line, resume hints — everything a detached caller
#                        needs to watch
#   <id>.model.json      the structured report codex wrote (its -o target)
#   <id>.model-schema.json  what codex was told to shape that report like
#   <id>.session         codex session id — the checkpoint --resume needs
#   <id>.meta            role/repo/model/effort/prompt of the original invocation
#   <id>.inputs          declared input artifacts
#
# Model and effort default per role and can be overridden per run with
# CODEX_MODEL / CODEX_EFFORT. While codex works, a heartbeat line goes to the
# runner log every CLODEX_HEARTBEAT_SECONDS (default 60; 0 turns it off) —
# never to stdout or stderr, so a consumer that goes away cannot kill the run.
#
# --detach backgrounds the whole invocation (nohup internally), prints one
# line — `detached <invocation-id> pid <pid> log <runner log path>` — and
# returns immediately. Watch it the way the skills document: the pid, plus the
# runner log's final `^(complete|partial|interrupted|failed) ` status line.
#
# The envelope is written from an EXIT trap: no death mode — signal, set -e,
# a consumer closing the pipe — may end this script after codex started
# without leaving an envelope behind.
#
# Exit: 0 complete · 1 failed (including a missing or invalid envelope)
#       2 partial · 3 interrupted · 64 usage error
#       --detach: 0 once the background invocation is launched

set -euo pipefail

# A consumer that stops listening must never kill the run: writes to a dead
# pipe get EPIPE (handled per-write) instead of SIGPIPE (fatal, untrappable
# mid-write). A 27-minute implementer round once died envelope-less this way.
trap '' PIPE

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVELOPE_TOOL="$RUNNER_DIR/validate_envelope.py"
HEARTBEAT_SECONDS="${CLODEX_HEARTBEAT_SECONDS:-60}"

die() { printf 'run-codex.sh: %s\n' "$1" >&2; exit "${2:-64}"; }

# The header comment above, minus the shebang, is the help text.
usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" >&2
}

# Absolute, symlink-resolved paths (no readlink -f: this is BSD userland).
abs_dir() { (cd "$1" 2>/dev/null && pwd -P); }

abs_file() {
    local dir base
    dir="$(abs_dir "$(dirname -- "$1")")" || return 1
    [ -n "$dir" ] || return 1
    base="$(basename -- "$1")"
    printf '%s/%s\n' "$dir" "$base"
}

meta_get() {
    awk -v k="$1" 'substr($0, 1, length(k) + 1) == k "=" { print substr($0, length(k) + 2); exit }' "$2"
}

role_sandbox() {
    case "$1" in
        implementer) printf 'workspace-write\n' ;;
        plan-reviewer|code-reviewer|advisor) printf 'read-only\n' ;;
        *) return 1 ;;
    esac
}

role_model() {
    case "$1" in
        implementer) printf '%s\n' "${CODEX_MODEL:-gpt-5.6-luna}" ;;
        *) printf '%s\n' "${CODEX_MODEL:-gpt-5.6-sol}" ;;
    esac
}

# The session id to resume from: the LAST one in the event stream, because
# resumes append to the same stream and codex may mint a new id each time.
# On a first run the last is the only one. Tolerant about event shape — the id
# may sit at any depth, inside objects or arrays.
extract_session_id() {
    python3 - "$1" <<'PY'
import json, sys

KEYS = ("thread_id", "session_id", "conversation_id")
found = ""
try:
    handle = open(sys.argv[1])
except OSError:
    sys.exit(0)
with handle:
    for line in handle:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        stack = [event]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in KEYS:
                    value = node.get(key)
                    if isinstance(value, str) and value:
                        found = value
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
if found:
    print(found)
PY
}

# --------------------------------------------------------------------------- #
# arguments
# --------------------------------------------------------------------------- #

ROLE=""
REPO=""
PROMPT_FILE=""
RESUME_ID=""
RUN_ID=""
DETACH=0
INPUTS=()
CHILD_ARGS=()   # everything except --detach, for the re-exec a detach makes

# A flag given as the final argument has no value to shift to; without this
# `shift 2` would fail and set -e would kill the script with no message.
need_value() {
    [ "$1" -ge 2 ] || die "$2 needs a value"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --role)          need_value $# "$1"; ROLE="$2"; CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --role=*)        ROLE="${1#*=}"; CHILD_ARGS+=("$1"); shift ;;
        --repo)          need_value $# "$1"; REPO="$2"; CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --repo=*)        REPO="${1#*=}"; CHILD_ARGS+=("$1"); shift ;;
        --prompt-file)   need_value $# "$1"; PROMPT_FILE="$2"; CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --prompt-file=*) PROMPT_FILE="${1#*=}"; CHILD_ARGS+=("$1"); shift ;;
        --input)         need_value $# "$1"; INPUTS+=("$2"); CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --input=*)       INPUTS+=("${1#*=}"); CHILD_ARGS+=("$1"); shift ;;
        --resume)        need_value $# "$1"; RESUME_ID="$2"; CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --resume=*)      RESUME_ID="${1#*=}"; CHILD_ARGS+=("$1"); shift ;;
        --run-id)        need_value $# "$1"; RUN_ID="$2"; CHILD_ARGS+=("$1" "$2"); shift 2 ;;
        --run-id=*)      RUN_ID="${1#*=}"; CHILD_ARGS+=("$1"); shift ;;
        --detach)        DETACH=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *)               die "unknown argument: $1" ;;
    esac
done

# --role and --repo are required on both paths: together they say which state
# directory this invocation lives in, and --resume needs to find it.
[ -n "$ROLE" ] || { usage; die "--role is required"; }
[ -n "$REPO" ] || { usage; die "--repo is required"; }
SANDBOX="$(role_sandbox "$ROLE")" || \
    die "unknown role: $ROLE (plan-reviewer|implementer|code-reviewer|advisor)"
[ -d "$REPO" ] || die "repo root is not a directory: $REPO"
REPO_ABS="$(abs_dir "$REPO")" || die "cannot resolve repo root: $REPO"

case "$HEARTBEAT_SECONDS" in
    ''|*[!0-9]*) die "CLODEX_HEARTBEAT_SECONDS must be a whole number of seconds" ;;
esac

STATE_ROOT="${CLODEX_RUNNER_STATE_DIR:-$REPO_ABS/.clodex/runner}"
[ -n "$RUN_ID" ] && STATE_ROOT="$STATE_ROOT/$RUN_ID"
STATE_DIR="$STATE_ROOT/$ROLE"

# A resume is checked against the recorded invocation BEFORE anything is
# created: a mistyped --repo or --role must not leave an empty state directory
# behind in a repo it does not belong to.
if [ -n "$RESUME_ID" ]; then
    META_FILE="$STATE_DIR/$RESUME_ID.meta"
    [ -f "$META_FILE" ] || die "no recorded $ROLE invocation $RESUME_ID in $STATE_DIR" 1
    META_REPO="$(meta_get repo "$META_FILE")"
    [ "$META_REPO" = "$REPO_ABS" ] || \
        die "$RESUME_ID ran against $META_REPO, not $REPO_ABS" 1
    # `--resume <id>` works alone: the original prompt path was recorded in
    # the meta, so nobody has to read this script's source mid-run to learn
    # that a bare resume is rc=64.
    if [ -z "$PROMPT_FILE" ]; then
        PROMPT_FILE="$(meta_get prompt_file "$META_FILE")"
        [ -n "$PROMPT_FILE" ] || \
            die "--prompt-file is required: $RESUME_ID predates the recorded prompt path"
    fi
fi

[ -n "$PROMPT_FILE" ] || { usage; die "--prompt-file is required"; }
[ -f "$PROMPT_FILE" ] || die "prompt file not found: $PROMPT_FILE"
[ -s "$PROMPT_FILE" ] || die "prompt file is empty: $PROMPT_FILE"
PROMPT_FILE="$(abs_file "$PROMPT_FILE")" || die "cannot resolve prompt file: $PROMPT_FILE"

mkdir -p "$STATE_DIR"
STATE_DIR="$(abs_dir "$STATE_DIR")" || die "cannot resolve state dir: $STATE_ROOT/$ROLE"

if [ -n "$RESUME_ID" ]; then
    INVOCATION_ID="$RESUME_ID"
    META_FILE="$STATE_DIR/$INVOCATION_ID.meta"
    MODEL="${CODEX_MODEL:-$(meta_get model "$META_FILE")}"
    EFFORT="${CODEX_EFFORT:-$(meta_get effort "$META_FILE")}"
    SANDBOX="$(meta_get sandbox "$META_FILE")"
    RESUMED=1
else
    MODEL="$(role_model "$ROLE")"
    EFFORT="${CODEX_EFFORT:-xhigh}"
    # A detaching parent mints the id and hands it down, so the caller learns
    # the log path before the work has even started.
    INVOCATION_ID="${CLODEX_INVOCATION_ID:-$ROLE-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')}"
    META_FILE="$STATE_DIR/$INVOCATION_ID.meta"
    RESUMED=0
fi

ENVELOPE_FILE="$STATE_DIR/$INVOCATION_ID.envelope.json"
EVENTS_FILE="$STATE_DIR/$INVOCATION_ID.events.ndjson"
STDERR_FILE="$STATE_DIR/$INVOCATION_ID.stderr.log"
RUNNER_LOG="$STATE_DIR/$INVOCATION_ID.runner.log"
MODEL_REPORT_FILE="$STATE_DIR/$INVOCATION_ID.model.json"
MODEL_SCHEMA_FILE="$STATE_DIR/$INVOCATION_ID.model-schema.json"
SESSION_FILE="$STATE_DIR/$INVOCATION_ID.session"
INPUTS_FILE="$STATE_DIR/$INVOCATION_ID.inputs"

# Printed verbatim when a run does not finish. Shell-quoted so it can be
# pasted and run as-is, whatever the paths look like. (`--resume <id>` alone
# would also work now; the explicit form survives a lost meta file.)
RESUME_COMMAND="$(printf '%q --role %q --repo %q --resume %q --prompt-file %q' \
    "$RUNNER_DIR/run-codex.sh" "$ROLE" "$REPO_ABS" "$INVOCATION_ID" "$PROMPT_FILE")"
if [ -n "$RUN_ID" ]; then
    RESUME_COMMAND="$RESUME_COMMAND $(printf -- '--run-id %q' "$RUN_ID")"
fi

# Best-effort narration: the runner log is plain-file, so these cannot die on
# a closed pipe; the mirrored stderr copy is what an attached caller sees.
note() {
    printf '%s\n' "$1" >> "$RUNNER_LOG" 2>/dev/null || true
    printf '%s\n' "$1" >&2 || true
}

if [ "$DETACH" -eq 1 ]; then
    # Launch the whole invocation nohup'd with this id, tell the caller how to
    # watch it, and get out of the way. The child writes the same runner log.
    CLODEX_INVOCATION_ID="$INVOCATION_ID" nohup bash "$0" ${CHILD_ARGS[@]+"${CHILD_ARGS[@]}"} \
        < /dev/null >> "$RUNNER_LOG" 2>&1 &
    printf 'detached %s pid %s log %s\n' "$INVOCATION_ID" "$!" "$RUNNER_LOG" || true
    exit 0
fi

# --------------------------------------------------------------------------- #
# inputs and the model-authored sub-schema
# --------------------------------------------------------------------------- #

declare_inputs() {
    local path
    printf '%s\n' "$PROMPT_FILE"
    for path in ${INPUTS[@]+"${INPUTS[@]}"}; do
        [ -f "$path" ] || die "input artifact not found: $path"
        abs_file "$path" || die "cannot resolve input artifact: $path"
    done
    if [ "$RESUMED" -eq 1 ] && [ -f "$INPUTS_FILE" ]; then
        cat "$INPUTS_FILE"
    fi
}

DECLARED_INPUTS="$(declare_inputs)"
printf '%s\n' "$DECLARED_INPUTS" > "$INPUTS_FILE"

python3 "$ENVELOPE_TOOL" model-schema --out "$MODEL_SCHEMA_FILE" || \
    die "cannot export the model output schema" 1

# A leftover report from an earlier turn must never be read as this turn's.
rm -f "$MODEL_REPORT_FILE"

# --------------------------------------------------------------------------- #
# run codex
# --------------------------------------------------------------------------- #

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
INTERRUPTED=0
CODEX_PID=""
HEARTBEAT_PID=""

# What codex was doing when we last looked. Cheap on purpose: this runs once a
# heartbeat, and a missing or half-written event line just reads as unknown.
last_event_kind() {
    local kind
    kind="$(tail -1 "$EVENTS_FILE" 2>/dev/null |
            sed -n 's/.*"type"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    printf '%s' "${kind:-no events yet}"
}

# Still running, as opposed to gone or reaped-but-not-yet-collected. `kill -0`
# alone says yes to a zombie, which would buy one bogus tick after codex exits.
process_alive() {
    local state
    state="$(ps -o state= -p "$1" 2>/dev/null || true)"
    case "$state" in
        ''|Z*) return 1 ;;
        *)     return 0 ;;
    esac
}

# A stalled run and a slow one look identical without this. The tick goes to
# the runner LOG, never stdout or stderr: a heartbeat aimed at a consumer that
# went away is a write to a dead pipe, and that once killed a 27-minute round.
#
# The ticker owns its sleep instead of running it in the foreground. A killed
# ticker used to leave that `sleep` orphaned, and the orphan kept the fds it
# inherited — so a caller capturing the runner's stdout (which is how every
# clodex skill reads the status line) waited for the sleep, not for the run.
# Here the sleep is a child the TERM handler can kill, and the ticker gives up
# the caller's stdout and stderr the moment it starts.
start_heartbeat() {
    [ "$HEARTBEAT_SECONDS" -gt 0 ] || return 0
    local began
    began="$(date +%s)"
    (
        exec >/dev/null 2>/dev/null
        napping=""
        trap 'if [ -n "$napping" ]; then kill "$napping" 2>/dev/null || true; fi; exit 0' INT TERM
        while :; do
            sleep "$HEARTBEAT_SECONDS" &
            napping=$!
            wait "$napping" || true
            napping=""
            process_alive "$CODEX_PID" || break
            printf 'run-codex.sh: %s still running — %ss elapsed, last event: %s\n' \
                "$INVOCATION_ID" "$(( $(date +%s) - began ))" "$(last_event_kind)" \
                >> "$RUNNER_LOG" 2>/dev/null || true
        done
    ) &
    HEARTBEAT_PID=$!
}

stop_heartbeat() {
    [ -n "$HEARTBEAT_PID" ] || return 0
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
}

on_signal() {
    INTERRUPTED=1
    [ -n "$CODEX_PID" ] && kill -TERM "$CODEX_PID" 2>/dev/null || true
    stop_heartbeat
}
# HUP is in the list because it is exactly how a detached consumer's death
# reaches a still-attached runner — untrapped, it would end this script with
# no envelope and no EXIT trap.
trap on_signal INT TERM HUP QUIT

# The envelope is the one artifact no exit path may skip. Assembled by this
# function exactly once; everything it needs is a global that is valid from
# the moment codex starts.
ENVELOPE_WRITTEN=0
STATUS=""
RC=""
ENDED_AT=""
SESSION_ID=""

build_envelope() {
    [ "$ENVELOPE_WRITTEN" -eq 0 ] || return 0
    [ -n "$ENDED_AT" ] || ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    SESSION_ID="$(extract_session_id "$EVENTS_FILE")"
    if [ -n "$SESSION_ID" ]; then
        printf '%s\n' "$SESSION_ID" > "$SESSION_FILE" 2>/dev/null || true
    fi
    local build_args=(build
        --invocation-id "$INVOCATION_ID"
        --role "$ROLE"
        --exit-code "${RC:-143}"
        --started-at "$STARTED_AT"
        --ended-at "$ENDED_AT"
        --model "$MODEL"
        --effort "$EFFORT"
        --sandbox "$SANDBOX"
        --session-id "$SESSION_ID"
        --events "$EVENTS_FILE"
        --stderr "$STDERR_FILE"
        --model-report "$MODEL_REPORT_FILE"
        --state-dir "$STATE_DIR"
        --out "$ENVELOPE_FILE")
    if [ "$INTERRUPTED" -eq 1 ]; then build_args+=(--interrupted); fi
    if [ "$RESUMED" -eq 1 ]; then build_args+=(--resumed); fi
    local declared
    while IFS= read -r declared; do
        [ -n "$declared" ] || continue
        build_args+=(--input "$declared")
    done <<< "$DECLARED_INPUTS"
    STATUS="$(python3 "$ENVELOPE_TOOL" "${build_args[@]}")" || return 1
    ENVELOPE_WRITTEN=1
}

on_exit() {
    stop_heartbeat
    if [ -n "$CODEX_PID" ] && [ "$ENVELOPE_WRITTEN" -eq 0 ]; then
        # The runner is dying by a route the straight-line code never reaches
        # — a set -e failure, an untrapped signal's EXIT, a dead pipe. Codex
        # started, so an envelope is owed; write it as interrupted so the
        # round is resumable rather than lost.
        if process_alive "$CODEX_PID"; then
            kill -TERM "$CODEX_PID" 2>/dev/null || true
        fi
        INTERRUPTED=1
        if build_envelope 2>> "$RUNNER_LOG"; then
            {
                printf '%s %s\n' "$STATUS" "$ENVELOPE_FILE"
                printf 'resume with:\n  %s\n' "$RESUME_COMMAND"
            } >> "$RUNNER_LOG" 2>/dev/null || true
        fi
    fi
}
trap on_exit EXIT

cd "$REPO_ABS" || die "repo root is not reachable: $REPO_ABS" 1

if [ "$RESUMED" -eq 1 ]; then
    SESSION_ID="$(cat "$SESSION_FILE" 2>/dev/null || true)"
    [ -n "$SESSION_ID" ] || SESSION_ID="$(extract_session_id "$EVENTS_FILE")"
    [ -n "$SESSION_ID" ] || die "no codex session id recorded for $INVOCATION_ID" 1
    printf '%s\n' "$SESSION_ID" > "$SESSION_FILE"
    # `codex exec resume` has no -C/--sandbox/--color: it inherits the original
    # session's sandbox, and the cd above anchors it to the repo.
    codex exec resume "$SESSION_ID" \
        --json \
        --skip-git-repo-check \
        -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" \
        --output-schema "$MODEL_SCHEMA_FILE" \
        -o "$MODEL_REPORT_FILE" \
        - \
        < "$PROMPT_FILE" >> "$EVENTS_FILE" 2>> "$STDERR_FILE" &
    CODEX_PID=$!
else
    {
        printf 'role=%s\n' "$ROLE"
        printf 'repo=%s\n' "$REPO_ABS"
        printf 'model=%s\n' "$MODEL"
        printf 'effort=%s\n' "$EFFORT"
        printf 'sandbox=%s\n' "$SANDBOX"
        printf 'prompt_file=%s\n' "$PROMPT_FILE"
        printf 'created_at=%s\n' "$STARTED_AT"
    } > "$META_FILE"
    codex exec \
        --json \
        --skip-git-repo-check \
        --sandbox "$SANDBOX" \
        --color never \
        -C "$REPO_ABS" \
        -m "$MODEL" \
        -c model_reasoning_effort="$EFFORT" \
        --output-schema "$MODEL_SCHEMA_FILE" \
        -o "$MODEL_REPORT_FILE" \
        - \
        < "$PROMPT_FILE" > "$EVENTS_FILE" 2> "$STDERR_FILE" &
    CODEX_PID=$!
fi

start_heartbeat

RC=0
wait "$CODEX_PID" || RC=$?
trap - INT TERM HUP QUIT
stop_heartbeat
wait "$CODEX_PID" 2>/dev/null || true
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --------------------------------------------------------------------------- #
# the envelope decides
# --------------------------------------------------------------------------- #

build_envelope || die "could not write a result envelope for $INVOCATION_ID" 1

printf '%s %s\n' "$STATUS" "$ENVELOPE_FILE" || true

case "$STATUS" in
    complete)
        exit 0
        ;;
    partial)
        note "run-codex.sh: $INVOCATION_ID stopped short of finishing (status partial)"
        note "resume with:"
        note "  $RESUME_COMMAND"
        exit 2
        ;;
    interrupted)
        note "run-codex.sh: $INVOCATION_ID was interrupted (exit $RC)"
        note "resume with:"
        note "  $RESUME_COMMAND"
        exit 3
        ;;
    *)
        note "run-codex.sh: $INVOCATION_ID failed (codex exit $RC)"
        if [ -s "$STDERR_FILE" ]; then
            { printf '            codex stderr (tail):\n'
              tail -10 "$STDERR_FILE"; } >&2 || true
        fi
        exit 1
        ;;
esac
