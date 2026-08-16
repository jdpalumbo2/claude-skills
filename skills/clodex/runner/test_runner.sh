#!/usr/bin/env bash
# Tests for the clodex Codex runner.
#
# The real `codex` is never invoked: a stub binary is put first on PATH for the
# life of this process only — and the suite refuses to run unless it verifies
# that the stub really shadows the real binary. Everything the tests write
# lives under one temp dir that is removed on exit.
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

# The single *.envelope.json under a state root (state is per-role, so the
# envelopes live one level down). Fails if there is not exactly one.
sole_envelope() {
    local root="$1" found="" f
    for f in "$root"/*/*.envelope.json; do
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

complete_report='{"status":"complete","summary":"stub done","findings":[]}'

printf '{"type":"thread.started","thread_id":"%s"}\n' "${STUB_SESSION_ID:-stub-session-0001}"

case "${STUB_MODE:-complete}" in
    hang)
        sleep "${STUB_HANG_SECONDS:-10}"
        exit 0
        ;;
    slow)
        sleep "${STUB_SLOW_SECONDS:-3}"
        printf '%s\n' "$complete_report" > "$out"
        ;;
    no-envelope)
        exit 0
        ;;
    complete-nested-session)
        # A resume that mints a NEW session id, reported deeper in the event
        # shape than the opening line: inside an array, inside an object.
        printf '{"type":"thread.resumed","payload":{"sessions":[{"session_id":"%s"}]}}\n' \
            "${STUB_RESUMED_SESSION_ID:?}"
        printf '%s\n' "$complete_report" > "$out"
        ;;
    complete-nonzero)
        # The dangerous shape: a model claiming success while codex itself
        # fails (quota, sandbox denial, crash after the last message).
        printf '%s\n' "$complete_report" > "$out"
        printf 'codex: stream disconnected before completion\n' >&2
        exit "${STUB_EXIT_CODE:-4}"
        ;;
    extra-key)
        # Well-formed JSON claiming success, but not the shape the runner asked
        # for — a model wandering off the output schema it was given.
        printf '%s\n' '{"status":"complete","summary":"done","findings":[],"notes":"chatty extra key"}' > "$out"
        ;;
    partial)
        printf '%s\n' '{"status":"partial","summary":"stub ran out of room","findings":[{"severity":"high","summary":"stub finding","detail":"stub detail","location":"stub.py:1"}]}' > "$out"
        ;;
    *)
        printf '%s\n' "$complete_report" > "$out"
        ;;
esac
exit 0
STUB
chmod +x "$BIN/codex"
export PATH="$BIN:$PATH"
[ "$(command -v codex)" = "$BIN/codex" ] || {
    printf 'stub codex is not first on PATH (%s) — refusing to run against the real binary\n' \
        "$(command -v codex || true)" >&2
    exit 1
}

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
# (b) codex is anchored to --repo no matter where the caller stood
# ---------------------------------------------------------------------------
case_b() {
    local name="b  codex anchored to --repo (cd + -C) regardless of caller cwd"
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
    # The cd is what the cwd check proves; -C is the second anchor, asserted
    # separately so removing it cannot pass unnoticed.
    if ! grep -qx -- '-C' "$log/argv" || ! grep -qx "$expected" "$log/argv"; then
        fail "$name" "codex was not given -C $expected"
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
        for f in "$state"/*/*.events.ndjson; do
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
    local id role_dir
    id="$(json_get "$env" invocation_id)"
    role_dir="$(dirname "$env")"
    if [ ! -f "$role_dir/$id.session" ] || ! grep -q "$session" "$role_dir/$id.session"; then
        fail "$name" "session id was not checkpointed to $role_dir/$id.session"
        return
    fi

    # Resume by running the exact command the interrupted run printed — the
    # spec asks for a one-command resume, so the printed line must be runnable.
    local resume_cmd
    resume_cmd="$(sed -n '/^resume with:/{n;s/^ *//;p;}' "$TMP/d1.err")"
    if [ -z "$resume_cmd" ]; then
        fail "$name" "interrupted run printed no resume command: $(tr '\n' ' ' < "$TMP/d1.err")"
        return
    fi
    case "$resume_cmd" in
        *'<'*'>'*) fail "$name" "resume command is a placeholder, not runnable: $resume_cmd"; return ;;
    esac

    rc=0
    STUB_LOG_DIR="$log_resume" CLODEX_RUNNER_STATE_DIR="$state" \
    STUB_MODE=complete-nested-session STUB_RESUMED_SESSION_ID="$session-second" \
        eval "$resume_cmd" > "$TMP/d2.out" 2> "$TMP/d2.err" || rc=$?

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
    # The resume minted a new session id, nested inside an array. A further
    # resume must continue from THAT one, so it has to be what got checkpointed
    # and what the envelope reports.
    if ! grep -qx "$session-second" "$role_dir/$id.session"; then
        fail "$name" "checkpoint still holds '$(cat "$role_dir/$id.session")', expected $session-second"
        return
    fi
    if [ "$(json_get "$env2" codex.session_id)" != "$session-second" ]; then
        fail "$name" "envelope reports a stale session id: $(json_get "$env2" codex.session_id)"
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

# ---------------------------------------------------------------------------
# (f) the model claims success but codex failed => the process wins
# ---------------------------------------------------------------------------
case_f() {
    local name="f  model says complete but codex exits non-zero => failed, exit non-zero"
    local log="$TMP/log/f" state="$TMP/state/f" prompt="$TMP/prompt-f.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" \
    STUB_MODE=complete-nonzero STUB_EXIT_CODE=4 \
        "$RUNNER" --role code-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/f.out" 2> "$TMP/f.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 although codex exited 4"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "no single envelope in $state"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "failed" ]; then
        fail "$name" "envelope status is '$status', expected 'failed'"
        return
    fi
    # The model's own claim is preserved for auditing, but it did not decide.
    if [ "$(json_get "$env" model_status)" != "complete" ]; then
        fail "$name" "the model's own claim was not preserved in model_status"
        return
    fi
    if [ "$(json_get "$env" exit.code)" != "4" ]; then
        fail "$name" "envelope did not record codex's exit code"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (g) a long run heartbeats to its runner LOG — never stdout or stderr — and
#     the ticker dies with the run
# ---------------------------------------------------------------------------
case_g() {
    local name="g  long run heartbeats to the runner log only; ticker dies with the run"
    local log="$TMP/log/g" state="$TMP/state/g" prompt="$TMP/prompt-g.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" \
    STUB_MODE=slow STUB_SLOW_SECONDS=3 CLODEX_HEARTBEAT_SECONDS=1 \
        "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/g.out" 2> "$TMP/g.err" || rc=$?

    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/g.err" | tr '\n' ' ')"
        return
    fi
    local runner_log
    runner_log="$(ls "$state"/*/*.runner.log 2>/dev/null | head -1 || true)"
    if [ -z "$runner_log" ]; then
        fail "$name" "no runner log was written under $state"
        return
    fi
    local ticks
    ticks="$(grep -c 'still running' "$runner_log" || true)"
    if [ "$ticks" -lt 2 ]; then
        fail "$name" "expected repeated heartbeats in the runner log, saw $ticks"
        return
    fi
    if ! grep -q 'last event:' "$runner_log"; then
        fail "$name" "heartbeat does not report the last observed event"
        return
    fi
    # A consumer that went away must have nothing to be killed by: heartbeats
    # reach neither stdout nor stderr.
    if grep -q 'still running' "$TMP/g.out" "$TMP/g.err" 2>/dev/null; then
        fail "$name" "heartbeats leaked to stdout/stderr"
        return
    fi
    if [ "$(wc -l < "$TMP/g.out" | tr -d ' ')" != "1" ]; then
        fail "$name" "stdout is not exactly the status line: $(tr '\n' ' ' < "$TMP/g.out")"
        return
    fi
    # A ticker that outlived the run would keep writing after the runner exited.
    local before after
    before="$(wc -l < "$runner_log" | tr -d ' ')"
    sleep 2
    after="$(wc -l < "$runner_log" | tr -d ' ')"
    if [ "$before" != "$after" ]; then
        fail "$name" "the heartbeat ticker outlived the run ($before -> $after lines)"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (h) state belongs to the repo being worked on, not to this catalogue
# ---------------------------------------------------------------------------
case_h() {
    local name="h  default state dir is <repo>/.clodex/runner/<role>"
    local log="$TMP/log/h" prompt="$TMP/prompt-h.md" repo="$TMP/repo-h"
    mkdir -p "$repo"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    env -u CLODEX_RUNNER_STATE_DIR STUB_LOG_DIR="$log" STUB_MODE=complete \
        "$RUNNER" --role plan-reviewer --repo "$repo" --prompt-file "$prompt" \
        > "$TMP/h.out" 2> "$TMP/h.err" || rc=$?

    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/h.err" | tr '\n' ' ')"
        return
    fi
    local env
    env="$(sole_envelope "$repo/.clodex/runner")" || {
        fail "$name" "no envelope under $repo/.clodex/runner"; return; }
    if [ "$(dirname "$env")" != "$repo/.clodex/runner/plan-reviewer" ]; then
        fail "$name" "envelope landed in $(dirname "$env"), expected the plan-reviewer dir"
        return
    fi
    if [ -e "$RUNNER_DIR/state" ]; then
        fail "$name" "the runner wrote state into the catalogue repo: $RUNNER_DIR/state"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (i) a flag with no value is a usage error, not a silent failure
# ---------------------------------------------------------------------------
case_i() {
    local name="i  trailing flag with no value => exit 64 with a message"
    local prompt="$TMP/prompt-i.md" flag rc broken=""
    printf 'Review the plan.\n' > "$prompt"

    for flag in --prompt-file --role --input --repo --resume; do
        rc=0
        STUB_LOG_DIR="$TMP/log/i" CLODEX_RUNNER_STATE_DIR="$TMP/state/i" STUB_MODE=complete \
            "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" "$flag" \
            > /dev/null 2> "$TMP/i.err" || rc=$?
        if [ "$rc" -ne 64 ]; then
            broken="$flag exited $rc, expected 64"
            break
        fi
        if [ ! -s "$TMP/i.err" ]; then
            broken="$flag failed silently — nothing on stderr"
            break
        fi
    done
    if [ -n "$broken" ]; then
        fail "$name" "$broken"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (j) a resume that produces nothing must not inherit the last turn's report
# ---------------------------------------------------------------------------
case_j() {
    local name="j  resume with no new report => failed, never the previous turn's"
    local state="$TMP/state/j" prompt="$TMP/prompt-j.md"
    local log_one="$TMP/log/j-1" log_two="$TMP/log/j-2"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log_one" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/j1.out" 2> "$TMP/j1.err" || rc=$?
    if [ "$rc" -ne 0 ]; then
        fail "$name" "first turn exited $rc; stderr: $(tail -3 "$TMP/j1.err" | tr '\n' ' ')"
        return
    fi
    local env id
    env="$(sole_envelope "$state")" || { fail "$name" "no envelope from the first turn"; return; }
    id="$(json_get "$env" invocation_id)"

    rc=0
    STUB_LOG_DIR="$log_two" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=no-envelope \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --resume "$id" --prompt-file "$prompt" \
        > "$TMP/j2.out" 2> "$TMP/j2.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "resume exited 0 while writing no report of its own"
        return
    fi
    env="$(sole_envelope "$state")" || { fail "$name" "no envelope after the resume"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "failed" ]; then
        fail "$name" "resume envelope is '$status' — it inherited the first turn's report"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (k) capturing the runner's stdout must not wait on the heartbeat
# ---------------------------------------------------------------------------
case_k() {
    local name="k  a caller capturing stdout gets the status line without stalling"
    local log="$TMP/log/k" state="$TMP/state/k" prompt="$TMP/prompt-k.md"
    printf 'Review the plan.\n' > "$prompt"

    # Command substitution keeps reading until every process holding the write
    # end of the pipe is gone — a heartbeat sleep that outlives the run holds
    # it, and no amount of file-redirected output would show that.
    local began ended elapsed result rc=0
    began="$(date +%s)"
    result="$(STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" \
              STUB_MODE=slow STUB_SLOW_SECONDS=1 CLODEX_HEARTBEAT_SECONDS=15 \
              "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" \
              2> "$TMP/k.err")" || rc=$?
    ended="$(date +%s)"
    elapsed=$((ended - began))

    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/k.err" | tr '\n' ' ')"
        return
    fi
    if [ "$elapsed" -ge 10 ]; then
        fail "$name" "capturing stdout took ${elapsed}s for a ~1s run — something still holds the caller's pipe open"
        return
    fi
    case "$result" in
        'complete '/*) ;;
        *) fail "$name" "expected a 'complete <path>' status line, got: $result"; return ;;
    esac
    pass "$name"
}

# ---------------------------------------------------------------------------
# (l) a model report that drifts off the output schema is not a result
# ---------------------------------------------------------------------------
case_l() {
    local name="l  model report off the output schema => failed, exit non-zero"
    local log="$TMP/log/l" state="$TMP/state/l" prompt="$TMP/prompt-l.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=extra-key \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/l.out" 2> "$TMP/l.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 on a report that does not match the schema"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "no single envelope in $state"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "failed" ]; then
        fail "$name" "envelope status is '$status', expected 'failed'"
        return
    fi
    if ! json_get "$env" error | grep -qi 'schema'; then
        fail "$name" "envelope does not record why it failed: $(json_get "$env" error)"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (m) a rejected resume must not touch the repo it was pointed at
# ---------------------------------------------------------------------------
case_m() {
    local name="m  a rejected resume creates nothing in the repo it named"
    local log="$TMP/log/m" prompt="$TMP/prompt-m.md" repo="$TMP/repo-m"
    mkdir -p "$repo"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    env -u CLODEX_RUNNER_STATE_DIR STUB_LOG_DIR="$log" STUB_MODE=complete \
        "$RUNNER" --role advisor --repo "$repo" \
        --resume advisor-19990101T000000Z-aaaaaa --prompt-file "$prompt" \
        > /dev/null 2> "$TMP/m.err" || rc=$?

    if [ "$rc" -eq 0 ]; then
        fail "$name" "resuming an invocation that does not exist exited 0"
        return
    fi
    if [ -e "$repo/.clodex" ]; then
        fail "$name" "the rejected resume created $repo/.clodex"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (n) a death mode with no straight-line exit still writes an envelope —
#     SIGHUP is how a detached consumer's death reaches the runner
# ---------------------------------------------------------------------------
case_n() {
    local name="n  SIGHUP mid-run => interrupted envelope written, resume line in the log"
    local log="$TMP/log/n" state="$TMP/state/n" prompt="$TMP/prompt-n.md"
    printf 'Implement the batch.\n' > "$prompt"

    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" \
    STUB_MODE=hang STUB_HANG_SECONDS=10 \
        "$RUNNER" --role implementer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/n.out" 2> "$TMP/n.err" &
    local runner_pid=$!

    local i started=""
    for i in $(seq 1 100); do
        local f
        for f in "$state"/*/*.events.ndjson; do
            [ -f "$f" ] || continue
            if grep -q 'thread.started' "$f" 2>/dev/null; then started="$f"; break; fi
        done
        [ -z "$started" ] || break
        sleep 0.1
    done
    if [ -z "$started" ]; then
        kill -KILL "$runner_pid" 2>/dev/null || true
        wait "$runner_pid" 2>/dev/null || true
        fail "$name" "codex never started"
        return
    fi

    kill -HUP "$runner_pid" 2>/dev/null || true
    local rc=0
    wait "$runner_pid" || rc=$?
    if [ "$rc" -eq 0 ]; then
        fail "$name" "runner exited 0 after SIGHUP"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "SIGHUP lost the envelope"; return; }
    local status
    status="$(json_get "$env" status)"
    if [ "$status" != "interrupted" ]; then
        fail "$name" "envelope status is '$status', expected 'interrupted'"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (o) --detach: immediate return with pid + log, status line lands in the log
# ---------------------------------------------------------------------------
case_o() {
    local name="o  --detach prints pid+log and the log ends with the status line"
    local log="$TMP/log/o" state="$TMP/state/o" prompt="$TMP/prompt-o.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0 out
    out="$(STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" \
           STUB_MODE=slow STUB_SLOW_SECONDS=2 \
           "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" --detach \
           2> "$TMP/o.err")" || rc=$?
    if [ "$rc" -ne 0 ]; then
        fail "$name" "--detach exited $rc; stderr: $(tail -3 "$TMP/o.err" | tr '\n' ' ')"
        return
    fi
    local pid runner_log
    case "$out" in
        detached\ *\ pid\ *\ log\ *) ;;
        *) fail "$name" "unexpected detach line: $out"; return ;;
    esac
    pid="$(printf '%s' "$out" | awk '{print $4}')"
    runner_log="$(printf '%s' "$out" | awk '{print $6}')"

    # The Monitor recipe from the skills: watch the pid AND grep the log for a
    # final status line.
    local i
    for i in $(seq 1 100); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        fail "$name" "detached invocation still running after 10s"
        return
    fi
    if ! grep -Eq '^(complete|partial|interrupted|failed) ' "$runner_log"; then
        fail "$name" "no status line in the runner log: $(tail -3 "$runner_log" | tr '\n' ' ')"
        return
    fi
    local env
    env="$(sole_envelope "$state")" || { fail "$name" "detached run wrote no envelope"; return; }
    if [ "$(json_get "$env" status)" != "complete" ]; then
        fail "$name" "detached envelope is '$(json_get "$env" status)', expected complete"
        return
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (p) --run-id keys the state dir, so two runs never interleave envelopes
# ---------------------------------------------------------------------------
case_p() {
    local name="p  --run-id keys envelope paths by run"
    local log="$TMP/log/p" state="$TMP/state/p" prompt="$TMP/prompt-p.md"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --role advisor --repo "$REPO" --prompt-file "$prompt" \
        --run-id r-2026-08-16-a \
        > "$TMP/p.out" 2> "$TMP/p.err" || rc=$?
    if [ "$rc" -ne 0 ]; then
        fail "$name" "runner exited $rc; stderr: $(tail -3 "$TMP/p.err" | tr '\n' ' ')"
        return
    fi
    local env
    env="$(sole_envelope "$state/r-2026-08-16-a")" || {
        fail "$name" "no envelope under $state/r-2026-08-16-a"; return; }
    case "$env" in
        "$state/r-2026-08-16-a/advisor/"*) ;;
        *) fail "$name" "envelope landed at $env, expected under r-2026-08-16-a/advisor"; return ;;
    esac
    # And the printed resume command carries the run id, or a resume would
    # look in the wrong state dir.
    if ! grep -q 'r-2026-08-16-a' "$TMP/p.out"; then
        # complete runs print no resume line; check the envelope's state_dir
        if [ "$(json_get "$env" output.state_dir)" != "$state/r-2026-08-16-a/advisor" ]; then
            fail "$name" "state_dir not keyed by run id: $(json_get "$env" output.state_dir)"
            return
        fi
    fi
    pass "$name"
}

# ---------------------------------------------------------------------------
# (q) --resume <id> works alone: the prompt path is read back from the meta
# ---------------------------------------------------------------------------
case_q() {
    local name="q  bare --resume works without --prompt-file"
    local state="$TMP/state/q" prompt="$TMP/prompt-q.md"
    local log_one="$TMP/log/q-1" log_two="$TMP/log/q-2"
    printf 'Review the plan.\n' > "$prompt"

    local rc=0
    STUB_LOG_DIR="$log_one" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=partial \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --prompt-file "$prompt" \
        > "$TMP/q1.out" 2> "$TMP/q1.err" || rc=$?
    if [ "$rc" -ne 2 ]; then
        fail "$name" "first turn exited $rc, expected 2 (partial)"
        return
    fi
    local env id
    env="$(sole_envelope "$state")" || { fail "$name" "no envelope from the first turn"; return; }
    id="$(json_get "$env" invocation_id)"

    rc=0
    STUB_LOG_DIR="$log_two" CLODEX_RUNNER_STATE_DIR="$state" STUB_MODE=complete \
        "$RUNNER" --role plan-reviewer --repo "$REPO" --resume "$id" \
        > "$TMP/q2.out" 2> "$TMP/q2.err" || rc=$?
    if [ "$rc" -ne 0 ]; then
        fail "$name" "bare resume exited $rc; stderr: $(tail -3 "$TMP/q2.err" | tr '\n' ' ')"
        return
    fi
    # The prompt really reached codex again, from the recorded path.
    if ! grep -q 'Review the plan.' "$log_two/stdin"; then
        fail "$name" "resume did not feed the recorded prompt to codex"
        return
    fi
    pass "$name"
}

case_a
case_b
case_c
case_d
case_e
case_f
case_g
case_h
case_i
case_j
case_k
case_l
case_m
case_n
case_o
case_p
case_q

printf '\n'
if [ "$FAILURES" -ne 0 ]; then
    printf '%d case(s) failed\n' "$FAILURES"
    exit 1
fi
printf 'all cases passed\n'
