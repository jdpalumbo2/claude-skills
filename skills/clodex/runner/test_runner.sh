#!/usr/bin/env bash
# Tests for the clodex Codex runner.
#
# The real `codex` is never invoked: a stub binary is put first on PATH for the
# life of this process only, and everything the tests write lives under one
# temp dir that is removed on exit.
#
# Usage: ./test_runner.sh      # exit 0 only if every case passes

set -euo pipefail

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$RUNNER_DIR/run-codex.sh"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/clodex-runner-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

REPO="$TMP/repo"
ELSEWHERE="$TMP/elsewhere"
BIN="$TMP/bin"
mkdir -p "$REPO" "$ELSEWHERE" "$BIN"

FAILURES=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n        %s\n' "$1" "$2"; FAILURES=$((FAILURES + 1)); }

# Read a dotted path out of a JSON file. Strings print bare, everything else
# prints as JSON (so booleans read `true`, not `True`).
json_get() {
    python3 - "$1" "$2" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    value = value[int(key)] if isinstance(value, list) else value[key]
print(value if isinstance(value, str) else json.dumps(value))
PY
}

# The single *.envelope.json in a state dir (fails if there is not exactly one).
sole_envelope() {
    local state="$1" found=""
    local f
    for f in "$state"/*.envelope.json; do
        [ -f "$f" ] || continue
        [ -z "$found" ] || return 1
        found="$f"
    done
    [ -n "$found" ] || return 1
    printf '%s\n' "$found"
}

# ---------------------------------------------------------------------------
# the stub codex
# ---------------------------------------------------------------------------
cat > "$BIN/codex" <<'STUB'
#!/usr/bin/env bash
# Stand-in for the real `codex` binary. Records its argv, its working
# directory and everything it was given on stdin, then behaves as $STUB_MODE
# says. Writes nothing outside $STUB_LOG_DIR and the -o target.
set -uo pipefail

log="${STUB_LOG_DIR:?STUB_LOG_DIR is not set}"
mkdir -p "$log"

: > "$log/argv"
for arg in "$@"; do printf '%s\n' "$arg" >> "$log/argv"; done
pwd -P > "$log/cwd"
cat > "$log/stdin"

out=""
prev=""
for arg in "$@"; do
    case "$prev" in
        -o|--output-last-message) out="$arg" ;;
    esac
    prev="$arg"
done

printf '{"type":"thread.started","thread_id":"%s"}\n' "${STUB_SESSION_ID:-stub-session-0001}"

case "${STUB_MODE:-complete}" in
    hang)
        sleep "${STUB_HANG_SECONDS:-10}"
        exit 0
        ;;
    no-envelope)
        exit 0
        ;;
    partial)
        printf '%s\n' '{"status":"partial","summary":"stub ran out of room","findings":[{"severity":"high","summary":"stub finding","detail":"stub detail","location":"stub.py:1"}]}' > "$out"
        ;;
    *)
        printf '%s\n' '{"status":"complete","summary":"stub done","findings":[]}' > "$out"
        ;;
esac
exit 0
STUB
chmod +x "$BIN/codex"
export PATH="$BIN:$PATH"

# ---------------------------------------------------------------------------
# (a) the prompt travels by file, never as an argument
# ---------------------------------------------------------------------------
case_a() {
    local name="a  prompt transported by file, never inline in argv"
    local log="$TMP/log/a" state="$TMP/state/a" prompt="$TMP/prompt-a.md"
    local marker="CLODEX_PROMPT_MARKER_A7F3"
    printf 'Review the plan.\n%s\n' "$marker" > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/a.out" 2> "$TMP/a.err" || rc=$?

    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/a.err" | tr '\n' ' ')"
        return
    fi
    if [ ! -f "$log/stdin" ]; then
        fail "$name" "stub recorded no stdin"
        return
    fi
    if ! grep -q "$marker" "$log/stdin"; then
        fail "$name" "prompt did not reach codex on stdin"
        return
    fi
    if grep -q "$marker" "$log/argv"; then
        fail "$name" "prompt text appeared in codex argv: $(grep -n "$marker" "$log/argv" | head -1)"
        return
    fi
    if ! grep -qx -- '-' "$log/argv"; then
        fail "$name" "codex was not told to read the prompt from stdin (no '-' positional)"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (b) codex runs in --repo no matter where the caller stood
# ---------------------------------------------------------------------------
case_b() {
    local name="b  codex runs in --repo regardless of caller cwd"
    local log="$TMP/log/b" state="$TMP/state/b" prompt="$TMP/prompt-b.md"
    printf 'Review the plan.\n' > "$prompt"
    local expected
    expected="$(cd "$REPO" && pwd -P)"

    local rc=0
    ( cd "$ELSEWHERE" && \
      STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --role code-reviewer --repo "$REPO" --prompt-file "$prompt" ) \
        > "$TMP/b.out" 2> "$TMP/b.err" || rc=$?

    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/b.err" | tr '\n' ' ')"
        return
    fi
    local actual
    actual="$(cat "$log/cwd" 2>/dev/null || true)"
    if [ "$actual" != "$expected" ]; then
        fail "$name" "codex ran in '$actual', expected '$expected'"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (c) a model that reports partial yields a partial envelope and a non-zero exit
# ---------------------------------------------------------------------------
case_c() {
    local name="c  model reports partial => envelope status partial, exit non-zero"
    local log="$TMP/log/c" state="$TMP/state/c" prompt="$TMP/prompt-c.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=partial \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/c.out" 2> "$TMP/c.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 on a partial result"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "no single envelope in $state"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "partial" ]; then
        fail "$name" "envelope status is '$status', expected 'partial'"
        return
    fi
    local fid
    fid="$(json_get "$env" findings.0.id)"
    if [ -z "$fid" ]; then
        fail "$name" "finding carries no id"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (d) kill mid-run, then --resume: same invocation id, resumes the session
# ---------------------------------------------------------------------------
case_d() {
    local name="d  killed mid-run then --resume => same invocation id, continues session"
    local state="$TMP/state/d" prompt="$TMP/prompt-d.md"
    local log_start="$TMP/log/d-start" log_resume="$TMP/log/d-resume"
    local session="stub-session-D42"
    printf 'Implement the batch.\n' > "$prompt"

    STUB_LOG_DIR="$log_start" CLODEX_RUNNER_STATE_DIR="$state" \
    STUB_MODE=hang STUB_HANG_SECONDS=10 STUB_SESSION_ID="$session" \
        "$RUNNER" --role implementer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/d1.out" 2> "$TMP/d1.err" &
    local runner_pid=$!

    # Wait until codex has really started and emitted its session id.
    local i started=""
    for i in $(seq 1 100); do
        local f
        for f in "$state"/*.events.ndjson; do
            [ -f "$f" ] || continue
            if grep -q 'thread.started' "$f" 2>/dev/null; then started="$f"; break; fi
        done
        [ -z "$started" ] || break
        sleep 0.1
    done
    if [ -z "$started" ]; then
        kill -KILL "$runner_pid" 2>/dev/null || true
        wait "$runner_pid" 2>/dev/null || true
        fail "$name" "codex never started (no events file with thread.started)"
        return
    fi

    kill -TERM "$runner_pid" 2>/dev/null || true
    local rc=0
    wait "$runner_pid" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 after being killed"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "no single envelope after the kill"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "interrupted" ]; then
        fail "$name" "envelope status after kill is '$status', expected 'interrupted'"
        return
    fi
    local id
    id="$(json_get "$env" invocation_id)"
    if [ ! -f "$state/$id.session" ] || ! grep -q "$session" "$state/$id.session"; then
        fail "$name" "session id was not checkpointed to $state/$id.session"
        return
    fi

    rc=0
    STUB_LOG_DIR="$log_resume" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --resume "$id" --prompt-file "$prompt" \
        > "$TMP/d2.out" 2> "$TMP/d2.err" || rc=$?

    if [ "$rc" -ne 0 ]; then
        fail "$name" "resume exited $rc; stderr: $(tail -3 "$TMP/d2.err" | tr '\n' ' ')"
        return
    fi
    if ! grep -qx 'resume' "$log_resume/argv"; then
        fail "$name" "resume did not call 'codex exec resume': $(tr '\n' ' ' < "$log_resume/argv")"
        return
    fi
    if ! grep -qx "$session" "$log_resume/argv"; then
        fail "$name" "resume did not pass the checkpointed session id"
        return
    fi
    local env2
    env2="$(sole_envelope "$state")" || { fail "$name" "resume did not reuse the invocation's state dir"; return; }
    if [ "$(json_get "$env2" invocation_id)" != "$id" ]; then
        fail "$name" "resume wrote a different invocation id"
        return
    fi
    if [ "$(json_get "$env2" status)" != "complete" ]; then
        fail "$name" "resumed envelope status is '$(json_get "$env2" status)', expected 'complete'"
        return
    fi
    if [ "$(json_get "$env2" codex.resumed)" != "true" ]; then
        fail "$name" "resumed envelope does not record codex.resumed = true"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (e) codex writes no envelope => fail closed
# ---------------------------------------------------------------------------
case_e() {
    local name="e  no envelope from codex => exit non-zero, envelope failed"
    local log="$TMP/log/e" state="$TMP/state/e" prompt="$TMP/prompt-e.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=no-envelope \
        "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/e.out" 2> "$TMP/e.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 with no result envelope from codex"
        return
    fi
    if ! grep -qi 'envelope' "$TMP/e.err"; then
        fail "$name" "stderr does not say the envelope is missing: $(tail -3 "$TMP/e.err" | tr '\n' ' ')"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "runner recorded no envelope of its own"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "failed" ]; then
        fail "$name" "envelope status is '$status', expected 'failed'"
        return
    fi
    pass "$name"
}

case_a
case_b
case_c
case_d
case_e

printf '\n'
if [ "$FAILURES" -ne 0 ]; then
    printf '%d case(s) failed\n' "$FAILURES"
    exit 1
fi
printf 'all cases passed\n'
