---
name: clodex
description: Use when any development work starts in a repository — a feature request, a dense brief, a bug fix, "continue where we left off", or an ask whose shape is unclear. Also use when a repo has a .clodex/ directory with an unfinished run, and before invoking clodex-plan, clodex-build, clodex-verify, or clodex-ship.
---

# clodex — the front door

## Overview

One entry point for all work, so nobody has to remember stage names. This skill
runs five things in order and then hands off:

1. **Preflight** — prove the environment before a stage burns tokens on it.
2. **Open-run detection** — a run already in flight is resumed, never
   overwritten.
3. **Profile** — load `.clodex/profile.json`, or interview once and write it.
4. **Lane classification** — feature-shaped work enters the core path; every
   other shape is named and handed back, because those lanes are v0.2.
5. **Change boundary** — record what was already dirty, and never let the run
   commit someone else's work.

Then it opens the run and hands to a stage skill.

This skill does not edit code, does not call Codex, and does not run release
actions. The stage skills own all three.

## Paths and commands

```bash
CLODEX_HOME="${CLODEX_HOME:-$HOME/.claude/skills/clodex}"  # the dir holding this SKILL.md
STATE="$CLODEX_HOME/state/clodex_state.py"
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"    # do this, do not just assume it
REMOTE="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null | cut -d/ -f1 || true)"
[ -n "$REMOTE" ] || REMOTE="$(git remote | head -1)"   # empty = this repo has no remote
```

Shell variables do not survive between separate command invocations, so
**re-establish this block at the top of any shell you run these procedures in**.
Later sections use `$REPO`, `$STATE`, and `$REMOTE` as if it were already there.

**Every command below runs from `$REPO`.** `git check-ignore`, the repo
inspection in §3, and `git add` all resolve relative paths against the current
directory, so from a subdirectory they answer the wrong question — a correct
`.gitignore` reads as missing. If a step cannot `cd`, use `git -C "$REPO" …`.

| Thing | Path | Committed? |
|---|---|---|
| Run-state engine | `$STATE` | catalogue |
| Profile schema | `$CLODEX_HOME/profile.schema.json` | catalogue |
| Codex runner (stages only, never here) | `$CLODEX_HOME/runner/run-codex.sh` | catalogue |
| Repo profile | `$REPO/.clodex/profile.json` | **yes** |
| Run directory | `$REPO/.clodex/<run-id>/` (`$RUN_DIR` below) | **no — gitignored** |

A run's state is its directory: `events.ndjson` is an append-only event log and
is **the** record of what happened; `run.json` is a snapshot derived from it by
replaying the log; `lock.json` says which session owns the run; `write.lock`
serializes writes and is not something you reason about. You add to a run only
by appending an event.

Engine commands (payloads travel on **stdin**, never argv):

```bash
python3 "$STATE" status  "$RUN_DIR"          # human summary, incl. the lock line
python3 "$STATE" rebuild "$RUN_DIR"          # full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
python3 "$STATE" unlock  "$RUN_DIR"          # dead holder only; refuses a live one
```

`append` exit codes: `0` written · `1` refused, nothing written, safe to retry ·
`2` usage · `3` the event is durably logged but `run.json` is stale. On `3` the
event **counts** — it is in the log and the reducer applies it — so **do not
retry** (that would double-write). Run `rebuild` to refresh the snapshot and
carry on from the event you just appended.

### Telemetry: two fields any event may carry

The vocabulary is frozen at 23 names, so what happened *around* an event is
recorded as fields on it rather than as events of its own. Both are optional;
a run that never sets them reduces exactly as it would have without them.

- **`preflight`** — `{"status": …, "checks": [{"name", "status", "detail"}]}`.
  Appended to the snapshot's `preflight` list. §1 explains when.
- **`codex`** — one **leg** of a Codex role invocation:
  ```json
  {"codex": {"invocation_id": "plan-reviewer-20260811T134400Z-88b056",
             "role": "plan-reviewer", "round": 4, "status": "complete",
             "envelope": ".clodex/runner/<run-id>/plan-reviewer/<id>.envelope.json",
             "input_hashes": ["<sha256 of each artifact it read>"],
             "duration_s": 501, "resumed": false}}
  ```
  `invocation_id` and `role` are required — a record nothing can be matched to
  would read as evidence that a round happened. Everything comes off the
  envelope the runner already wrote; `input_hashes` is what binds a review to
  the plan version it actually read.

  **A leg, not an invocation.** A resumed round overwrites its own envelope,
  which then reports only the resume — the pilot's envelopes under-reported the
  review by 25% that way. So append one `codex` block for the interrupted leg
  (`"status": "interrupted"`) and another for the resume (`"resumed": true`),
  both with the same `invocation_id`. The legs sum to what the round cost.

Attach a `codex` block to the first event that invocation causes — the finding
it raised, the `batch:reviewed` it produced, the `plan:amended` it forced. A
round that found nothing still gets one: put it on the event its clean result
unlocked (`plan:approved`, `batch:reviewed`), or the log cannot tell "reviewed
clean" from "never reviewed".

**Copied, never estimated.** `duration_s` is the envelope's `exit.duration_ms`
over 1000, and `status` is the envelope's `status` — never a number you
remember, never a state you assert. Estimated durations ran 1.1–1.8× actuals
the first weekend this was tested at scale, and two logs contradicted their
envelopes' status outright. And because the attach discipline itself fails
under load — seven completed invocations went unrecorded that same weekend —
every stage reconciles at its exit step:

```bash
python3 "$STATE" telemetry-sync "$RUN_DIR" "$REPO/.clodex/runner"
```

Exit 1 means it printed one ready-to-attach `codex` block per orphaned
envelope, every field copied from disk. Attach each block to an event that
stage still appends — any event carries one `codex` block. The diff is
recomputable, so a block with no carrier left is not hand-carried in prose: it
surfaces again at the next stage's reconcile, whose own appends can carry it.

`finding:recorded` additionally takes `severity`, `summary`, `location`,
`detail`, `recommendation`, `round`, `invocation` and `plan_hash` — `location`
and `detail` copied verbatim from the envelope's finding, so the manifest can
answer *where* and *why* without anyone opening envelopes — and
`finding:disposed`'s `note` is promoted into the snapshot beside them. See
`clodex-plan` §9.

### Long rounds: `--detach`, and how to watch one

A review or implementer round can outlive a harness tool timeout. Do not
babysit it in the foreground and do not hand-roll nohup — the runner does it:

```bash
bash "$RUNNER" --role implementer --repo "$REPO" \
     --run-id "$(basename "$RUN_DIR")" --prompt-file "$PROMPT" --detach
# -> detached <invocation-id> pid <pid> log <runner log path>
```

Watch **both** signals, because either alone lies: the pid (gone means the
run ended, says nothing about how) and the runner log's final status line —
`grep -E '^(complete|partial|interrupted|failed) ' <log>` — which also names
the envelope. Heartbeats stream into the same log, so a stalled run and a
slow one are distinguishable mid-flight. When the pid is gone, map the status
the way the stage skills' rc tables do. `--resume <invocation-id>` works
alone: the runner recorded the prompt path in the invocation's meta.

Stage skills always pass `--run-id "$(basename "$RUN_DIR")"`. It keys the
runner state by run (`.clodex/runner/<run-id>/<role>/…`), so two runs in one
repo never interleave their envelopes.

---

## 1. Preflight — before any stage runs

Run every check. A failed check stops here; do not "proceed and see." Report the
results in chat **and carry them into the run**: the `run:opened` event in §6
takes a `preflight` field holding every check's verdict, so "was this
environment ever verified?" is answerable from the manifest instead of from a
transcript. Preflight that runs again — on a resume, or after the user fixes a
failed check — rides on whatever event you append next, and appends a second
record rather than replacing the first.

A run that is resumed rather than opened has no `run:opened` to carry it: put
the `preflight` field on the `stage:*:entered` event the stage skill appends,
which is the first event of the resumed session.

**When a check fails**, the invocation does not end: name the check, say exactly
what would fix it, and wait for the user. When they say it is fixed, **resume
from that check** — re-run it and continue down the list. Do not silently re-run
the checks that already passed, and do not skip the ones after it.

**Order on a first run:** checks 4 and 6 read the profile, which does not exist
yet. Do checks 1–3 and 5, run the interview (§3), then come back and finish 4
and 6. A first run also has no `.clodex/` directory, so §2 finds nothing and
costs one `ls`.

1. **Repo root.** `git rev-parse --show-toplevel`. Not inside a work tree → stop
   and ask where the work lives. Also note the branch: `git rev-parse
   --abbrev-ref HEAD`.
2. **Remote state.** `$REMOTE` comes from the preamble — the remote is not
   always named `origin`, and halting a workflow over a hardcoded name is a
   self-inflicted outage:
   ```bash
   if [ -n "$REMOTE" ]; then
     git ls-remote --exit-code "$REMOTE" HEAD >/dev/null
   else
     echo "no remote configured"
   fi
   git status -sb | head -1                       # ahead/behind
   ```
   `ls-remote` proves the remote is reachable *and* that credentials work.
   Report divergence now — a repo behind its remote gets resolved before
   planning, never at ship. "No remote configured" is a **pass**, not a failure:
   say so out loud, because ship will have no push step.
3. **`.clodex/` ignore rule.** Run state must never be committed; the profile
   must be:
   ```bash
   git check-ignore -q .clodex/ANY-RUN-ID/events.ndjson  # expect exit 0 (ignored)
   git check-ignore -q .clodex/profile.json              # expect exit 1 (NOT ignored)
   ```
   `check-ignore` tests the path against the ignore rules, so neither path has to
   exist and `ANY-RUN-ID` is a stand-in, not a reserved name. Exit 1 on the
   second probe is the **pass**, not an error — run them as two separate commands
   so a shell with `set -e` cannot swallow the result.
   Either result wrong → the remedy is the **nested ignore file**,
   `.clodex/.gitignore`, self-contained inside the directory it governs so no
   other session's edit to the shared `.gitignore` can collide with it (that
   collision once nearly swept 56 events into someone else's commit):
   ```
   *
   !.gitignore
   !profile.json
   !claims.json
   ```
   The `!.gitignore` line lets the file exempt itself; without it the remedy
   ignores its own carrier. `claims.json` is the shared-claims ledger (check
   8) — committed state like the profile, so it gets the same negation (for a
   root-style remedy: `!.clodex/claims.json`). Show the user, write it after they agree, and make
   sure it gets **committed** (§3 step 4 commits it beside the profile) — an
   uncommitted nested file does not exist in a fresh worktree, which is exactly
   where run state most needs ignoring. Root-`.gitignore` lines (`.clodex/*` +
   `!.clodex/profile.json`) remain a legal remedy where a repo already has
   them; do not migrate a working one.

   **Second ignore mechanisms replace `.gitignore` — probe every one present.**
   `.gcloudignore`, `.dockerignore`, `.vercelignore`, `.npmignore`: each makes
   its uploader ignore *its* list instead of git's, so a repo whose git ignore
   is perfect can still ship run state — sixteen worktrees of clodex logs and
   evidence screenshots once entered a production Cloud Build upload exactly
   this way. For each such file that exists:
   ```bash
   for f in .gcloudignore .dockerignore .vercelignore .npmignore; do
     [ -f "$f" ] && { grep -qE '(^|/)\.clodex(/|$)|^\.clodex\b' "$f" \
       || echo "$f does not exclude .clodex/ — run state will ride its uploads"; }
   done
   ```
   A miss is handled the way this check handles `.gitignore`: show the exact
   lines to add (`.clodex/` — plus `worktrees/` when lanes live under the
   repo), and write them only after the user agrees.
4. **Runtimes.** For each entry in the profile's `runtimes`: `command -v
   <command>`, plus the version check when `min_version` is set. Missing runtime
   → stop; it fails later and more expensively inside a stage. An empty list is
   a legal answer (this repo pins no runtimes); a *missing* `runtimes` key is a
   profile that never answered the question — go fix it in §3.

   **In a worktree, a missing prerequisite gets an offer — never an auto-run,
   never a shrug.** The profile's `commands.install` is required by the
   schema, filled at the interview, and executed by nothing — while every
   lane rediscovers the same folklore (symlinked env files, a venv built from
   the parent checkout) by hand. When this check, or a dry probe of the test
   command, shows dependencies, a venv, or an env file absent in a worktree:
   **offer** to run `commands.install`, and offer to materialize the env
   files the main checkout carries (symlink or copy; the user names which
   files, and their contents are never read or printed). Run either only
   after the user says yes. Preflight's charter stays proof, not
   construction — the offer is the construction path, and it is theirs to
   take.
5. **Codex auth.** `command -v codex`, then `codex login status` (expect exit 0
   and a logged-in line). Codex is not optional: plan review is default-on and
   build delegates to it. Not logged in → stop and ask the user to run
   `codex login`.
6. **Credentials.** For each name in the profile's `required_env`:
   ```bash
   printenv "$NAME" >/dev/null || echo "missing credential: $NAME"
   ```
   Names only. Never print, echo, log, or write a credential value.
7. **Bootstrap (worktree lanes only).** When this checkout is a linked
   worktree — `git rev-parse --git-dir` differs from `git rev-parse
   --git-common-dir` — first-run setup must already be **committed**, never
   re-created here:
   ```bash
   git ls-files --error-unmatch .clodex/profile.json   # expect exit 0 (tracked)
   ```
   Tracked → record `{"name": "bootstrap", "status": "pass"}` among the
   preflight checks. Not tracked → **stop; a lane never interviews.** Two
   lanes once interviewed independently, six minutes apart, produced
   contradictory profiles, and merge order silently picked the winner — every
   later lane inherited answers nobody chose. The fix is the bootstrap ritual
   (§3), run once from the main checkout on the default branch before lanes
   fork; tell the user that, and wait. In the main checkout this check is a
   no-op — §3 handles the first run there.
8. **Claims (when `.clodex/claims.json` exists).** The shared-claims ledger:
   collision-prone resources — migration numbers, ports, workflow ids,
   property names — claimed for the repo's concurrent lanes. **Orchestrator-
   owned: only the orchestrator writes or commits it; lanes read.** Shape:
   ```json
   {"claims": [{"resource": "migration-008", "holder": "lane-C",
                "note": "room-liveness schema"}]}
   ```
   Check every resource this run will need — the brief usually names them,
   and the plan's `Claims:` line (clodex-plan §5) re-checks at plan time:
   ```bash
   python3 - "$REPO/.clodex/claims.json" <needed resource>... <<'PY'
   import json, sys
   path, needed = sys.argv[1], sys.argv[2:]
   try:
       held = {c["resource"]: c for c in json.load(open(path)).get("claims", [])}
   except FileNotFoundError:
       print("no claims ledger"); raise SystemExit(0)
   rc = 0
   for r in needed:
       c = held.get(r)
       if c and c.get("holder"):
           print("CLAIMED: %s is held by %s%s" % (r, c["holder"],
                 " — " + c["note"] if c.get("note") else ""))
           rc = 1
       else:
           print("free:", r)
   raise SystemExit(rc)
   PY
   ```
   A `CLAIMED` hit **fails the lane here** — three lanes once independently
   claimed the same migration number, and only the orchestrator's hand
   arbitration caught it at merge. The fix is theirs: renumber, or get the
   orchestrator to reassign the claim and commit the ledger. Never edit
   `claims.json` from a lane, even to claim for yourself — a lane has no
   commit authority over shared coordination state.

   **Waiting on a sibling lane** is the same read-only discipline: the
   sanctioned recipe is a Monitor polling
   `git ls-tree <default-branch> -- <the path the sibling will land>` until
   it appears — no new event, no shared mutable state, and the poll answers
   from committed truth rather than from another lane's promises.

---

## 2. Is a run already open?

```bash
ls -1d "$REPO"/.clodex/r-*/ 2>/dev/null
python3 "$STATE" status "$REPO/.clodex/<run-id>"
```

A run is **open** when `status` shows a `stage:` other than `closed`.

`stage: -` is not an open run — it is a directory that never got its
`run:opened` event, left by a session that died in the window §6 opens between
`mkdir` and the first append. It has no brief, lane, or start commit, so there
is nothing to resume. Close it out and open a new run:
`echo '{"e":"run:closed"}' | python3 "$STATE" append "$RUN_DIR"` (legal on an
empty log; it yields `stage: closed`).

**v0.1 allows one open run per repo.** If you find two, the older is the one
whose run id sorts first — the ids are `r-<date>-<letter>`, so plain
lexicographic order is chronological. Resume it, or close it with the same
`run:closed` append, before opening anything new.

`status` also prints a `lock:` line when `lock.json` exists. That line decides
what you may do:

| `status` shows | What it means | What to do |
|---|---|---|
| no `lock:` line | no write is in flight and no writer died mid-write | Offer resume (below); an `append` will be accepted. This is the *normal* state even while another session is working, because the lock is taken per write and released — so a missing lock line is not proof you are alone. The one-open-run rule and the user's answer to the resume offer are what actually keep two agents off one run. |
| `lock: held by pid N (not running) since …` | a session died mid-write | Offer resume-or-abort. On resume: `python3 "$STATE" unlock "$RUN_DIR"` — plain `unlock` succeeds only for a dead holder, which is exactly this case — then resume. Never `--force` here. |
| `lock: … (running)` or `… (liveness unknown)` | another session owns the run, or a write is in flight right now. *Unknown* means the lock carries no usable PID — including a lock caught in the instant between its creation and its payload write, whose holder is very much alive | **Do not write.** Name the PID to the user. `unlock` will refuse. Only after the user confirms that process is gone may you run `unlock --force`. Otherwise abort here and let the other session finish. |

**Who may write run state while the lock is held:** only the holder, plus
processes the holder spawned carrying the `CLODEX_LOCK_TOKEN` environment
variable, which the engine exports to its children so they can write as the same
owner. Every other session's `append` is refused — exit 1, nothing written. You
never create or hand-edit `lock.json`, and there is no `acquire` verb: the engine
takes the session lock around each write itself. A dead holder's lock is **never**
broken implicitly; breaking it is this skill's decision, made with the user.

**The resume offer.** From `status` (and `rebuild` for fields `status` does not
print, such as `brief`), tell the user in one message: the run id and lane, the
brief, the current stage, plan version and amendment count, open findings,
verification debt, release state and any pending step. Then offer these three —
**and lead with the one the situation calls for, not always Resume**:

- **Close** → append `{"e": "run:closed"}`. Lead with this, and say plainly that
  it is the answer, whenever the run reached you as a **hand-back from a stage
  skill asking for closure** — `clodex-verify` does that when verification
  fails, so a follow-on run can carry this run's id as its `parent` (§6). Such a
  run is still open at its stage, so offering Resume first walks the user
  straight back into the loop the hand-back exists to escape. Follow the
  handing-back skill's stated procedure; do not improvise a substitute here.
- **Resume** → hand to the stage skill for the current stage (§6 table). If
  `release:` shows a pending step, do **not** retry it here: clodex-ship
  reconciles pending steps against reality before any retry.
- **Abandon** → append `{"e": "release:updated", "state": "abandoned"}`, then
  `{"e": "run:closed"}`.

**Archive on close — every close path, this skill's and ship's.** A run that
lives in a worktree keeps its evidence, envelopes and handoff artifact in a
directory that dies with `git worktree remove`; a release record pointing into
one points at deletable paths. So whenever a run closes in a checkout that is
not the main one, copy the core across — archived into an ignored path, never
committed, so no commit-authority question arises:

```bash
python3 - "$STATE" "$RUN_DIR" <<'PY'
import json, os, shutil, subprocess, sys
state, run_dir = sys.argv[1], sys.argv[2]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
repo = snap["repo"]
head = subprocess.check_output(["git", "-C", repo, "worktree", "list", "--porcelain"]).decode()
main = head.splitlines()[0].split(" ", 1)[1]          # first entry is the main checkout
if os.path.realpath(main) == os.path.realpath(repo):
    print("main checkout — run state is already as durable as it gets; nothing to do")
    raise SystemExit(0)
dest = os.path.join(main, ".clodex", "archive", os.path.basename(os.path.normpath(run_dir)))
os.makedirs(dest, exist_ok=True)
copied = 0
for name in sorted(os.listdir(run_dir)):              # the run dir IS the core:
    src = os.path.join(run_dir, name)                 # log, snapshot, prompts, diffs,
    out = os.path.join(dest, name)                    # gate logs, evidence, handoff
    if os.path.isfile(src):
        shutil.copy2(src, out); copied += 1
    elif os.path.isdir(src):
        shutil.copytree(src, out, dirs_exist_ok=True); copied += 1
# Envelopes are selected by the MANIFEST, not by globbing: invocations[] names
# exactly the legs this run spent, and their envelopes are the only place
# finding location/detail exist once the worktree is gone.
for leg in snap.get("invocations") or []:
    env = leg.get("envelope")
    if not env:
        continue
    src = env if os.path.isabs(env) else os.path.join(repo, env)
    if not os.path.isfile(src):
        print("MISSING envelope (recorded but not on disk):", env)
        continue
    out = os.path.join(dest, "runner", os.path.basename(os.path.dirname(src)),
                       os.path.basename(src))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.copy2(src, out); copied += 1
print("archived %d item(s) -> %s" % (copied, dest))
PY
```

Raw runner transcripts (`*.events.ndjson` under `.clodex/runner/`) are
deliberately not copied — they are an order of magnitude bigger than
everything else combined, and the envelopes carry what the record needs.

Never delete a run directory to get out of this. The log is the record of what
happened.

---

## 3. Profile — load, or interview once

`$REPO/.clodex/profile.json` is committed state: it is how a repo tells clodex
how to build, test, version, release, and verify itself.

**It exists** → load it and validate it:

```bash
python3 - "$CLODEX_HOME" "$REPO" <<'PY'
import importlib.util, json, os, sys
home, repo = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location(
    "clodex_state", os.path.join(home, "state", "clodex_state.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
mod.validate(json.load(open(os.path.join(repo, ".clodex", "profile.json"))),
             json.load(open(os.path.join(home, "profile.schema.json"))))
print("profile ok")
PY
```

On success that prints `profile ok` and exits 0. On failure it exits 1 with a
traceback whose **last line names the offending path** — e.g.
`ClodexStateError: $.actions[0].policy: 'auto' is not an allowed value`. Report
that path and message to the user verbatim; it is the fastest fix instruction
there is.

It checks types, required fields, and enums. It does **not** check
`additionalProperties`, `pattern`, or `minItems` — so an unknown key, a
malformed action id, and an action with an empty `argv` all survive it. Read the
file yourself as well.

Two things send you back to the user: a **missing** key the schema requires, and
a **stale** profile — one whose `schema_version` is not the version
`profile.schema.json` accepts, which is the only mechanical signal that the
contract moved. Ask for just those keys and rewrite **only** those keys.
Non-destructive: never regenerate the file wholesale, never drop `notes`.

**It does not exist** → first-run interview:

1. **Inspect before asking.** Anything you can read, do not ask about:
   ```bash
   ls; sed -n '1,60p' package.json 2>/dev/null      # scripts, engines, version
   ls Makefile pyproject.toml tox.ini vercel.json railway.json fly.toml Dockerfile 2>/dev/null
   ls .github/workflows docs 2>/dev/null
   cat .nvmrc .tool-versions .python-version 2>/dev/null   # pinned runtimes
   git tag --sort=-v:refname | head -5
   git symbolic-ref --short "refs/remotes/${REMOTE:-origin}/HEAD" 2>/dev/null
   ```
   **Fill in `runtimes` and `commands.install` here** — preflight check 4 loops
   over `runtimes`, so a profile without it makes that check a permanent no-op.
   `package.json` `engines`, `.nvmrc`, `.tool-versions`, and `pyproject.toml`
   `requires-python` give you `command` and `min_version` without asking anyone.
2. **Ask once, in one message**, only what inspection cannot settle or what is a
   decision rather than a fact: confirm the build/test/lint/typecheck commands
   (`null` where the repo genuinely has none — an omitted gate gets silently
   skipped at verify) and the runtimes you inferred; version source; branch rule
   and tag format; changelog path; architecture docs and where plans go; deploy
   target and the exact command that proves a release is live; default evidence
   classes; which release actions clodex may take; the **names** of required env
   vars.

   What those terms mean, so you can answer "what are my options?":
   - **Version source** — the file that holds the authoritative version, and the
     key inside it. Typically `package.json` → `version`, or `pyproject.toml` →
     `project.version`, or a bare `VERSION` file. `null` if the repo is
     unversioned.
   - **Branch rule** — whether a run may commit straight to the default branch
     (`main`, `work_on_default: true`) or must work on its own branch
     (`work_on_default: false` plus a naming pattern like `feature/<slug>` or
     `clodex/<run-id>`).
   - **Tag format** — the pattern a release tag follows, e.g. `v{version}`
     producing `v1.4.0`; or tagging off entirely (`enabled: false`).
   - **Deploy target** — where a release actually lands and how it gets there:
     a host and project auto-deploying on push to the default branch, a manual
     command listed in `actions`, something external, or nothing at all
     (`deploy: null` — ship then closes at an explicit not-deployed boundary).
   - **Evidence classes** — the four kinds of proof a plan can require;
     `evidence.default_classes` is which of them this repo expects by default:
     `tests` (automated suites), `real-data` (run against production-shaped
     input), `live-check` (the deployed thing observed working), `visual`
     (rendered output reviewed). `clodex-plan` owns the per-plan detail.
3. **Action policy is structured, per action.** Every entry in `actions` carries
   a literal `argv` and a `policy`:
   - `auto-with-authorization` — may run once it is covered by the single
     consolidated release authorization: the one message in which `clodex-ship`
     enumerates every external action a release will take and the user approves
     the set.
   - `always-ask-exact` — the literal filled argv is presented for approval
     **every time, in every run**. Use this for destructive or irreversible
     actions, and for repos with their own guardrail tiers (an infra control
     plane marks its red-tier actions this way).

   Unsure → `always-ask-exact`. Nothing outside `actions` may be proposed at
   ship; a new action gets added to the profile and committed first. A complete
   entry — `{braced}` placeholders are filled from run state before the argv is
   shown or run:
   ```json
   {"id": "push-main",
    "argv": ["git", "push", "origin", "main"],
    "cwd": null,
    "target": "origin/main",
    "env_refs": [],
    "policy": "auto-with-authorization"}
   ```
   The remaining three fields: `cwd` is the repo-relative directory the command
   runs in, `null` meaning the repo root; `target` names what the action affects
   in plain words, so a user approving it can see the blast radius without
   parsing argv; `env_refs` lists the **names** of credentials the action needs,
   never values, and `[]` when it needs none. The same repo would mark a
   production deploy `always-ask-exact`, so its literal filled argv is shown for
   approval on every release.
4. **Write, validate, commit.** Write every required key — the schema requires
   `runtimes` and `required_env` (use `[]` for "none", never omit them) and every
   key of `commands` including `install`, precisely so preflight checks 4 and 6
   have something to check. Re-run the validator above, then commit **by
   pathspec**, because the tree — and the index — may hold the user's unrelated
   work:
   ```bash
   git add .clodex/profile.json && git commit -m "chore(clodex): repo profile" -- .clodex/profile.json
   ```
   The trailing `-- .clodex/profile.json` is the load-bearing part. A bare
   `git commit -m` commits **everything already staged**, so anything the user or
   another tool had in the index rides along inside a commit labelled as a
   profile write. With the pathspec, the commit can hold only that one file and
   the rest of the index is left exactly as it was. The `git add` is still
   required — a pathspec cannot name a file git does not yet know about. When
   §1 check 3 wrote the nested `.clodex/.gitignore`, name it in **both** lists
   — it must be committed for worktrees to inherit it.

   This is the only commit this skill makes. Never `git add -A`, `git add .`, or
   `git commit -a`. Ever.
5. **`notes` is inert.** It is free-form text for humans and nothing in clodex
   reads it. Anything that must change what clodex *does* goes in a typed field.

Field-by-field contract: `$CLODEX_HOME/profile.schema.json`.

### Bootstrap — multi-lane repos: once, before lanes fork

A repo that will run parallel lanes in worktrees gets its first-run setup as
**one commit, on the default branch, from the main checkout, before any lane
forks**: the interview above, the profile, and the nested `.clodex/.gitignore`
(§1 check 3). The router never checks branches out — when the main checkout is
not on the default branch, the commit is the user's to make there (or via
`git -C <main-checkout>` once it is), and the bootstrap waits until it exists.
A bootstrap that rides a feature branch rides **merge order**, which is the
failure this ritual kills: two lanes once interviewed independently six
minutes apart, produced contradictory profiles, and wall-clock picked the
winner — a push-policy divergence between two lanes of the same weekend traced
straight to it. Once the bootstrap commit exists, every lane's preflight
**requires** it (§1 check 7) and no lane ever interviews. A repo whose lanes
contend for numbered or named resources also bootstraps the claims ledger —
an empty `{"claims": []}` in `.clodex/claims.json`, committed the same way;
the orchestrator alone writes to it thereafter (§1 check 8).

---

## 4. Classify the ask

| Shape | The ask looks like | v0.1 |
|---|---|---|
| **feature** | new or changed behavior someone can observe — a capability, an enhancement, a behavior-changing bug fix | **core path** |
| audit | "review / inventory / assess X across the repo", no change requested yet | lane not built |
| repair | recovering a broken state — failed deploy, environment drift, corrupted data | lane not built |
| chore | mechanical, no product decision — dependency bumps, renames, formatting, test backfill, config sync | lane not built |
| sync | making two places agree — docs↔code, env↔env, fork↔upstream, inventory↔reality | lane not built |

**Feature-shaped** → continue to §5, open the run, hand to `clodex-plan`.

**Anything else** → the noticing rule. Say exactly three things and stop:

1. Name the shape: "This is chore-shaped work — a mechanical change with no
   product decision in it."
2. Say the lane is not built: "clodex v0.1 has no chore lane; audit, repair,
   chore, and sync are deferred to v0.2."
3. Propose the closest manual approach, concretely — the actual commands, files,
   or sequence you would use, not a category.

Then **do not open a run.** There is no stage skill to drive a non-feature lane,
and an open run nothing can advance is worse than none. If the user accepts the
manual approach, do that work as ordinary work: no run directory, no manifest,
no clodex events.

Mixed asks ("audit the config, then fix it") classify by what the user wants
*done*. If the fix is feature-shaped and specified, run the core path on the fix
and handle the audit part manually.

---

## 5. The change boundary

### A. At open — acknowledge what is already dirty

```bash
START_HEAD="$(git rev-parse HEAD)"                # recorded as git.start_head
git status --porcelain --untracked-files=all      # the dirty snapshot
```

`--untracked-files=all` (`-uall`) is not optional. Plain `git status --porcelain`
collapses an untracked directory into one entry — `?? docs/` — but everything
downstream treats `git.dirty_at_start` as a list of **files**, and a directory
entry breaks the change boundary in both directions. §5B asks whether a dirty
path *is* an owned path or sits under one, which an acknowledged **ancestor**
like `docs/` never satisfies: a batch owning `docs/plans/` sees no overlap, and
the user's pre-existing `docs/plans/older-draft.md` lands in the batch commit —
the exact outcome this section exists to prevent. Compared the other way, every
file under an acknowledged directory reads as an unowned stray and falsely
halts the run. `-uall` records the files themselves, so neither happens.

Record each entry as a **repo-relative file path with the status prefix
stripped**. Porcelain lines are `XY<space>path`, so take everything from the
fourth character on: ` M src/app.ts` → `src/app.ts`, `?? docs/plans/draft.md` →
`docs/plans/draft.md`. No status letters, no trailing slashes, no directories.
For a staged rename (`R  old -> new`) record the new path. A path containing a
space or a quote comes back C-quoted (`"a b.txt"`); if you hit one, re-run with
`-z` and split the NUL-separated output instead of unquoting by hand.

Show the user every dirty path. They acknowledge the list, or **the run does not
open**. The acknowledged paths go into `run:opened` as `git.dirty_at_start`
(§6). A clean tree records `[]`.

### B. Before build — when a dirty path overlaps an owned path

**Who runs this and when:** not the router. The router's pass ends at §6, and
owned paths do not exist yet at that point. `clodex-build` re-reads this section
**before opening its first batch**, comparing the plan's owned paths against
`git.dirty_at_start` in the run snapshot. Running it earlier does not work
mechanically either: the `approval:granted` event below binds to a plan hash, so
the reducer refuses it — exit 1, *"approval must bind to a plan hash; none given
and no plan is recorded"* — until `clodex-plan` has recorded a plan.

A **batch** is one bounded unit of implementation work with a declared list of
**owned paths** — the only paths that batch may touch. `clodex-plan` declares
them. A dirty path overlaps when it *is* an owned path or sits under one, which
is a sound test only because §A recorded files: if you find a directory entry in
`git.dirty_at_start` — an older run, or a hand-edited snapshot — expand it with
`git status --porcelain --untracked-files=all` before comparing, or an ancestor
entry will match nothing and let a pre-existing file through. There are exactly
**three legal outcomes**:

1. **Fold with acknowledgment.** The pre-existing edit will end up inside a
   clodex commit, so capture it into the run directory *first* and get the user
   to say so out loud:
   ```bash
   git diff -- <overlapping tracked paths> > "$RUN_DIR/pre-existing.diff"
   git diff --stat -- <overlapping tracked paths>          # show the user
   # untracked overlaps are absent from git diff — copy them instead:
   for f in <overlapping untracked paths>; do
     mkdir -p "$RUN_DIR/pre-existing/$(dirname "$f")"
     cp -p "$f" "$RUN_DIR/pre-existing/$f"
   done
   ```
   Then record the acknowledgment as an event (a plan is recorded by now, so the
   approval binds to it):
   ```json
   {"e": "approval:granted", "scope": "dirty-fold", "by": "user",
    "actions": [{"id": "fold-pre-existing", "paths": ["src/x/thing.ts"],
                 "captured": ".clodex/<run-id>/pre-existing.diff"}]}
   ```
2. **Isolate in a clean worktree.**
   ```bash
   git worktree add ../<repo>-clodex-<run-id> -b clodex/<run-id> "$START_HEAD"
   ```
   Re-run this skill from the worktree: fresh preflight, clean tree, new run. If
   a run was already open in the dirty checkout, close it (§2) and set the new
   run's `parent` to the closed run's id.
3. **Abort.** Do not open or continue the run. Tell the user what would unblock
   it — commit, stash, or move their work — and stop.

**Hard rules, no fourth option:**

- Path-level ownership never blurs file-level provenance. Owning `src/x/` does
  not entitle a commit to a pre-existing edit to `src/x/thing.ts`. That file is
  folded, isolated, or the run aborts.
- Never run `git add -A`, `git add .`, `git commit -a`, `git stash`, or
  `git checkout -- <path>` on the user's behalf.
- Ship stages only paths owned by the run's batches. Unrelated work in the tree
  is never swept into a clodex commit.

---

## 6. Open the run, then hand off

```bash
DATE="$(date -u +%Y-%m-%d)"
RUN_ID=""
for L in a b c d e f g h; do
  [ -e "$REPO/.clodex/r-$DATE-$L" ] && continue
  RUN_ID="r-$DATE-$L"; break                  # first free letter for today
done
if [ -z "$RUN_ID" ]; then
  RUN_DIR=""
  echo "no free run id for $DATE — stop, do not open a run"
else
  RUN_DIR="$REPO/.clodex/$RUN_ID"
  mkdir -p "$RUN_DIR"
fi
```

The guard is inside the block on purpose. An unguarded empty `$RUN_ID` makes
`$REPO/.clodex/$RUN_ID` expand to `$REPO/.clodex/` itself, and the append then
writes `events.ndjson` and `run.json` **beside `profile.json`**, where §2's
`ls -1d "$REPO"/.clodex/r-*/` will never find them. If you see that message,
**stop and tell the user**: eight runs in one day means something is wrong, and
appending into an existing run directory would corrupt someone else's history.

Write the event to `$RUN_DIR/run-opened.json` with your file-writing tool, not
shell interpolation — the brief is verbatim user text and will contain quotes:

```json
{"e": "run:opened",
 "run": "r-2026-08-10-b",
 "parent": null,
 "repo": "/absolute/path/to/repo",
 "branch": "main",
 "brief": "<the ask, verbatim>",
 "lane": "feature",
 "git": {"start_head": "<git rev-parse HEAD>",
         "dirty_at_start": ["src/app.ts", "docs/plans/older-draft.md"]},
 "preflight": {"status": "pass",
               "checks": [{"name": "repo-root", "status": "pass", "detail": "/absolute/path/to/repo, branch main"},
                          {"name": "remote", "status": "pass", "detail": "origin reachable, 0 ahead 0 behind"},
                          {"name": "clodex-ignore", "status": "pass", "detail": "run state ignored, profile tracked"},
                          {"name": "runtimes", "status": "pass", "detail": "node 22.4.0, python 3.12.2"},
                          {"name": "codex-auth", "status": "pass", "detail": "codex login status ok"},
                          {"name": "required-env", "status": "pass", "detail": "none required"}]}}
```

One check per §1 item, in §1's order, each with the verdict you reported in
chat. `status` is the verdict for the whole list — `pass` only when every check
passed. A check the user fixed mid-preflight is recorded at the verdict it
**ended** on, and `detail` says it was fixed, because the manifest's job is to
answer whether the environment was verified, not to relitigate how.

Two fields need a decision rather than a copy:

- **`parent`** is `null` for ordinary new work, but **not** when the ask reached
  you as a hand-back from a stage skill naming a prior run. A run cannot be sent
  backwards — stage order is monotonic — so a stage that needs earlier work
  redone closes its run and asks for a follow-on; `clodex-verify` does exactly
  this when verification fails. In that case `parent` is the closed run's id,
  copied verbatim from the hand-back sentence: `"parent": "r-2026-08-10-a"`. It
  is the only link between the two runs, so a `null` here silently orphans the
  history. The §5B worktree path is the same shape: the new run's `parent` is the
  run you closed in the dirty checkout.
- **`dirty_at_start`** is file paths only — never `"docs/"` — for the reasons in
  §5A.

```bash
python3 "$STATE" append "$RUN_DIR" < "$RUN_DIR/run-opened.json"   # stdin, never argv
rm -f "$RUN_DIR/run-opened.json"
```

The engine stamps `schema_version`, `seq`, and `t` — do not supply them. On a
non-zero exit, read the error on stderr and act on the exit codes above: `1`
covers a locked run, a bad payload, and a reducer invariant alike, and they need
different responses.

Then invoke the stage skill, telling it the absolute run directory — it reads
everything else from the run itself ("clodex-plan, run dir
`/absolute/path/to/repo/.clodex/r-2026-08-10-a`"):

| Stage in `status` | Hand to |
|---|---|
| `open`, `plan` | `clodex-plan` |
| `build` | `clodex-build` |
| `verify` | `clodex-verify` |
| `ship` | `clodex-ship` |

The router does **not** append `stage:*:entered`. Each stage skill appends its
own entry event, so the log never claims a stage that did not start.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Inventing an event name | The vocabulary is frozen at 23 names and the reducer refuses anything else; the full list is the `e` enum in `$CLODEX_HOME/state/schemas/event.schema.json`. This skill appends only four of them: `run:opened`, `run:closed`, `release:updated`, `approval:granted`. Something the names do not cover is a **field** on one of them — see the telemetry block above. |
| Reporting preflight only in chat | Chat is a transcript, and answering "was this environment verified?" from a transcript is the gap this field closes. It goes in `run:opened` (§6), or on the resumed session's first event (§1). |
| Hand-editing `run.json` | It is derived. Append an event; `rebuild` regenerates it. |
| Building an audit/repair/chore/sync lane on the fly | Name the shape, say it is v0.2, propose the manual approach (§4). |
