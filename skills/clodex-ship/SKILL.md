---
name: clodex-ship
description: Use when the clodex router or clodex-verify hands off a run at stage `ship`, when a resumed run's manifest shows stage `ship` or a release step still pending, or when a run's release state is `push-failed` or `deploy-failed`.
---

# clodex-ship — one authorization, then two-phase steps that reconcile before they retry

## Overview

This is the only stage in clodex that changes anything outside the repository, so
it is the only one whose mistakes cannot be undone by editing a file. It owes the
run three things, all of them fact in the event log:

| Fact | Event | In the run manifest |
|---|---|---|
| exactly what the user authorized — actions and accepted debt | `approval:granted` | `approvals[]` with `scope: "release-authorization"` |
| every external step, before and after it happened | `release:step:pending` → `release:step:done` / `:failed` | `release.steps[]` |
| where the release ended up | `release:updated` | `release.state`, `.tag`, `.deployed`, `.verified_live` |

### This is the single binding debt gate in clodex

`clodex-plan` declared the evidence classes. `clodex-verify` produced what it
could and recorded the rest as **verification debt** — deliberately without
gating on it, because there is exactly one place in this system where a human
accepts debt, and **it is here**, inside the release authorization (§5), in the
same message as the exact commands the release will run.

So: non-empty debt is **itemised** in the authorization, class by class, with its
`reason` and its `risk`, and it is **accepted in words**. Never inferred from
silence, never rolled into "approve?", never assumed because the user already saw
it at verify. They did not accept it at verify. Nobody has.

### Where this stage ends

**In the repository tree you write two files and no others**: the profile's
`changelog.path` and its `version.source` (§2). Working artifacts — a diff, a
prompt, a log — go in the run directory, which is gitignored. You do not edit
code, tests, or docs: those were `clodex-build`'s under a batch contract, and a
change to one here is a finding, not a quiet edit. You cannot send the run
backwards: the reducer refuses it.

You arrive here from `clodex` or from `clodex-verify`, which hands you an
absolute run directory. If you were invoked without one, **stop and invoke
`clodex`** — do not go looking for a run yourself.

---

## 0. Paths and commands

```bash
CLODEX_HOME="${CLODEX_HOME:-$HOME/.claude/skills/clodex}"   # the router's dir, not this one
STATE="$CLODEX_HOME/state/clodex_state.py"
RUNNER="$CLODEX_HOME/runner/run-codex.sh"
RUN_DIR="<the absolute run dir you were handed>"
SNAP="$(python3 "$STATE" rebuild "$RUN_DIR")"
REPO="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["repo"])')"
PLAN="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["plan"]["path"] or "")')"
RUN="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["run"])')"   # the run id — every op_id starts with it
cd "$REPO"
PROFILE="$REPO/.clodex/profile.json"
RUNNER_STATE="${CLODEX_RUNNER_STATE_DIR:-$REPO/.clodex/runner}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REMOTE="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null | cut -d/ -f1 || true)"
[ -n "$REMOTE" ] || REMOTE="$(git remote | head -1)"    # empty = this repo has no remote
```

Shell variables do not survive between command invocations — **re-establish this
block at the top of every shell you run these procedures in.** Everything below
runs from `$REPO`: `git`, the profile reads, and every action's relative `cwd`
resolve against the current directory, so from a subdirectory they answer the
wrong question.

**`$BRANCH` comes from git, not from the manifest.** `snapshot.branch` records
where the run *opened*; `clodex-build` §4 may have created a run branch
afterwards and no event records that. What you push is the branch you are on.

Engine verbs, payload on **stdin**:

```bash
python3 "$STATE" status  "$RUN_DIR"     # human summary; its `release:` line names any pending step
python3 "$STATE" rebuild "$RUN_DIR"     # the manifest: full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
```

"The **manifest**" below always means the output of `rebuild`. Append exit codes
and the lock rules live in the `clodex` skill, §"Paths and commands" and §2 —
read them there. The one that bites hardest in this stage: exit **3** means the
event *is* durably logged; run `rebuild`, do not retry. Re-appending a
`release:step:pending` after exit 3 is refused anyway (*"op_id … was already
used"*), which is the invariant doing its job.

Write every event to a file with your file-writing tool and pipe the file in. A
`reason`, a `risk`, an argv element and a commit subject all contain quotes;
shell interpolation will corrupt them.

This stage appends ten event types and no others: `stage:ship:entered`,
`approval:granted`, `release:step:pending`, `release:step:done`,
`release:step:failed`, `release:step:reconciled`, `release:updated`,
`finding:recorded`, `finding:disposed`, `run:closed`.

---

## 1. Take the handoff

```bash
python3 "$STATE" status "$RUN_DIR"
```

- `stage: verify` → append your entry event, once:
  ```json
  {"e": "stage:ship:entered"}
  ```
- `stage: ship` → a previous session already entered. **Do not append it again.**
  The engine accepts a duplicate silently — nothing stops you but this sentence.
  Read the manifest and pick up from the resume map.
- `open`, `plan`, `build` → the work is not verified yet. Hand back: *"clodex,
  run dir `<the absolute run dir>` — this run is at stage `<X>`, not ship."* You
  **cannot** pull it forward yourself; the stage before you appends its own entry
  event, and skipping one would leave the log claiming a stage that never ran.
- `closed` → the run is over. Do not reopen it, do not append to it. If the user
  wants more, `clodex` opens a new run carrying this one as its `parent`.

**Resume map** — read the manifest and match the first row that is true. The
first row exists because it is the only one that can cost real money:

```bash
python3 "$STATE" rebuild "$RUN_DIR" | python3 -c '
import json,sys
snap = json.load(sys.stdin); rel = snap["release"]
print("release state:", rel["state"], "| tag:", rel["tag"], "| deployed:", rel["deployed"])
print("timestamp:", rel["timestamp"], "| verified_live:", rel["verified_live"])
for s in rel["steps"]:
    print("  step %-12s %-8s op_id=%s reconciled=%s" % (s["step"], s["status"], s["op_id"], s["reconciled"]))
for a in snap["approvals"]:
    print("  approval", a["scope"], "REVOKED" if a["revoked"] else "standing",
          "| actions:", [x.get("id") for x in a["actions"]],
          "| accepted_debt:", [x.get("class") for x in a["accepted_debt"]])
print("debt recorded:", [d.get("class") for d in snap["verification"]["debt"]])'
```

| What you find | You are | Go to |
|---|---|---|
| **a step with `status: "pending"`** | interrupted while an external action was in flight | **§8, first, before anything else.** Reconcile it against reality. Do not retry it, do not run the next step, do not re-authorize. |
| `release.state` is `push-failed` or `deploy-failed`, nothing pending | a step failed and was recorded | §8's decision table |
| no `release-authorization` approval, or the only one shows `REVOKED` | before the gate | §3 |
| a standing `release-authorization` and no steps | authorized, nothing run | §7.1 — the first step. §6 is the mechanism each step runs through, not a place in the sequence. |
| steps done through some point in §7's order | mid-sequence | the next step in §7's order |
| `release.state` is `verified-live`, `not-deployed`, or `abandoned` | terminal | §10 — close the run if `stage` is not already `closed` |

**The reducer does not de-duplicate.** Read the state above before appending
anything: a session that died after acting appended nothing about it, and a
session that died after appending left the fact in the log where you can see it.

---

## 2. What this stage owns, and what it must never touch

**The changelog and the version source, and nothing else.** The bookkeeping step
writes the profile's `changelog.path` and its `version.source`, and the release
commit stages exactly those paths. That is the whole of what ship writes.

Usually two files. `changelog.path` may also be **the directory releases are
written into** (profile.schema.json says so, and `changelog.style` is where a
repo records a convention like *one file per release plus a rollup row*). Then
the release writes more than one changelog file, and their names come from the
convention rather than from the profile — so the **authorization names them**:
`changelog` becomes an object mapping each path to its exact text, and the
bookkeeping descriptor's `writes` is that list plus the version source (§5).
Everything downstream reads that one list.

```bash
python3 - "$PROFILE" <<'PY'
import json, sys
prof = json.load(open(sys.argv[1]))
cl, ver, tag = prof.get("changelog"), prof["version"], prof["tag"]
print("changelog:  ", (cl or {}).get("path") or "(this repo keeps none)")
print("version:    ", ver.get("source") or "(this repo is unversioned)", "| field:", ver.get("field"))
print("bump_rule:  ", ver.get("bump_rule") or "(none recorded — ask the user)")
print("tag:        ", tag["format"] if tag["enabled"] else "(tagging off in this repo)")
print("branch:     ", prof["branch"]["default"], "| work_on_default:", prof["branch"]["work_on_default"])
PY
```

| Never, in this stage | Why |
|---|---|
| Editing code, a test, a fixture, or a doc | Those are batch-owned; build changed them under a contract with a delta review. A change here is a delta nobody reviewed. It is a finding (§3). |
| `git add -A`, `git add .`, `git commit -a`, a bare `git commit -m` | Every one of them commits the whole index, including work the user staged before the run. The release commit names its pathspec (§7.2). |
| `git tag -f`, `git push --force`, `git push --force-with-lease`, deleting a tag or a branch | Rewriting published history is a human-owned decision and it is not in any authorization this skill writes. A tag pointing at the wrong commit stops the run (§8). |
| Running any command that is not in the standing authorization | The authorization *is* the authorized set (§5). §6 executes argv **out of the manifest**, so this is mechanical rather than remembered. |
| Editing `.clodex/profile.json` | Committed repo state the router owns with the user. An action this repo does not have is added there and committed first — by the router, not by you mid-release. |
| Deciding the debt is fine, or the version, or that a deploy can be skipped | All four are human-owned decisions (design spec, *Human-owned decisions*). You propose; they decide; §5 records it. |

Read-only probes are not actions and need no authorization: `git status`,
`git log`, `git ls-remote`, `git rev-parse`, `git show`, the profile's
`deploy.verify_live` checks, and `printenv NAME >/dev/null`. Reconciliation is
built out of them, so treating a read as an action would make §8 impossible.

---

## 3. The final review — against the hash that was approved

Three questions, and the first two are mechanical.

**(a) Is the approved plan still the plan?** Approvals bind to a plan content
hash. An amendment supersedes that hash and revokes every approval bound to it,
and each amendment declares the re-review it requires. **A declared re-review
that has not happened blocks ship** — that is this stage's job, not build's, and
you check it again here because build's check ran before verify:

```bash
python3 - "$STATE" "$RUN_DIR" "$RUNNER_STATE" <<'PY'
import glob, hashlib, json, os, subprocess, sys
state, run_dir, runner_state = sys.argv[1], sys.argv[2], sys.argv[3]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
plan, blockers = snap["plan"], []
print("plan: %s v%s %s" % (plan["path"], plan["version"], (plan["hash"] or "-")[:12]))

disk = None
if not plan["path"] or not plan["hash"]:
    blockers.append("this run has no recorded plan — there is nothing an approval could bind to")
elif not os.path.exists(plan["path"]):
    blockers.append("the plan file %r is gone from the tree" % plan["path"])
else:
    disk = hashlib.sha256(open(plan["path"], "rb").read()).hexdigest()
print("plan file on disk is the approved plan:", disk is not None and disk == plan["hash"])
if disk is not None and disk != plan["hash"]:
    blockers.append("the plan file on disk is not the approved plan — edited without an amendment")

live = [a for a in snap["approvals"] if a["revoked"] is None and a["scope"] == "plan"]
print("standing plan approval:", bool(live))
if not live:
    blockers.append("no standing plan approval on the current plan hash")

# No event records "a review ran", so the evidence is the envelope on disk: a
# complete one, in that role, whose inputs hash the CURRENT plan file.
ran = set()
if disk is not None:
    for path in sorted(glob.glob(os.path.join(runner_state, "*", "*.envelope.json"))):
        try:                       # a half-written envelope is an absent review,
            env = json.load(open(path))     # not a reason to crash the gate
        except (OSError, ValueError):
            print("unreadable envelope, treated as absent:", path)
            continue
        if env.get("status") == "complete" and any(
                i.get("sha256") == disk for i in env.get("inputs", []) if isinstance(i, dict)):
            ran.add(env.get("role"))
declared = sorted({r for a in plan["amendments"] for r in a["required_review"]})
print("declared re-reviews:", declared or "(none)", "| evidenced:",
      sorted(ran) or ("(none)" if disk is not None else "(not tested — no plan hash to match)"))
for role in declared:
    if role not in ran:
        blockers.append("amendment re-review %r has no complete envelope against the current plan" % role)

open_f = [f["id"] for f in snap["findings"] if f["disposition"] == "open"]
print("open findings:", " ".join(open_f) or "(none)")
if open_f:
    blockers.append("findings still open: " + " ".join(open_f))

for b in blockers:
    print("BLOCKER:", b)
print("REVIEW GATE OPEN" if not blockers else "BLOCKED — %d blocker(s)" % len(blockers))
PY
```

`BLOCKED` is not something you narrate past. A missing re-review is satisfied by
running that role against the current plan — `clodex-plan` §8 for
`plan-reviewer`, **(c) below for `code-reviewer`** — and nothing else clears it.
That second one is deliberate, not a loophole: (c) reviews the whole release diff
against the current plan, which is a superset of the batches any amendment
affected, and it is why this script is run **again at the end of §3**. First pass
it may say `BLOCKED` on a `code-reviewer` re-review that has not happened yet;
after (c) runs, the same script sees the envelope. A plan file edited without an
amendment is `clodex-build` §11, and this run cannot re-enter build, so it goes
to the user with those two facts.

**(b) Does every commit in this release belong to a batch?** `clodex-verify` §8
gives the user a path where they fix something themselves and commit it. That
commit is real, it is in the release, and no batch owns it. Find it:

```bash
python3 - "$STATE" "$RUN_DIR" <<'PY'
import json, os, re, subprocess, sys
state, run_dir = sys.argv[1], sys.argv[2]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
start = snap["git"]["start_head"]
if not start:
    raise SystemExit("no start_head recorded — this run cannot bound its own release, so it "
                     "cannot tell its commits from anyone else's. Stop: this is a defect in the "
                     "run's opening, and the user decides whether to release by hand or re-run.")
owned = {b["commit"] for b in snap["batches"] if b["commit"]}
try:                                   # the raw log, only for the hint below
    events = open(os.path.join(run_dir, "events.ndjson"), encoding="utf-8").read()
except OSError:
    events = ""
log = subprocess.check_output(["git", "log", "--format=%H %s", "%s..HEAD" % start]).decode().splitlines()
unowned = []
for line in log:
    sha, _, subject = line.partition(" ")
    # A hint only: a 7-char prefix at a hex boundary, so it does not match inside
    # some other sha. What settles an unowned commit is the user's disposition.
    hint = bool(re.search(r"(?<![0-9a-f])%s[0-9a-f]*(?![0-9a-f])" % sha[:7], events))
    if sha in owned:
        print("owned    %s  %s" % (sha[:8], subject))
    else:
        print("UNOWNED  %s  %s  | hint, the run log mentions this sha: %s" % (sha[:8], subject, hint))
        unowned.append(sha)
print("unowned commits in this release:", len(unowned))
for sha in unowned:
    print(subprocess.check_output(["git", "show", "--stat", "--oneline", sha]).decode())
PY
```

Every `UNOWNED` line is **recorded as a finding and disposed by the user before
the authorization**, and then itemised in the authorization message beside the
debt (§5). It is not swept up silently and it is not invisible at release:

```json
{"e": "finding:recorded", "id": "s-F001", "source": "ship",
 "severity": "medium",
 "summary": "commit 4f21ab9 'fix: null guard in parser' is in this release and no batch owns it"}
```

Then the user says what it is, in their words, and you dispose it:

```json
{"e": "finding:disposed", "id": "s-F001", "disposition": "accepted",
 "note": "<the user's own words>"}
```

`accepted` when they vouch for it — the `clodex-verify` §8 user-fix path, whose
own finding note carries their sha, which is why the script prints that hint.
`rejected` when it should not be in this release, which **stops the run**:
removing a commit from a branch is theirs to do, not yours. The rule underneath:
**a release never contains a change nobody named.** Rewriting history to remove
one is not a step this skill has.

**(c) One Codex `code-reviewer` round over the whole release diff.** Build
reviewed each batch against its own contract; this looks at all of it at once
against the plan. **Default-on**, with exactly one skip, and it is a predicate
over `git diff --name-only` with nothing left to interpret: skip only when
**every** path in the release diff ends `.md` or is the plan file. Everything
else — a test, a fixture, a workflow, a Dockerfile, a lockfile, a Makefile —
gets the round. Drawing the line at "does this file run?" sounds tighter and is
not: it turns a `git diff --name-only` into an argument about `tests/helpers/`,
and the round is cheap next to the release. Say in chat which of the two you did,
and list the paths you decided on.

```bash
START="$(python3 "$STATE" rebuild "$RUN_DIR" | python3 -c 'import json,sys;print(json.load(sys.stdin)["git"]["start_head"])')"
git diff "$START" HEAD > "$RUN_DIR/release.diff"
git diff --name-only "$START" HEAD                 # read this before deciding the skip
PROMPT="$RUN_DIR/release-review.prompt.md"         # written with your file tool, never a shell string
RC=0
OUT="$(bash "$RUNNER" --role code-reviewer --repo "$REPO" \
        --prompt-file "$PROMPT" --input "$RUN_DIR/release.diff" --input "$PLAN")" || RC=$?
printf 'rc=%s line=%s\n' "$RC" "$OUT"
ENVELOPE="${OUT#* }"      # strip the FIRST word only — a repo path may contain spaces
```

Read the envelope rather than the runner's prose — it is what the rc table below
sends you to, and it proves which diff was reviewed:

```bash
python3 - "$ENVELOPE" "$RUN_DIR/release.diff" <<'PY'
import hashlib, json, sys
env = json.load(open(sys.argv[1]))
want = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
print("status:", env["status"], "role:", env["role"], "invocation:", env["invocation_id"])
print("reviewed this exact release diff:", any(i["sha256"] == want for i in env["inputs"]))
print("error:", env.get("error"))
print("stderr log (path):", env["output"]["stderr"])          # a path, not the text
try:                                                          # the last of the text itself
    print("".join(open(env["output"]["stderr"]).readlines()[-10:]) or "(empty)")
except OSError as exc:
    print("(stderr log unreadable: %s)" % exc)
for f in env["findings"]:
    print(f["id"], f["severity"], "|", f["summary"], "|", f["location"])
PY
```

The prompt, in this shape:

```markdown
Assess whether this release does what its plan says, as a whole. Every batch was
already reviewed on its own; you are looking for what only shows up across them.

Plan: <the value of $PLAN> — read its Scope ("Done when"), Batches, and Evidence.
Diff under review: <$RUN_DIR/release.diff> — every commit this run made.

Report as findings:
1. Something the plan's "Done when" requires that this diff does not deliver.
2. Two batches that disagree — a caller and a callee, a writer and a reader, a
   config and the code that reads it.
3. A change outside what the plan describes.
4. A credential, token, or key VALUE in the diff. Names are fine; values never are.

Report findings only. Do not edit files and do not propose patches: this run's
build stage is over. blocker/high/medium for anything that should not be
released; low/info for improvements. Return an empty findings list if you find
nothing.
```

The runner prints one line, `"<status> <envelope-path>"`, and **its exit code is
the authority** — never read status out of prose or stderr:

| rc | Status | What to do |
|---|---|---|
| 0 | `complete` | Read the findings. |
| 2 | `partial` | It stopped short. Resume with the one-command line the runner printed on stderr — do not start a fresh invocation. |
| 3 | `interrupted` | Same: resume with the printed command. |
| 1 | `failed` | Read the envelope's `error` and `output.stderr`. A failed worker is an absent review, not a clean bill: **run it once more**, and if it fails again, add a line to §5's message — *"the final code review did not run: `<the envelope's error>`"* — so the user authorizes with that known. |
| 64 | usage error | You called the runner wrong. Fix the arguments. |
| — | empty `$OUT` | The runner died before writing an envelope. Read its stderr. |

(The runner's rc `3` is `interrupted` — resume it. That is a different `3` from
the state engine's *"logged, do not retry"* in §0; the two tools each own their
codes, and mixing them up costs a duplicate event or a lost review.)

Record every finding with `source: "code-reviewer"`, continuing the same `s-`
sequence §3(b) started — if it recorded `s-F001`, these are `s-F002` onward, and
`finding:recorded` refuses a duplicate id. Each carries `invocation`, and the
first of them carries the `codex` block (`clodex` → Telemetry) with this round's
`role`, `status`, `envelope`, `input_hashes` and `duration_s`. **A round that
finds nothing carries it too** — put it on the `approval:granted` event §5
appends, because a release whose final review found nothing and a release whose
final review never ran must not look the same in the manifest. This is the only
Codex round this stage makes, and it is the one the release rests on.

Dispose every one before §5. What carries over unchanged
from `clodex-plan` §9: the three dispositions, that **only the user** may accept
or reject one and their words go in the `note`, that nothing is ever dropped, and
that an `accepted` blocker is a legitimate end state. What is different here:
`fixed` means code changed, and **this stage cannot change code**. A finding that
needs a code fix has the same three outcomes `clodex-verify` §8 lists — a
follow-on run, the user fixing and committing it themselves (which then appears
as an unowned commit in (b), and is named there), or the user accepting it.

**Then run (a)'s script again**, last, once every finding from (b) and (c) is
disposed. It is the gate, and (b) and (c) both add findings to what it checks;
`REVIEW GATE OPEN` on that second run is what lets you write §5's message.

---

## 4. Assemble the release: what this repo's profile says will happen

The step list is computed from the profile, not chosen. Print it:

```bash
python3 - "$PROFILE" "$BRANCH" "$REMOTE" <<'PY'
import json, sys
prof, branch, remote = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
cl, ver, tag, dep = prof.get("changelog"), prof["version"], prof["tag"], prof["deploy"]
writes = [p for p in ((cl or {}).get("path"), ver.get("source")) if p]
n = 0
def step(name, detail):
    global n; n += 1; print("  %d %-12s %s" % (n, name, detail))
if writes:
    step("bookkeeping", "write " + ", ".join(writes) + " (one timestamp, chosen once)")
    step("commit", "git commit -- " + " ".join(writes))
else:
    print("  (no changelog and no version source — nothing to write, no release commit)")
if tag["enabled"]:
    step("tag", "format %s, annotated, on the release commit" % tag["format"])
if remote:
    step("push", "branch %s to %s — needs an action id from the list below" % (branch, remote))
else:
    print("  (no remote — nothing to push; the release stays on this machine)")
if dep is None:
    print("  (deploy: null — this repo does not deploy: the run closes at not-deployed)")
elif dep["trigger"] == "auto-on-push":
    step("deploy", "%s, triggered by the push itself — no separate command" % dep["target"])
elif dep["trigger"] == "manual-command":
    step("deploy", "%s — needs an action id from the list below" % dep["target"])
else:
    # NOT a step. §5 and §10 both derive the step list as auto-on-push or
    # manual-command only, so counting it here made three derivations into two
    # answers: a deploy descriptor §5 never checked but §6 would have run.
    print("  (deploy.trigger external — someone outside clodex deploys %s: not-deployed)"
          % dep["target"])
if dep and dep["verify_live"]:
    step("verify-live", "; ".join("%s: %s" % (c["name"], c["check"]) for c in dep["verify_live"]))
elif dep is not None:
    print("  (deploy.verify_live is empty — this repo cannot prove a release is live: see §7.6)")
print("profile actions available (nothing outside this list may be proposed):")
for a in prof["actions"]:
    print("  %-22s %-24s argv: %s | cwd: %s | target: %s | env: %s"
          % (a["id"], a["policy"], " ".join(a["argv"]),
             a.get("cwd") or "<repo root>", a.get("target") or "-",
             ", ".join(a.get("env_refs") or []) or "none"))
PY
```

Then settle the three things the profile cannot settle on its own:

1. **The new version.** Read the current one out of `version.source` (for a JSON
   source, `version.field` is a dotted key; for TOML or a bare `VERSION` file,
   read the file and find the line — never regex-replace blindly). `bump_rule` is
   guidance for a human, not an automation input, so you **propose** the next
   version and the user confirms it in §5.
2. **Which action id performs the push, and which performs the deploy.** Exactly
   one action whose `target` names `$REMOTE`/`$BRANCH` → that is the push, and the
   user confirms the id in §5. **Zero, or more than one, is not yours to break the
   tie on**: print the candidates and ask which id, and record their answer. The
   same for the deploy against `deploy.target`. If no action fits at all, the
   release cannot take that step: say so, and the fix is the
   router adding it to `.clodex/profile.json` and committing it — not a command
   you compose here. That profile commit lands inside this release and no batch
   owns it, so when it happens, **re-run §3(b)**: it will show up as `UNOWNED`,
   and it gets recorded, disposed, and named in the authorization like any other.
3. **Whether this branch is the one that deploys.** If `work_on_default` is false
   and you are on a run branch, `git push` publishes that branch, and merging it
   is a human decision outside clodex v0.1. Then the release does not go live in
   this run and it closes at `not-deployed` (§9), with that as the reason.

**The placeholder vocabulary is exactly five tokens**, and nothing else in an
argv is a placeholder:

| Token | Filled from |
|---|---|
| `{version}` | the version you just settled |
| `{tag}` | `tag.format` filled with it |
| `{branch}` | `$BRANCH` |
| `{run}` | `$RUN` |
| `{commit}` | **nothing — see below** |

A brace that is not one of those five is ordinary text and is left alone: a
`curl -d '{"ref":"main"}'`, a `docker --format '{{.ID}}'`, a `kubectl -o
jsonpath=...` are all perfectly good actions, and nothing here objects to them.

**Resolve all five before the argv is written into the authorization.** §6's
executor substitutes nothing — that is what lets it compare the approved argv to
the profile's, resolved, for **exact** equality — so a token reaching it would be
passed to git or a deploy CLI as literal text. §5's validator refuses the
authorization if one survives, which is the point: **the refusal lands before the
commit, the tag and the push, not after them.**

**`{commit}` cannot be used in clodex v0.1.** The release commit does not exist
when the authorization is written, and there is no second, later authorization to
fill it in — one authorization is the design. An action whose argv needs the
release sha is refused at §5 with that as the reason: tell the user this version
cannot authorize it, and let them change the profile to an action that does not
need one (deploy from the branch or the tag, or let the host resolve `HEAD`
itself). The release tag needs no such placeholder — the tag step runs directly
after the commit step, so `git tag -a <tag>` lands on HEAD, and §8's tag reconcile
is what proves HEAD was the release commit.

---

## 5. The release authorization — one message

One gate. Everything the release will do, and everything it is knowingly
shipping without, in a single message, bound to the plan hash.

Read the debt out of the manifest first, in full — you are about to quote all
three fields of every entry:

```bash
python3 "$STATE" rebuild "$RUN_DIR" | python3 -c '
import json,sys
d = json.load(sys.stdin)["verification"]["debt"]
print("verification debt entries:", len(d))
for i, item in enumerate(d, 1):
    print("%d. class: %s\n   reason: %s\n   risk:   %s" % (i, item.get("class"), item.get("reason"), item.get("risk")))'
```

**Render the action lines rather than typing them**, so that what the user reads
and what §5's validator enforces come from the same field set. Add a field to
`profile.schema.json` and it appears here without this document changing:

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" "$CLODEX_HOME/profile.schema.json" <<'PY'
import json, subprocess, sys
state, run_dir, profile_path, schema_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
prof = json.load(open(profile_path))
fields = sorted(k for k in
                json.load(open(schema_path))["properties"]["actions"]["items"]["properties"]
                if k != "id")
for a in prof["actions"]:
    print("  [%s] %s" % (a["id"], a["policy"].upper() if a["policy"] == "always-ask-exact"
                         else a["policy"]))
    for key in fields:
        shown = a[key] if key in a else ("(the schema's empty value)" )
        print("      %-9s %s" % (key + ":", json.dumps(shown) if key in a else shown))
PY
```

Fill each `{braced}` word before you paste the line in — the message must show
the string that will run. Then the message, in this shape and this order:

```
Release authorization — run <run id>
Plan <plan path> v<N>, hash <first 12>. Release commit will be on branch <branch>.
Version <current> -> <proposed>.  Tag <filled tag>.  Timestamp <the one ISO timestamp>.

Steps, in order:
 1 bookkeeping  write CHANGELOG.md (section below) and set package.json:version to 1.4.0
 2 commit       git commit -m "chore(release): v1.4.0" -- CHANGELOG.md package.json
 3 tag          git tag -a v1.4.0 -m "v1.4.0"   (on HEAD, which by then is step 2's commit)
 4 push         <the rendered block for push-main, every field, verbatim>
 5 deploy       [deploy-prod] ALWAYS-ASK-EXACT — I will show this exact command again,
                and ask again, immediately before it runs, every time it runs
                <the rendered block for deploy-prod, every field, verbatim>
 6 verify-live  read-only checks, not an authorized action:
                smoke: curl -fsS https://…/health | grep -q '"version":"1.4.0"'

Changelog text I will write:
  <the exact lines>

Verification debt this release ships with — accepting these is part of this approval:
 1 live-check
   reason: <verbatim>
   risk:   <verbatim>
 2 real-data
   reason: <verbatim>
   risk:   <verbatim>

Commits in this release that no batch owns:
 4f21ab9 "fix: null guard in parser" (src/parser.ts) — <how it was disposed, in your words>

Steps this repo's release has that I am NOT doing, and why:
 deploy — <the reason, in your words>          (omit this block when there are none)

Approve exactly these <N> actions and accept these <M> debt entries? Or name what to change.
```

Rules that make this message the gate rather than a summary of one:

- **Exact descriptors, not prose.** Each profile-backed action shows `id`, its
  policy, and **every field the profile schema defines**, rendered by the block
  above rather than chosen by you — plus, for the `bookkeeping` step
  which runs no command, `writes` (the files), `version` (the number the user just
  settled), `tag` (the release tag, when this repo tags) and `changelog` (the
  exact text). Those four are how the manifest answers *"which version, which tag
  and which text did the human agree to?"* without anyone re-reading a
  transcript; §7.2's compare holds the files on disk to them, and `{version}` and
  `{tag}` in any profile argv are resolved from them. `env_refs` are names; a
  value never appears in this message, in a log, or in an event.
- **`changelog` is a string when `changelog.path` is a file, and an object when
  it is a directory** — `{"<path>": "<the exact text of that file>"}`, one entry
  per file this release writes there. `writes` must equal those paths plus the
  version source, and the release commit's pathspec must be the same list; §5
  refuses all three ways of disagreeing. This is the only place the file names
  exist, because a one-file-per-release convention names them from the version
  and the profile cannot know them in advance.
- **Every descriptor carries its `step`**, one of §6's six names. That is what
  lets §10 check that each authorized action actually ran — an authorization for a
  push, with no `done` push step and no reason saying why, is the "tagged but
  never pushed" release the whole state machine exists to prevent.
- **`always-ask-exact` is presented literally, every time.** Never folded into
  "and then deploys", never abbreviated with an ellipsis, never batched with its
  neighbours — here **and** again immediately before each execution, including on
  a retry after a resume (§6). A repo marks an action this way precisely because
  its own guardrails require the literal command in front of a human before every
  execution; honouring that is the point of the mechanism, not a formality.
- **Debt is itemised and accepted in words.** Every entry, all three fields, no
  summarising ("some verification debt"), no counting instead of quoting. If the
  user approves without addressing the debt, **ask once more, specifically**:
  *"and do you accept these <M> debt entries?"* Silence is not acceptance.
- **An empty debt list still gets said**: *"no verification debt — every declared
  class was produced."* One line, so the absence is a fact rather than an
  omission.
- **They may cut any action from the set** — dropping the deploy is a normal,
  expected answer (§9's `not-deployed`), not a failure to talk them into it. What
  you do with a cut is come back with a **corrected whole message** and get one
  yes to that; you never append an approval covering part of what you showed.
  Record what they approved, not what you proposed.

**On yes, write the payload to `$RUN_DIR/authorization.json`** — with the actions
exactly as shown and the debt items copied verbatim from `verification.debt`:

```json
{"e": "approval:granted", "scope": "release-authorization", "by": "user",
 "plan_version": 3, "plan_hash": "<sha256, recomputed from the plan file>",
 "actions": [
   {"id": "bookkeeping", "step": "bookkeeping",
    "argv": null, "writes": ["CHANGELOG.md", "package.json"],
    "version": "1.4.0", "tag": "v1.4.0",
    "changelog": "## 1.4.0 — 2026-08-11\n- <the exact lines>",
    "cwd": null, "target": "working tree", "env_refs": [],
    "policy": "auto-with-authorization"},
   {"id": "release-commit", "step": "commit",
    "argv": ["git", "commit", "-m", "chore(release): v1.4.0", "--", "CHANGELOG.md", "package.json"],
    "cwd": null, "target": "the release commit", "env_refs": [],
    "policy": "auto-with-authorization"},
   {"id": "release-tag", "step": "tag", "argv": ["git", "tag", "-a", "v1.4.0", "-m", "v1.4.0"],
    "cwd": null, "target": "refs/tags/v1.4.0", "env_refs": [],
    "policy": "auto-with-authorization"},
   {"id": "push-main", "step": "push", "argv": ["git", "push", "origin", "main"],
    "cwd": null, "target": "origin/main", "env_refs": [],
    "policy": "auto-with-authorization"},
   {"id": "deploy-prod", "step": "deploy",
    "argv": ["<deploy command>", "<argument>", "<argument>"],
    "cwd": null, "target": "production", "env_refs": ["DEPLOY_TOKEN"],
    "policy": "always-ask-exact"}
 ],
 "accepted_debt": [
   {"class": "live-check", "reason": "<verbatim>", "risk": "<verbatim>"}
 ]}
```

- **Every step that changes anything gets a descriptor, including the
  `always-ask-exact` one.** Leaving the deploy out because it will be asked again
  later authorizes a release whose deploy §6 will then refuse — the descriptors
  are the authorized set, and the second ask is an extra gate on top, never a
  substitute for membership.
- **`verify-live` gets no descriptor.** Its checks are reads (§2), so they are not
  actions and `<N>` does not count them. The message lists them so the user knows
  what will be run against the live system; the authorized set is the descriptors.
- **A profile-backed descriptor is that profile entry, resolved — every field the
  profile _schema_ defines.** `argv`, `cwd`, `env_refs`, `target`, `policy`:
  whatever `.clodex/profile.json` declares for that id is what the descriptor
  says, with `{version}` / `{tag}` / `{branch}` / `{run}` filled in. You are
  transcribing, not composing.
- **A field the profile omits is not a free field.** `cwd`, `target` and
  `env_refs` are all optional in `profile.schema.json`, so a perfectly legal entry
  can leave one out — and an omitted one means the schema's **empty value** for
  that type (`cwd` and `target` null, `env_refs` `[]`), never "whatever the
  descriptor likes". The validator reads the field set out of the schema and
  derives the empty value from the declared type, so `cwd: "packages/b"` against
  an entry with no `cwd` is refused exactly as it is against one that wrote
  `"cwd": null`. Whether a human happened to type the key is not a security
  boundary — and a field added to the schema next year is compared the day it is
  added, without this document changing.
- The three local steps carry the ids `bookkeeping`, `release-commit`,
  `release-tag` and have no profile entry, so their fields are yours to write —
  which is why the validator checks their **shape** instead: all seven fields
  present, `policy: "auto-with-authorization"`, `cwd` null, `env_refs` `[]`, and
  an argv that is not one of the shapes §2 forbids by name (a `git commit` with
  no `--` pathspec, `-a`, `git add -A`, a `-f`/`--force`/`--delete` on a ref).
  `bookkeeping` runs no command: its `argv` is `null` and its `writes` list the
  files instead.
- **A repo with no changelog and no version source writes nothing**, so it gets
  **no `bookkeeping` descriptor and no `release-commit`** — §4's step list already
  prints that shape, and the validator expects their absence rather than merely
  tolerating it.
- **Every step §4 computed has a descriptor, or is cut in writing.** The step
  list is not advisory: it is derived from `version.source`, `changelog.path`,
  `tag.enabled`, `deploy` and the remote, and the validator derives it again the
  same way. A step that is in it and has no descriptor is the release quietly
  losing a step — bookkeeping written, then never committed, tagged or pushed,
  and §10 with nothing to notice it by. So a step you are not doing goes in the
  payload as a `cut` entry with a reason:
  ```json
  "cut": [{"step": "deploy", "why": "the user cut deploy-prod at the gate"}]
  ```
  It is shown in the message under *"Steps this repo's release has that I am NOT
  doing"*, and it is the same decision `skipped:` records at §10 — cut means
  never authorized, skipped means authorized and not run. Neither is ever
  inferred from a step simply being absent.
- **Always pass `plan_hash`, recomputed from the file.** An approval against any
  other hash is refused: *"approval binds to plan hash 'X' but the current plan
  hash is 'Y'"*.
- **Check the push descriptor names `$REMOTE` and `$BRANCH`, both.** They come
  from git; the profile's action was written months ago. An argv ending `main` on
  a run branch pushes the wrong ref, and an argv naming `origin` when the upstream
  is `upstream` pushes somewhere §7.4 will not look — either way you record
  `push-failed` for a push that did exactly what was approved. Mismatch on the
  branch → stop, and settle §4 item 3 first. Mismatch on the remote → stop; the
  profile and this checkout disagree about where this repo publishes, and that is
  the user's to resolve.

**Then validate the payload before you append it.** Every check here could also be
made at execution time, and §6 repeats the load-bearing ones — but a release that
fails halfway has already committed, tagged and pushed, and those do not come
back. This is the last moment where "no" costs nothing:

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" "$CLODEX_HOME/profile.schema.json" \
        "$RUN_DIR/authorization.json" <<'PY'
import json, os, subprocess, sys
state, run_dir, profile_path, schema_path, payload_path = sys.argv[1:6]
STEPS = ("bookkeeping", "commit", "tag", "push", "deploy", "verify-live")
LOCAL = ("bookkeeping", "release-commit", "release-tag")
TOKENS = ("version", "tag", "branch", "run", "commit")     # the whole placeholder vocabulary

def die(message):
    raise SystemExit("DO NOT APPEND — " + message)

snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
try:
    prof = json.load(open(profile_path))
except (OSError, ValueError) as exc:
    die("cannot read %s: %s" % (profile_path, exc))
try:
    ACTION = json.load(open(schema_path))["properties"]["actions"]["items"]
    if not isinstance(ACTION.get("properties"), dict) or not ACTION["properties"]:
        raise KeyError("properties")
except (OSError, ValueError, KeyError, TypeError) as exc:
    die("cannot read the action field set from %s: %s. Both gates key on that field set, so "
        "there is nothing to check a descriptor against — fix the install." % (schema_path, exc))
payload, problems = json.load(open(payload_path)), []

# The field set comes from the SCHEMA, not from the keys this profile happened to
# write. `cwd`, `target` and `env_refs` are all optional there, so a schema-legal
# entry can omit one — and an omitted field must mean the schema's empty value,
# never "nothing to compare". Deriving the empty value from the declared type is
# what makes this cover the next optional field somebody adds to the schema.
REQUIRED = set(ACTION.get("required", []))
FIELDSET = {}
for key, spec in ACTION["properties"].items():
    if key == "id":
        continue
    types = spec.get("type")
    types = [types] if isinstance(types, str) else list(types or [])
    if key in REQUIRED:
        FIELDSET[key] = ("required", None)
    elif "null" in types:
        FIELDSET[key] = ("omitted-means", None)
    elif "array" in types:
        FIELDSET[key] = ("omitted-means", [])
    elif "object" in types:
        FIELDSET[key] = ("omitted-means", {})
    else:
        FIELDSET[key] = ("no-empty-value", None)
print("action fields the schema defines:", ", ".join(sorted(FIELDSET)))

# §4's step list, derived again from the same five inputs. A step in it with no
# descriptor is a step nothing downstream can notice the absence of: §10 keys
# completeness on this same derivation, not on the descriptors that happen to
# exist.
src = prof["version"]["source"]
cl = (prof.get("changelog") or {}).get("path")
dep = prof["deploy"]
try:
    remote = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
                                     cwd=snap["repo"], stderr=subprocess.DEVNULL)
    remote = remote.decode().strip().split("/")[0]
except subprocess.CalledProcessError:
    remote = (subprocess.check_output(["git", "remote"], cwd=snap["repo"]).decode().split() or [""])[0]
STEP_LIST = []
if src or cl:
    STEP_LIST += ["bookkeeping", "commit"]
if prof["tag"]["enabled"]:
    STEP_LIST += ["tag"]
if remote:
    STEP_LIST += ["push"]
if dep is not None and dep["trigger"] in ("auto-on-push", "manual-command"):
    STEP_LIST += ["deploy"]
if dep is not None and dep["verify_live"]:
    STEP_LIST += ["verify-live"]
# verify-live is reads, and an auto-on-push deploy runs no command (§7.5): those
# two are steps without descriptors by design, and only those two.
NEEDS_DESCRIPTOR = [st for st in STEP_LIST if st != "verify-live"
                    and not (st == "deploy" and dep and dep["trigger"] == "auto-on-push")]
print("steps this repo's release has:", ", ".join(STEP_LIST) or "(none)")
print("of which need a descriptor:", ", ".join(NEEDS_DESCRIPTOR) or "(none)")

book = [x for x in payload.get("actions", []) if x.get("id") == "bookkeeping"]

def changelog_targets(entry):
    """{path: the authorized text for it} — the release's changelog files.

    `changelog.path` is a file OR "the directory releases are written into"
    (profile.schema.json), and a one-file-per-release repo writes two: the new
    release note and a rollup. So `changelog` is a string for the file case and
    a {path: text} object for the directory case, and everything downstream —
    the pathspec, §7.1's writes, §7.2's compare — reads this one derivation.
    """
    want = (entry or {}).get("changelog")
    if isinstance(want, dict):
        return want
    return {cl: want} if cl else {}

CL_FILES = changelog_targets(book[0] if book else None)
RELEASE_FILES = sorted([p for p in list(CL_FILES) + [src] if p])
print("files this release writes:", ", ".join(RELEASE_FILES) or "(none)")

values = {"version": (book[0].get("version") if book else None) or "",
          "tag": (book[0].get("tag") if book else None) or "",
          "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                            cwd=snap["repo"]).decode().strip(),
          "run": snap["run"] or ""}
def resolve(value, misses):
    """The profile's own value, with placeholders filled, at any depth."""
    if isinstance(value, str):
        for name in TOKENS:
            if "{%s}" % name in value:
                if not values.get(name):
                    misses.append(name)
                value = value.replace("{%s}" % name, values.get(name, ""))
        return value
    if isinstance(value, list):
        return [resolve(v, misses) for v in value]
    return value

def forbidden_shape(argv, tag):
    """§2's Never table, as a predicate over an argv ship wrote itself."""
    if argv[:2] == ["git", "commit"]:
        if "--" not in argv:
            problems.append("%s: `git commit` with no `--` pathspec commits the WHOLE index, "
                            "including work the user staged before the run (§2, §7.2)" % tag)
        else:
            # A pathspec is only a safety mechanism if it names the release files.
            # `-- .` is a pathspec, and it takes the whole working tree.
            given = argv[argv.index("--") + 1:]
            want = RELEASE_FILES
            if sorted(given) != sorted(want):
                problems.append("%s: the pathspec is %s but the release writes %s — a pathspec "
                                "commit takes the working tree, so anything else in it lands "
                                "unreviewed (§7.2)" % (tag, json.dumps(given), json.dumps(want)))
        if [a for a in argv if a in ("-a", "--all", "-am", "-a m")]:
            problems.append("%s: `git commit -a` stages every tracked file (§2)" % tag)
    if argv[:2] == ["git", "add"] and [a for a in argv if a in ("-A", "--all", ".")]:
        problems.append("%s: `git add -A` / `git add .` sweeps the tree (§2)" % tag)
    if argv[:2] in (["git", "tag"], ["git", "push"], ["git", "branch"]):
        bad = [a for a in argv
               if a in ("-f", "--force", "--force-with-lease", "-d", "-D", "--delete")]
        if bad:
            problems.append("%s: `%s` rewrites or deletes a published ref — a human-owned "
                            "decision that is not in any authorization this skill writes (§2)"
                            % (tag, bad[0]))

prof_acts = dict((a["id"], a) for a in prof["actions"])
for act in payload.get("actions", []):
    tag = act.get("id") or "<descriptor with no id>"
    if act.get("step") not in STEPS:
        problems.append("%s: step %r is not one of %s" % (tag, act.get("step"), ", ".join(STEPS)))
    if act.get("id") in prof_acts:
        # Every field the SCHEMA defines, against the profile's value or the
        # schema's empty value. `policy`, `step`, `cwd`, `env_refs` were each
        # found uncompared in turn; keying on the schema is what ends that.
        entry, misses = prof_acts[act["id"]], []
        for key in sorted(FIELDSET):
            kind, empty = FIELDSET[key]
            if key in entry:
                expected = resolve(entry[key], misses)
            elif kind == "required":
                problems.append("%s: its profile entry is missing the required field %s — fix "
                                ".clodex/profile.json first" % (tag, key))
                continue
            elif kind == "no-empty-value":
                problems.append("%s: the schema defines %s with no empty value and this profile "
                                "omits it, so ship cannot tell what it should be" % (tag, key))
                continue
            else:
                expected = empty
            if key not in act:
                problems.append("%s: the profile's %s is %s and the descriptor has no %s"
                                % (tag, key, json.dumps(expected), key))
            elif act[key] != expected:
                problems.append("%s: %s is %s but the profile's is %s — the profile wins"
                                % (tag, key, json.dumps(act[key]), json.dumps(expected)))
        for m in sorted(set(misses)):
            problems.append("%s: its profile entry needs {%s}, which this run cannot supply. %s"
                            % (tag, m,
                               "{commit} never can — the release commit does not exist yet, and "
                               "there is no second authorization to fill it in later (§4)."
                               if m == "commit" else
                               "The bookkeeping descriptor records no %s." % m))
    elif act.get("id") in LOCAL:
        # These three have no profile entry to be compared against, so their
        # shape is the only structural check they will ever get.
        for f in ("id", "step") + tuple(sorted(FIELDSET)):
            if f not in act:
                problems.append("%s: no %r — a local descriptor carries id, step and every field "
                                "the schema defines: %s"
                                % (tag, f, ", ".join(sorted(FIELDSET))))
        if act.get("policy") != "auto-with-authorization":
            problems.append("%s: policy is %s — ship's own steps are exactly what this message "
                            "grants, so they are auto-with-authorization"
                            % (tag, json.dumps(act.get("policy"))))
        if act.get("cwd") is not None:
            problems.append("%s: cwd is %s — ship's own commands run at the repo root"
                            % (tag, json.dumps(act.get("cwd"))))
        if act.get("env_refs"):
            problems.append("%s: env_refs is %s — ship's own commands need no credentials"
                            % (tag, json.dumps(act.get("env_refs"))))
        argv = act.get("argv")
        if act.get("id") == "bookkeeping":
            if argv is not None:
                problems.append("bookkeeping: argv is %s — it runs no command, so argv is null "
                                "and `writes` lists the files" % json.dumps(argv))
        elif not isinstance(argv, list) or not argv or not all(isinstance(w, str) for w in argv):
            problems.append("%s: argv is %s — a list of strings, one element per argument"
                            % (tag, json.dumps(argv)))
        else:
            forbidden_shape(argv, tag)
    else:
        problems.append("%s: in neither .clodex/profile.json nor %s — a new action is added to "
                        "the profile and committed first" % (tag, ", ".join(LOCAL)))
    for w in act.get("argv") or []:
        for n in TOKENS:
            if "{%s}" % n in w:
                problems.append("%s: argv still holds {%s}; §6 substitutes nothing, so it would be "
                                "passed to the command as literal text" % (tag, n))

def at_start(path):
    start = snap["git"]["start_head"]
    if not path or not start:
        return None
    try:
        return subprocess.check_output(["git", "show", "%s:%s" % (start, path)],
                                       stderr=subprocess.DEVNULL, cwd=snap["repo"]).decode()
    except subprocess.CalledProcessError:
        return None

# Every step this repo's release has, either descriptor-ed or cut in writing.
have = {}
for x in payload.get("actions", []):
    have.setdefault(x.get("step"), []).append(x.get("id"))
cut = {}
for entry in payload.get("cut", []):
    if not isinstance(entry, dict) or entry.get("step") not in STEP_LIST:
        problems.append("cut entry %s names no step this release has (%s)"
                        % (json.dumps(entry), ", ".join(STEP_LIST) or "none"))
        continue
    if not str(entry.get("why") or "").strip():
        problems.append("cut entry for %r has no `why` — a step is not dropped without a reason"
                        % entry["step"])
        continue
    cut[entry["step"]] = entry["why"]
for st in NEEDS_DESCRIPTOR:
    if st in have and st in cut:
        problems.append("step %r is both described and cut — decide which" % st)
    elif st not in have and st not in cut:
        problems.append("step %r is in this repo's release (§4) but this authorization has no "
                        "descriptor for it and no `cut` entry saying why not. A release that "
                        "quietly loses a step writes its files and never commits them." % st)
for st in cut:
    if st not in NEEDS_DESCRIPTOR:
        problems.append("step %r is cut, but it never needed a descriptor" % st)

# A repo that writes nothing has nothing to book-keep and nothing to commit.
if not (src or cl):
    for x in payload.get("actions", []):
        if x.get("id") in ("bookkeeping", "release-commit"):
            problems.append("%s: this repo has no changelog and no version source, so there is "
                            "nothing to write and nothing for a release commit to contain (§4)"
                            % x["id"])
elif len(book) != 1:
    problems.append("expected exactly one bookkeeping descriptor, found %d" % len(book))
else:
    for need in ("version", "changelog"):
        if not book[0].get(need):
            problems.append("bookkeeping: %s is required — §7.2 compares the files on disk against "
                            "it before anything is staged" % need)
    # A directory changelog writes files whose names the profile does not know,
    # so the authorization is the only place they can be named. A bare string
    # would leave §7.2 comparing against the directory itself.
    if cl and os.path.isdir(os.path.join(snap["repo"], cl)):
        if not isinstance(book[0].get("changelog"), dict):
            problems.append("bookkeeping: %s is a directory, so changelog must be an object "
                            "mapping each file this release writes to its exact text, not one "
                            "string (§7.1)" % cl)
        else:
            for path in book[0]["changelog"]:
                if os.path.normpath(path) == os.path.normpath(cl) or not (
                        os.path.normpath(path).startswith(os.path.normpath(cl) + os.sep)):
                    problems.append("bookkeeping: changelog names %r, which is not inside the "
                                    "profile's changelog directory %r" % (path, cl))
                if not str(book[0]["changelog"][path] or "").strip():
                    problems.append("bookkeeping: changelog entry %r has no text" % path)
    elif cl and isinstance(book[0].get("changelog"), dict):
        problems.append("bookkeeping: %s is a single file, so changelog is the text inserted "
                        "into it, not an object" % cl)
    writes = sorted(book[0].get("writes") or [])
    if writes != RELEASE_FILES:
        problems.append("bookkeeping: writes is %s but this release writes %s — §7.2 stages that "
                        "list and the commit pathspec is built from it"
                        % (json.dumps(writes), json.dumps(RELEASE_FILES)))
    if prof["tag"]["enabled"] and not book[0].get("tag"):
        problems.append("bookkeeping: tag is required — this repo tags releases (%s), and {tag} in "
                        "any profile argv is resolved from it" % prof["tag"]["format"])
    if src and at_start(src) is None and not book[0].get("version_file"):
        problems.append("bookkeeping: %s does not exist yet, so version_file is required — the "
                        "exact content ship will create, the way changelog carries the whole file "
                        "for a changelog this repo has never had (§7.1)" % src)

key = lambda d: json.dumps([d.get("class"), d.get("reason"), d.get("risk")], sort_keys=True)
for missing in sorted({key(d) for d in snap["verification"]["debt"]}
                      - {key(d) for d in payload.get("accepted_debt", [])}):
    problems.append("this authorization does not accept recorded debt: %s" % missing)

for p in problems:
    print("PROBLEM:", p)
print("AUTHORIZATION VALID — append it" if not problems
      else "DO NOT APPEND — %d problem(s)" % len(problems))
PY
```

`DO NOT APPEND` means go back to the user with a corrected message; it never
means append anyway and deal with it at the step. Then:

```bash
python3 "$STATE" append "$RUN_DIR" < "$RUN_DIR/authorization.json"
```

On no, or on "change this": nothing is appended, nothing runs, and you come back
with a corrected message. There is no partial authorization.

**If they will not accept a debt entry, the release does not happen.** There is
no way to ship past it — §10 blocks on debt this authorization did not cover, and
this stage cannot produce the missing evidence (verify owns that, and the run
cannot go back). Two honest endings: they accept it, or you record
`{"e": "release:updated", "state": "abandoned"}` and close (§9), and the missing
evidence becomes the point of a follow-on run that `clodex` opens.

**A plan amendment after this point revokes the authorization** — the reducer
marks it revoked in place, and §6's executor then refuses to run anything at all,
because there is no standing authorization for it to read an argv out of. This
stage does not append `plan:amended` (it is not one of
§0's ten), so an amendment here means the run went back through `clodex-build`'s
protocol, which it cannot: in practice you have a plan file that changed under
you, §3(a) blocks, and it goes to the user. If a fresh authorization does become
necessary mid-release, **it enumerates only the steps that have not run.** The
steps already `done` stay done: their `op_id`s are spent, their events stand, and
a tag that exists cannot be un-authorized. Say which those are, in the new
message, as facts rather than proposals.

**It re-lists every debt entry and gets them re-accepted, all of them.** The
revocation took the old acceptance with it — §10 counts `accepted_debt` only from
**standing** authorizations — so debt the user already accepted stops counting the
moment the first authorization is revoked, and a release that has already pushed
would block at the exit with no way forward. The debt was not re-litigated by the
amendment; the record of its acceptance was. Re-list it.

---

## 6. Running an authorized action, and the two-phase rule

**Every step is two-phase. Append `release:step:pending` before you act, and
`release:step:done` or `release:step:failed` after.** The pending event is the
only thing that tells a later session an action may already have happened; a step
that runs without one is an action nobody can reconcile.

**A step name and an action id are two different things**, and the events use one
while the executor uses the other. The step names are fixed by this document;
the action ids come from §5's authorization:

| Step name (in `release:step:*` and the `op_id`) | Action id (in the authorization, given to §6's executor) |
|---|---|
| `bookkeeping` | `bookkeeping` — no command; ship writes the files itself |
| `commit` | `release-commit` |
| `tag` | `release-tag` |
| `push` | whatever `profile.actions` calls it — `push-main` in the examples |
| `deploy` | whatever `profile.actions` calls it — `deploy-prod` in the examples |
| `verify-live` | none — the checks are reads, not actions (§2) |

The `op_id` is `$RUN-<step>-<attempt>` — `$RUN` is the run id from §0's prelude
(`snapshot.run`, e.g. `r-2026-08-11-a`), so `r-2026-08-11-a-push-1`, and `-2` for
a retry after a failure. The reducer refuses a reused `op_id` and refuses a
second pending while one is open (*"release step 'push' is still open"*), which
is what keeps two half-run actions from ever coexisting.

```json
{"e": "release:step:pending", "step": "push", "op_id": "r-2026-08-11-a-push-1"}
```

Then run it. **The argv comes out of the manifest, not out of your message** —
that is what makes "any runtime action outside the authorized set stops the run"
mechanical instead of remembered:

```bash
# CONFIRMED stays empty unless the user just said yes, in this turn, to a
# literal always-ask-exact argv. Then, and only then: CONFIRMED="confirmed-by-user".
RC=0
CONFIRMED="" python3 - "$STATE" "$RUN_DIR" "$CLODEX_HOME" "push-main" <<'PY' || RC=$?
import json, os, subprocess, sys
state, run_dir, clodex_home, action_id = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# 64 is the guard refusing: nothing ran, and there is nothing to reconcile.
# Any other non-zero came from the action itself, which is §8's problem.
def stop(message):
    print("STOP: " + message, file=sys.stderr)
    raise SystemExit(64)

LOCAL = ("bookkeeping", "release-commit", "release-tag")   # ship's own; not in profile.actions
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
auth = [a for a in snap["approvals"]
        if a["scope"] == "release-authorization" and a["revoked"] is None]
if len(auth) != 1:
    stop("expected one standing release authorization, found %d" % len(auth))
acts = [a for a in auth[0]["actions"] if a.get("id") == action_id]
if len(acts) != 1:
    stop("%r is not in the authorization — an action outside the authorized set stops the run" % action_id)
act = acts[0]
if not act.get("argv"):
    stop("%r runs no command (argv is null)" % action_id)

# The approval was typed by hand, so it is not allowed to be the only word on
# what this action is. The committed profile is the authority on membership and
# on policy; a mistyped policy would silently delete the always-ask-exact gate,
# and the user would have read the same wrong label in the authorization.
try:
    prof = json.load(open(os.path.join(snap["repo"], ".clodex", "profile.json")))
except (OSError, ValueError) as exc:
    stop("cannot read .clodex/profile.json: %s" % exc)

# The same resolution §5 did, redone here from run state. Doing it rather than
# skipping over placeholders is what keeps the comparison EXACT: a profile word
# of "release-{version}" resolves to one string, and only that string may run.
TOKENS = ("version", "tag", "branch", "run", "commit")
book = [x for a in auth for x in a["actions"] if x.get("id") == "bookkeeping"]
values = {"version": (book[0].get("version") if book else None) or "",
          "tag": (book[0].get("tag") if book else None) or "",
          "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                            cwd=snap["repo"]).decode().strip(),
          "run": snap["run"] or ""}
def resolve(value, misses):
    if isinstance(value, str):
        for name in TOKENS:
            if "{%s}" % name in value:
                if not values.get(name):
                    misses.append(name)
                value = value.replace("{%s}" % name, values.get(name, ""))
        return value
    if isinstance(value, list):
        return [resolve(v, misses) for v in value]
    return value

left = [w for w in act["argv"] for n in TOKENS if "{%s}" % n in w]
if left:
    stop("%r still holds placeholder(s) %s. Placeholders are resolved when the authorization is "
         "written (§5); one reaching here would be passed to the command as literal text."
         % (action_id, json.dumps(sorted(set(left)))))

# The field set comes from the profile SCHEMA, not from the keys this profile
# instance happened to write: `cwd`, `target` and `env_refs` are optional there,
# and an omitted one has to mean the schema's empty value rather than "nothing to
# compare". Deriving that empty value from the declared type is what makes this
# cover the next optional field added to the schema.
try:
    ACTION = json.load(open(os.path.join(clodex_home, "profile.schema.json")))
    ACTION = ACTION["properties"]["actions"]["items"]
    if not isinstance(ACTION.get("properties"), dict) or not ACTION["properties"]:
        raise KeyError("properties")
except (OSError, ValueError, KeyError, TypeError) as exc:
    stop("cannot read the action field set from %s/profile.schema.json: %s — there is nothing to "
         "check this descriptor against" % (clodex_home, exc))
REQUIRED = set(ACTION.get("required", []))
FIELDSET = {}
for key, spec in ACTION["properties"].items():
    if key == "id":
        continue
    types = spec.get("type")
    types = [types] if isinstance(types, str) else list(types or [])
    FIELDSET[key] = ("required", None) if key in REQUIRED else (
        ("omitted-means", None) if "null" in types else
        ("omitted-means", []) if "array" in types else
        ("omitted-means", {}) if "object" in types else ("no-empty-value", None))

prof_acts = dict((a["id"], a) for a in prof["actions"])
if action_id in prof_acts:
    entry, misses, wrong = prof_acts[action_id], [], []
    for key in sorted(FIELDSET):
        kind, empty = FIELDSET[key]
        if key in entry:
            expected = resolve(entry[key], misses)
        elif kind == "required":
            stop("%r: its profile entry is missing the required field %s" % (action_id, key))
        elif kind == "no-empty-value":
            stop("%r: the schema defines %s with no empty value and this profile omits it, so "
                 "there is nothing to check the descriptor against" % (action_id, key))
        else:
            expected = empty
        if key not in act:
            wrong.append("      %s: absent, but the profile's is %s" % (key, json.dumps(expected)))
        elif act[key] != expected:
            wrong.append("      %s: %s, but the profile's is %s"
                         % (key, json.dumps(act[key]), json.dumps(expected)))
    if misses:
        stop("%r needs %s, which this run cannot supply — see §4"
             % (action_id, ", ".join("{%s}" % m for m in sorted(set(misses)))))
    if wrong:
        stop("%r is not this repo's action resolved from run state — the profile wins:\n%s"
             % (action_id, "\n".join(wrong)))
elif action_id not in LOCAL:
    stop("%r is in neither .clodex/profile.json nor %s — nothing outside those may run at ship"
         % (action_id, ", ".join(LOCAL)))

missing = [n for n in act.get("env_refs") or [] if not os.environ.get(n)]
if missing:
    stop("unset credential(s): %s" % ", ".join(missing))                 # names only, never values
if act.get("policy") == "always-ask-exact" and os.environ.get("CONFIRMED") != "confirmed-by-user":
    stop("%r is always-ask-exact. Show this literal argv to the user, get a yes in this\n"
         "      turn, then re-run with CONFIRMED=confirmed-by-user:\n      %s"
         % (action_id, json.dumps(act["argv"])))
if act.get("cwd") and os.path.isabs(act["cwd"]):
    stop("%r has an absolute cwd %r — the schema says repo-relative" % (action_id, act["cwd"]))
root = os.path.realpath(snap["repo"])
cwd = os.path.realpath(os.path.join(root, act.get("cwd") or ""))
if cwd != root and not cwd.startswith(root + os.sep):
    stop("%r has cwd %r, which resolves to %s — outside this repo"
         % (action_id, act.get("cwd"), cwd))
print("running:", json.dumps(act["argv"]), "in", cwd)
sys.exit(subprocess.call(act["argv"], cwd=cwd))
PY
printf 'rc=%s\n' "$RC"
```

- `CONFIRMED=confirmed-by-user` may be set **only** in the same turn the user
  answered yes to the literal argv you just showed them. Setting it because you
  showed it last time, or because the authorization already listed it, defeats the
  entire policy. Every execution, every retry, every resumed session: show it, ask,
  then set it.
- The block never composes a shell string. argv is a list, executed as a list, so
  a target containing a space or a quote cannot become two arguments.
- A missing `env_refs` name stops the step before it acts. Names only, always.
- **The profile is the authority on the whole descriptor, not the approval.** The
  descriptors in §5 are typed by hand, and every hand-copied field is a gate
  somebody can delete by mistyping it: a `policy` written
  `auto-with-authorization` removes the `always-ask-exact` ask, a wrong `cwd`
  publishes the wrong package under the right argv, an emptied `env_refs` skips
  the credential check entirely. None of it is caught by the human gate either,
  because §5's message renders those same fields from the same wrong descriptor.
  So for any action with a profile entry the executor compares **every field that
  entry declares**, after placeholder resolution, and refuses on any absence,
  emptying or disagreement — not a list of field names that has to be extended
  each time one is found missing from it. It also refuses an id that is in
  neither the profile nor ship's own three, and refuses outright if the profile
  cannot be read. This is the mechanism behind the profile schema's *"Nothing
  outside this list may be run at ship"*, and behind a repo marking its red-tier
  actions `always-ask-exact` and expecting that to hold.
- **Know what that authority is not.** `.clodex/profile.json` is working-tree
  state, not a hash the authorization pins: an edit to it between the
  authorization and the step changes what the executor compares against, and it
  would report a mismatch against the approval rather than noticing the profile
  moved. It is committed repo state that this stage never edits (§2), so the
  realistic case is a person editing it mid-release — and then the mismatch is
  the right answer, because what the user approved and what the repo now declares
  really have come apart. Take it to them; do not reconcile it yourself.
- **And know where the field set comes from.** Both gates read it from
  `$CLODEX_HOME/profile.schema.json` — **skill-install state, not committed repo
  state**. The repo's profile remains the authority on the *values*, but the
  *set of fields compared* is trusted from the install, so a narrowed schema copy
  narrows what is checked. It fails closed when that file is missing, unreadable,
  or has no action properties; it cannot detect a deliberately shortened one.
- **Ship's own three ids have no profile entry**, so `bookkeeping`,
  `release-commit` and `release-tag` are checked for shape rather than against a
  declaration: §5 requires every schema field plus `step`, forbids §2's argv
  shapes, and requires the release commit's pathspec to be exactly the release
  files. That is the design — a repo does not declare its own release commit —
  and it is why §7.2's guard and the pathspec matter as much as they do.

**Read `rc` before you read anything else, because it says whether the world
changed:**

| `rc` | What it means | The step |
|---|---|---|
| `0` | the action ran and succeeded | confirm the effect (§7), then `release:step:done` |
| `64` **and a `STOP:` line on stderr** | **a guard refused; nothing ran** | `release:step:failed` straight away — no reconcile, because you know nothing happened. Fix the cause, then a new pending with a new `op_id`. |
| anything else, **including a bare `64` with no `STOP:` line** | the action ran and failed, or you do not know how far it got | `release:step:failed`, and treat the world as uncertain: §8 before any retry |

The `STOP:` marker is the load-bearing half of that first row. `64` is
`EX_USAGE`, and a deploy CLI given a bad flag exits it too — reading the number
alone would record *"nothing ran"* about a command that did.

Then close the step from what actually happened:

```json
{"e": "release:step:done",   "op_id": "r-2026-08-11-a-push-1"}
{"e": "release:step:failed", "op_id": "r-2026-08-11-a-push-1"}
```

and append the `release:updated` that records the fact this step established
(§7). A `done` for an unknown `op_id` is refused (*"no such release step"*), and
so is closing one twice (*"release step 'push' is done, not pending"*) — both
mean you are working from memory instead of from the manifest.

---

## 7. The steps, in order

**Every subsection below is the middle of this loop, and the loop is §6's — the
subsections do not repeat it.** Run it for each step in the list §4 printed,
including the ones that run no command:

1. `release:step:pending` with the step name and a fresh `op_id`.
2. For an `always-ask-exact` action: show the literal filled argv, get a yes.
3. Do the thing — §6's executor for a step with an action id, your file-writing
   tool for `bookkeeping`, the checks for `verify-live`.
4. Confirm the effect from the world, not the exit code (each subsection says how).
5. `release:step:done` or `release:step:failed` for that `op_id`.
6. The `release:updated` recording the fact this step established.

A step with no action id is still two-phase. `bookkeeping` writes files;
`verify-live` is the only step whose work is purely reads, and it still opens and
closes its step, because "the checks passed" is a fact the run has to carry.

### 7.1 bookkeeping — one timestamp, chosen once

The timestamp is release state, not a clock reading. Take it once, record it, and
read it from the manifest ever after:

```bash
RELEASE_T="$(date -u +%Y-%m-%dT%H:%M:%SZ)"      # ONCE, in the whole run
```

```json
{"e": "release:updated", "timestamp": "2026-08-11T14:32:07Z"}
```

On a resumed session, `release.timestamp` is already set: **use it, do not call
`date` again.** A changelog dated one minute after its tag is the symptom the
"one authoritative timestamp" rule exists to prevent.

Before writing, check the two files carry nobody else's work. **This guard runs
once, before ship's first write, and you are before that write exactly when
`release.steps` holds no `bookkeeping` entry** (§1's read prints the steps). If
one is there, the question is not "whose work is this" but "does what is on disk
match what was authorized" — §8's bookkeeping row, which compares both files
against the authorization's `version` and `changelog` fields and stops on a value
that is neither. The guard below is not skipped on a resume so much as replaced
by a stricter one:

```bash
git status --porcelain --untracked-files=all -- <release files>
```

Anything printed is a change ship did not make, and writing over it would put a
stranger's edit inside the release commit. Stop and resolve it with the user
exactly as `clodex` §5B does — fold it with an acknowledgment recorded as an
`approval:granted` with `scope: "dirty-fold"`, isolate, or abort. Never
`git checkout --`, never `git stash`.

Then write both files with your file-writing tool:

- **The version**, in `version.source` at `version.field`, set to the version the
  user confirmed in §5. Change that one value; leave the file's formatting alone.
- **The changelog**, one section, from what the run actually did: the plan's
  *Done when*, the batch commit subjects, and the release date from
  `release.timestamp`. It reports what happened and nothing else — no
  aspirations, no "should", nothing no commit did. Accepted verification debt
  stays in the run log and the authorization; it is release bookkeeping, not
  public changelog copy, unless the user asks for it there.

**A file this run creates is authorized by its whole content, because there is no
pre-release state to compare it against.** Both bookkeeping files work the same
way:

| The file | Existed at `start_head` | Did not |
|---|---|---|
| the changelog | `changelog` is the section being inserted | `changelog` is the **whole file**, header and all |
| the version source | `version` is the number; the compare applies that one edit to the pre-release file | `version_file` carries the **whole file**, and §5 refuses the payload without it |

The compare holds you to whichever it is: with a pre-release state it checks that
the file is that state plus exactly the authorized edit, and without one it checks
the file against the authorized content line by line, ignoring blank lines and
trailing whitespace. A header you invent at
writing time but never showed the user reads as somebody else's edit either way,
which is the point.

Reconcile (§8) is the version value and the changelog section: both present means
done, either missing means the step failed and is redone.

### 7.2 commit — the pathspec is the whole safety mechanism

**First, before anything is staged: are these files only ship's change?** This
runs on every path into this step — fresh or resumed — because that is the point
of it. A session that finished §7.1, died, and came back does not re-run §7.1's
guard, and `clodex-verify` §8 explicitly invites the user to edit and commit
files themselves in between. Without this, their edit is staged into the release
commit and `GUARD OK` is printed over the top of it.

It asks a stricter question than "is my value in there": **does this file differ
from its pre-release state only in the way the authorization describes?** A
`package.json` carrying the authorized version *and* a dependency somebody added
is not ship's change, and the version check alone would have passed it.

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" <<'PY'
import copy, difflib, json, os, subprocess, sys
state, run_dir, profile_path = sys.argv[1], sys.argv[2], sys.argv[3]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
try:
    prof = json.load(open(profile_path))
except (OSError, ValueError) as exc:
    raise SystemExit("RECONCILE: STOP — cannot read %s: %s" % (profile_path, exc))
auth = [a for a in snap["approvals"]
        if a["scope"] == "release-authorization" and a["revoked"] is None]
src = prof["version"]["source"]
cl = (prof.get("changelog") or {}).get("path")
if not src and not cl:
    raise SystemExit("RECONCILE: done — this repo has no changelog and no version source, so "
                     "there is nothing to write and no release commit to make (§4)")
book = [x for a in auth for x in a["actions"] if x.get("id") == "bookkeeping"]
if len(book) != 1:
    raise SystemExit("RECONCILE: STOP — expected one authorized bookkeeping descriptor, found %d"
                     % len(book))
book, start = book[0], snap["git"]["start_head"]
want_v, want_c = book.get("version"), book.get("changelog")

def at_start(path):
    """The file's content before the run. None means it did not exist."""
    if not path or not start:
        return None
    try:
        return subprocess.check_output(["git", "show", "%s:%s" % (start, path)],
                                       stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        return None

def parsed(text, where):
    try:
        return json.loads(text)
    except ValueError:
        raise SystemExit("RECONCILE: STOP — %s sets version.field %r but %s is not JSON. This "
                         "stage cannot read or write that safely; fix the profile."
                         % (profile_path, prof["version"].get("field"), where))

def with_version(doc, field, value):
    """A copy of `doc` with the dotted `field` set to `value` — the one edit
    §7.1 authorizes, applied to the pre-release file."""
    out = copy.deepcopy(doc)
    node, keys = out, field.split(".")
    for key in keys[:-1]:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if not isinstance(node, dict) or keys[-1] not in node:
        return None
    node[keys[-1]] = value
    return out

def changed(now, was):
    return [l for l in difflib.unified_diff((was or "").splitlines(), (now or "").splitlines(),
                                            lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]

def norm(t):
    return "\n".join(l.rstrip() for l in (t or "").splitlines() if l.strip())

verdicts = []
if src:
    if not want_v:
        raise SystemExit("RECONCILE: STOP — the authorization records no version to check against")
    now = open(src).read() if os.path.exists(src) else None
    was, field = at_start(src), prof["version"].get("field")
    if was is None:
        # This run is CREATING the file, so there is no pre-release state to
        # diff against and every line of it is new. The authorization has to
        # carry the whole content, exactly as it does for a changelog the repo
        # has never had; §5 refuses the payload without it.
        want_file = book.get("version_file")
        if not want_file:
            raise SystemExit("RECONCILE: STOP — %s does not exist at %s and the authorization "
                             "records no version_file, so there is nothing to check the file ship "
                             "is creating against (§7.1)" % (src, (start or "")[:8]))
        print("version: %s is created by this run | %d authorized bytes" % (src, len(want_file)))
        verdicts.append(("version",
                         "authorized" if now is not None and norm(now) == norm(want_file) else
                         "pre-release" if now is None else
                         "FOREIGN: " + (" | ".join(changed(norm(now), norm(want_file))[:3])
                                        or "not the authorized content")))
    else:
        # Containment, the same shape as the changelog test below: the file must
        # be its pre-release self with exactly the authorized edit applied. A
        # line-membership test passes an added `"evil": "1.4.0"` dependency,
        # because that line contains the version string too.
        if field:
            now_doc = parsed(now, src) if now is not None else None
            expected = with_version(parsed(was, "%s at %s" % (src, (start or "")[:8])),
                                    field, want_v)
            if expected is None:
                raise SystemExit("RECONCILE: STOP — version.field %r is not a path that exists in "
                                 "%s as it was before the run" % (field, src))
            def at(doc):
                for key in field.split("."):
                    doc = doc.get(key) if isinstance(doc, dict) else None
                return doc
            print("version: on disk %r | authorized %r | before the run %r"
                  % (at(now_doc), want_v, at(parsed(was, src))))
            # Diff against what was AUTHORIZED, not against the pre-release file:
            # ship's own edit is in both, so what is left is the unauthorized part.
            def canon(doc):
                return json.dumps(doc, indent=2, sort_keys=True)
            verdicts.append(("version",
                             "authorized" if now_doc == expected else
                             "pre-release" if now_doc == parsed(was, src) else
                             "FOREIGN: " + (" | ".join(changed(canon(now_doc), canon(expected))[:4])
                                            or "not the authorized edit")))
        else:
            before = was.strip()
            expected = was.replace(before, str(want_v)) if before else None
            print("version: on disk %r | authorized %r | before the run %r"
                  % ((now or "").strip(), want_v, before))
            verdicts.append(("version",
                             "authorized" if expected is not None and now == expected else
                             "pre-release" if now == was else
                             "FOREIGN: " + (" | ".join(changed(now, expected)[:4]) or "not the "
                                            "authorized edit")))

# `changelog.path` may be the directory releases are written into, in which case
# the authorization names the files it writes — a release note, a rollup — and
# carries the text of each. One derivation, the same one §5 validates against.
cl_files = want_c if isinstance(want_c, dict) else ({cl: want_c} if cl else {})

for path, want_text in sorted(cl_files.items()):
    if not want_text:
        raise SystemExit("RECONCILE: STOP — the authorization records no changelog text to check "
                         "against for %s" % path)
    # isfile, not exists: a directory here would raise IsADirectoryError, which
    # is what a directory-style changelog.path used to do before the files were
    # named individually.
    now = open(path).read() if os.path.isfile(path) else ""
    was = at_start(path) or ""
    # The whole test, and it is a containment one rather than a line-membership
    # one: the file must be its pre-release self with the authorized text
    # inserted ONCE. A per-line check against the set of authorized lines passes
    # a duplicate of any of those lines dropped anywhere else in the file —
    # `- did the thing` appended into last release's section reads as ship's own.
    # A file this release creates has was == "", so containment reduces to "the
    # file is exactly the authorized text", which is the right test for it.
    residue = now.replace(want_text, "", 1) if want_text in now else now
    inserted_once = want_text in now and norm(residue) == norm(was)
    print("changelog %s: holds the authorized text: %s | and nothing else changed: %s"
          % (path, want_text in now, inserted_once))
    # Take the authorized text back out and diff what is left against the file as
    # it was: that names the foreign edit itself, not the first three lines of a
    # diff that is mostly ship's own work.
    verdicts.append(("changelog %s" % path,
                     "authorized" if inserted_once else
                     "pre-release" if norm(now) == norm(was) else
                     "FOREIGN: " + (" | ".join(changed(norm(residue), norm(was))[:3])
                                    or "not the authorized text")))

for name, v in verdicts:
    print("%-44s %s" % (name, v))
states = [v for _, v in verdicts]
if any(v.startswith("FOREIGN") for v in states):
    print("RECONCILE: STOP — a release file holds something nobody authorized. Somebody edited it "
          "outside this run. Show it to the user; never overwrite it, and never stage it.")
elif not states:
    print("RECONCILE: done — this repo has no changelog and no version source, so there is "
          "nothing for a release commit to contain (§7.3)")
elif all(v == "authorized" for v in states):
    print("RECONCILE: done — all %d release files hold exactly what was authorized, and nothing "
          "else" % len(states))
else:
    print("RECONCILE: failed — ship's own work is missing or half-written; go back to §7.1")
PY
```

**Only `RECONCILE: done` continues into the staging below.** `failed` goes back
to §7.1 to finish the writing; `STOP` goes to the user, and nothing is staged,
overwritten, or committed until they have dealt with it.

`<release files>` below is the `writes` list from the bookkeeping descriptor —
the version source plus every changelog file, which is one file in a repo whose
`changelog.path` is a file and several in one where it is a directory. It is the
same list §5 validated and the same list the authorized commit argv names, so
the three cannot disagree.

```bash
git add -- <release files>
git status --short                       # anything staged that is not one of those is the
                                         # user's: leave it staged, and never widen the pathspec
git diff --cached -- <release files>     # read it, this is the release commit
if git diff --quiet -- <release files>; then
    echo "GUARD OK — now run the release-commit action through §6, then read it back:"
    echo "  git show --stat --oneline HEAD      # exactly those files, nothing else"
else
    echo "STOP: a release file changed after you staged it — what you read is not what would land."
fi
```

The commit itself runs through §6 under the id `release-commit`, so the argv —
pathspec included — is the one the user approved, not one composed here.

Three things, each of which has already been a bug in this codebase:

1. **The paths are named on the `commit`, not only on the `add`** — that is why
   the authorized argv ends `"--", "CHANGELOG.md", "package.json"`. A bare
   `git commit -m` commits the **whole index**, so a user who staged their own
   work before the run gets it swept into a release commit. With the pathspec,
   their index stays theirs. (`clodex-build` §10 has the long version.)
2. **A pathspec commit takes the working tree and disregards the index**, so a
   file edited after you read the staged diff is committed in its newer form and
   `git show --stat` will not show you: the file list is identical, only the
   content moved. The `git diff --quiet` guard is what holds that back, and it is
   an `if`, not a warning printed before an unconditional commit.
3. **`git add` first is still required** — a pathspec cannot name a file git does
   not yet know about, which is exactly the case for a changelog this repo has
   never had.

### 7.3 tag

Annotated, on the release commit, named by `tag.format` filled with the version.
It runs through §6 under the id `release-tag`. Never `-f`. If the tag already
exists, that is §8, not a `--force`.

```json
{"e": "release:updated", "tag": "v1.4.0"}
```

If `tag.enabled` is false there is no tag step, and the authorization said so.
In a repo with no changelog and no version source there is no release commit
either (§4's list says so out loud), and the tag then lands on HEAD — the last
batch commit. That is correct and worth saying in the authorization: *"there is
nothing for a release commit to contain; the tag goes on `<sha>`, batch 3's
commit."* §8's `commit` row does not apply to such a run, because no commit step
was ever in the list.

If the repo tags **and** pushes, check whether an action publishes the tag
(`git push origin v1.4.0`, or a push action carrying `--follow-tags`). If none
does, say it in the authorization in one line: *"the tag will exist locally
only."* Silently local tags are how a release becomes unreproducible.

### 7.4 push — the remote is verified before, and after

Before: `git ls-remote "$REMOTE" HEAD >/dev/null` proves the remote is reachable
and the credentials work — a read, so it needs no authorization. It failing here
is a clean stop that costs nothing; it failing mid-push is the state §8 exists
for.

After the action returns, prove the remote actually moved rather than believing
the exit code:

```bash
git ls-remote "$REMOTE" "refs/heads/$BRANCH"      # "<sha>\trefs/heads/<branch>"
git rev-parse HEAD
```

Equal → `release:step:done`. Not equal → `release:step:failed` and
`{"e": "release:updated", "state": "push-failed"}`, which is resumable (§9).

### 7.5 deploy

| `deploy.trigger` | The step |
|---|---|
| `auto-on-push` | The push **is** the deploy, so this step runs no command, changes nothing itself, and gets **no descriptor** in the authorization — like `verify-live`, and for the same reason. It still opens and closes a step: append the pending event, then poll §7.6's checks every 15s for at most 5 minutes. First poll that passes → `done`. Still failing at 5 minutes → `failed` and `deploy-failed`; a build that slow is something to look at, not to keep waiting on. **No `verify_live` checks at all → there is nothing to poll, and zero checks is not a pass**: go straight to §7.6's third bullet and ask the user. |
| `manual-command` | The profile action the user authorized, run through §6. Its `env_refs` are checked by name first. |
| `external` | There is no deploy step. Someone outside clodex deploys; the run closes at `not-deployed` (§9) naming that. |
| `deploy: null` | Same: no step, `not-deployed`. |

```json
{"e": "release:updated", "deployed": "vercel dpl_9f2… at 2026-08-11T14:33:10Z"}
```

`deployed` carries the deploy fact — a deployment id, URL, or time when it
deployed, and **the reason it did not** when it did not. That is what makes
`not-deployed` answerable from the manifest instead of from a chat log.

### 7.6 verify-live

Run every `deploy.verify_live[].check`. These are reads, and reads are safely
repeatable, so this is the one step where retrying blind is correct.

**They are read-only by contract with whoever wrote the profile, and nothing
verifies it.** These are the one place ship runs a shell string it did not get
from an authorization — the profile schema calls them "checks that prove the new
release is actually serving", and this stage takes that at its word. Read them
before you run them, and if one of them writes something, that is a profile
defect to report, not a check to run.

```bash
python3 - "$PROFILE" <<'PY'
import json, subprocess, sys
dep = json.load(open(sys.argv[1]))["deploy"]
if dep is None or not dep["verify_live"]:
    print("no verify_live checks in this profile"); raise SystemExit(0)
for c in dep["verify_live"]:
    rc = subprocess.call(["bash", "-c", c["check"]])
    print("check %-20s rc=%s   %s" % (c["name"], rc, c["check"]))
PY
```

- **Every check exits 0** → `release:step:done` for this step's `op_id`, then
  `{"e": "release:updated", "verified_live": "<what proved it — the check names and what they returned>", "state": "verified-live"}`.
  Terminal (§9). Closing the step is not optional because the release succeeded:
  §10 blocks on a pending step whatever the release state says.
- **Any check fails** → `release:step:failed`, then
  `{"e": "release:updated", "state": "deploy-failed"}`. Resumable. Say which
  check, its command, and its output.
- **`verify_live` is empty, or the checks cannot run here** → the profile is
  saying live state cannot be proven mechanically in this repo. Ask the user to
  look and tell you what they see; their observation, in their words, becomes
  `verified_live` and the state is `verified-live`. If they will not or cannot
  look, the release is out and unproven: record `deploy-failed`, and say plainly
  that it means *not proven live*, not *the deploy errored*. Leaving a run open
  on an unproven deploy is the honest record; `verified-live` would be a claim
  nobody made.

**There is deliberately no state for "deployed, and nobody will ever check."**
The way out of `deploy-failed` is a human: they look and you record what they
saw, or they say in as many words that they are treating it as live and you
record *that*, verbatim, as `verified_live`. Either closes the run. A release
nobody will look at stays open, and that is the record being accurate rather
than the workflow being stuck.

---

## 8. Reconcile before retry

**A pending step means an action may already have happened.** Reality decides
what happened next — not the log, not the exit code you never saw, and never a
retry "just to be safe". Re-running a push is usually harmless; re-running a
deploy, a publish, or a payment is not, and this procedure does not distinguish
between them because the run cannot.

Get the pending step and its `op_id` from §1's read, then run the check for that
step:

| Step | The question | The check | done | failed → retry | stop |
|---|---|---|---|---|---|
| `bookkeeping` | do the files hold **only** what was authorized? | **§7.2's compare**, which is the same script and runs on every path into the commit step anyway | it prints `RECONCILE: done` | `RECONCILE: failed` — your own half-done work | `RECONCILE: STOP` — a release file changed in a way the authorization does not describe. `clodex-verify` §8 invites exactly that. Show it; never overwrite it. |
| `commit` | is HEAD the release commit? | `git log -1 --format='%H %s'`; compare the sha to `batches[].commit` and read `git show --stat HEAD` | HEAD is not a batch commit and touches only the release files | HEAD is still the last batch commit | HEAD is neither — someone else committed |
| `tag` | does the tag exist, and where does it point? | `git tag --list "<tag>"`; `git rev-parse --verify "refs/tags/<tag>^{commit}"`; `git rev-parse HEAD` | it exists and points at the commit the release was cut from — the release commit, or HEAD-at-tag-time in a repo that makes none (§7.3) | it does not exist | it exists and points somewhere else — never `-f`, never delete: the user decides |
| `push` | did the remote advance? | `git ls-remote "$REMOTE" "refs/heads/$BRANCH"` vs `git rev-parse HEAD`; and if an action publishes the tag, `git ls-remote --tags "$REMOTE" "refs/tags/<tag>"` | the remote sha equals the release commit, **and** the tag ref is on the remote when one was to be published | the ref is absent, the tag was to be published and is not there, or the remote sha is an ancestor of HEAD (`git merge-base --is-ancestor <remote sha> HEAD`) | the remote sha is not an ancestor — someone else pushed; never force |
| `deploy` | is this version live? | a **version-aware** `verify_live` check — one that asserts the new version, tag, or build id and would fail against the old release — or the host's own deployment list, read-only | such a check passes, or the list shows a deployment for the release commit | **only on an affirmative negative**: a version-aware check ran and returned the **old** version, or the list shows no deployment for this commit | **the default.** No version-aware check exists (`verify_live` is `[]`, or every check would pass against the old release too) and you cannot query the host: you have established nothing. Ask the user to look before anything re-runs. |
| `verify-live` | — | just run the checks again; they are reads | — | — | — |

Four of those rows are a `git` one-liner you can read at a glance. The other two
are scripts, because they are the rows where guessing costs the most.
**`bookkeeping` is §7.2's compare** — the same script, in the place every path
into the commit step already goes through. Run it from there.

**`deploy`** — only a **version-aware** check settles it, and version-aware is
decided mechanically: the authorized version or tag appears in the check command
at a word boundary, so the check could not have passed against the old release.

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" <<'PY'
import json, re, subprocess, sys
state, run_dir, profile_path = sys.argv[1], sys.argv[2], sys.argv[3]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
try:
    dep = json.load(open(profile_path))["deploy"]
except (OSError, ValueError) as exc:
    raise SystemExit("RECONCILE: STOP — cannot read %s: %s" % (profile_path, exc))
auth = [a for a in snap["approvals"]
        if a["scope"] == "release-authorization" and a["revoked"] is None]
marks = [str(m) for m in [snap["release"]["tag"]] +
         [x.get("tag") for a in auth for x in a["actions"] if x.get("tag")] +
         [x.get("version") for a in auth for x in a["actions"] if x.get("version")] if m]
# A marker has to be specific enough to prove something. Version "2" matches
# `test 1 -lt 2`, which says nothing about what is deployed; a marker with no dot
# and under four characters cannot establish version-awareness at all.
strong = [m for m in marks if "." in m or len(m) >= 4]
weak = [m for m in marks if m not in strong]
if dep is None or not dep["verify_live"]:
    print("RECONCILE: STOP — this repo has no verify_live check, so nothing here can establish "
          "whether the deploy landed. Ask the user to look at the host before anything re-runs.")
    raise SystemExit(0)
aware = []
for c in dep["verify_live"]:
    hit = [m for m in strong
           if re.search(r"(?<![0-9A-Za-z._+-])%s(?![0-9A-Za-z._+-])" % re.escape(m), c["check"])]
    rc = subprocess.call(["bash", "-c", c["check"]])
    print("check %-18s version-aware=%-5s rc=%s   %s" % (c["name"], bool(hit), rc, c["check"]))
    if hit:
        aware.append(rc)
print("markers that could prove a version:", strong or "(none)",
      "| too generic to prove anything:", weak or "(none)")
if not aware:
    print("RECONCILE: STOP — no check names %s at a word boundary, so every one of them would "
          "pass against the PREVIOUS release too. They establish nothing about this deploy: ask "
          "the user to look at the host." % (strong or "any usable version marker"))
elif 0 in aware:
    print("RECONCILE: done — a version-aware check passed: this version is serving")
else:
    print("RECONCILE: failed — a version-aware check ran and this version is NOT serving")
PY
```

Then record it, in this order:

```json
{"e": "release:step:reconciled", "op_id": "r-2026-08-11-a-push-1"}
{"e": "release:step:done",       "op_id": "r-2026-08-11-a-push-1"}
```

`reconciled` first, while the step is still pending — it is the durable statement
that reality was consulted. Then `done` or `failed` for the same `op_id`. A retry
after `failed` is a **new** pending event with a **new** `op_id` (`…-push-2`);
the old one is never reused and never reopened.

**A `push-failed` or `deploy-failed` run with nothing pending** (§1's second row)
is the other way in. There is no step to reconcile — the failure was observed and
recorded — so run the same check anyway, because it is cheap and the world may
have moved: someone may have pushed, or the deploy may have landed late. Then
either open a **new** pending with the next attempt number and retry, or record
the boundary §9 gives you and stop. What you never do is retry without looking
first.

**If you cannot reach reality — `git ls-remote` fails, the host is down, the
credential is gone — stop.** Do not close the step, do not retry, do not guess.
Leave it pending, tell the user what you could not determine and what would
settle it. A pending step is a correct, resumable record; a wrong `done` is a lie
the next session will act on.

> **The case this section exists for.** A session dies between `git push`
> returning and the `release:step:done` append. The next session runs §1, sees
> `step push pending`, and comes straight here — **before** any retry. It runs
> `git ls-remote origin refs/heads/main`, gets the release commit's sha back,
> and appends `release:step:reconciled` then `release:step:done`. Nothing is
> pushed a second time. The step after push proceeds.

---

## 9. Where a release ends

| `release.state` | Means | Then |
|---|---|---|
| `verified-live` | the release is out and something proved it is serving | **terminal** → `run:closed` |
| `not-deployed` | the release exists and this run did not put it live, on purpose | **terminal** → `run:closed` |
| `abandoned` | the user called the release off | **terminal** → `run:closed` |
| `push-failed` | the remote did not advance | **resumable** — do not close |
| `deploy-failed` | the deploy did not land, or nothing proved it did | **resumable** — do not close |

### `not-deployed` is a real ending, not a failure

It is recorded on purpose, and it is the most common ending in a repo that is not
wired for automated deploys. All of these are it:

- `deploy: null` — this repo does not deploy;
- `deploy.trigger: "external"` — a person or system outside clodex deploys;
- the user cut the deploy action from the authorized set in §5;
- the release is on a branch this repo does not deploy from (§4, item 3);
- there is no remote, so nothing left this machine.

```json
{"e": "release:updated", "state": "not-deployed",
 "deployed": "skipped: deploy, verify-live | the user cut deploy-prod from the release authorization; this repo's deploy trigger is manual-command"}
```

`deployed` carries the reason, so the manifest answers "why isn't this live?"
without anyone re-reading a transcript. When an **authorized** step did not run,
that reason opens with the exact grammar §10 parses:

```
skipped: <step>, <step> | <why, in your own words>
```

Step names from §6's six, comma-separated, then a `|`, then the sentence. §10
reads that list and nothing else — and it reads it against **every step this
repo's release has**, so cutting the deploy cuts the live check with it and both
names belong in the list. A step you do not name is a step §10 says never
completed. It used to accept the step name appearing
anywhere in the prose, which let *"the push-button deploy dashboard was green"*
account for a `push` that never happened — a sentence, not a declaration.

**The reason after the `|` is required, and §10 refuses a list without one.** A
bare `skipped: deploy, verify-live |` is a step count, not an account: it names
what did not happen and says nothing about why, which is the one thing the
manifest is being asked for. Refusing it means every unnamed step blocks, which
is the right way round.

**`skipped:` is not the other half of `cut`, and §10 does not cross-check them.**
They answer different questions at different gates:

| | Asked at | About | Vocabulary |
|---|---|---|---|
| `cut` | §5, in the authorization payload | a step that needs a descriptor and is not getting one | never authorized |
| `skipped:` | §10, in `deployed` | a step this release has that did not complete | did not run — *whether or not* it was cut |

So a step cut at §5 is also declared skipped here — that is not a contradiction,
it is the same step failing two different tests, and §10 derives its list from
the profile rather than from the descriptors precisely so that a cut step still
has to be accounted for. And **`verify-live` can be skipped but never cut**,
because cutting is about descriptors and reads do not get one (§5). Its absence
is declared here, in this list, and nowhere else.

Then close (§10).

A resumable state closes nothing. Leave the run open, tell the user the one line
that resumes it — *"invoke `clodex` in this repo; it will offer to resume run
`<id>`"* — and stop. `clodex` §2 will route it back here, and §1 will send you to
§8 if a step is still pending.

`abandoned` is available to `clodex` at its resume offer, and to you when the
user stops a release you have already authorized. Record it, close, and say what
was already done — a release abandoned after the tag step still has the tag.

---

## 10. Exit

Run it from the repo root. It answers, from the manifest and the profile,
whether this stage did what it claims:

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" <<'PY'
import json, re, subprocess, sys
state, run_dir, profile_path = sys.argv[1], sys.argv[2], sys.argv[3]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
rel, blockers = snap["release"], []
TERMINAL, RESUMABLE = ("verified-live", "not-deployed", "abandoned"), ("push-failed", "deploy-failed")

for s in rel["steps"]:
    print("step %-12s %-8s reconciled=%-5s %s" % (s["step"], s["status"], s["reconciled"], s["op_id"]))
    if s["status"] == "pending":
        blockers.append("release step %r is still pending — reconcile it (§8)" % s["step"])

auth = [a for a in snap["approvals"] if a["scope"] == "release-authorization" and a["revoked"] is None]
# Whole entries, not just classes: two debt items can share a class, and
# accepting one of them is not accepting the other.
key = lambda d: json.dumps([d.get("class"), d.get("reason"), d.get("risk")], sort_keys=True)
debt = {key(d) for d in snap["verification"]["debt"]}
accepted = {key(d) for a in auth for d in a["accepted_debt"]}
print("standing release authorization:", len(auth))
print("debt recorded:", len(debt), "| accepted in the authorization:", len(accepted))
# A release called off before anything ran had nothing to authorize and shipped
# no debt. One that ran a step and was then abandoned still did — a run abandoned
# after the push has pushed, and the debt gate applies to what went out.
if rel["state"] != "abandoned" or rel["steps"]:
    if len(auth) != 1:
        blockers.append("expected exactly one standing release authorization, found %d" % len(auth))
    for item in sorted(debt - accepted):
        blockers.append("debt %s was never accepted — ship is the only place it can be" % item)

# A gate keyed on a hand-written field is deletable by leaving the field out, so
# a descriptor with no `step` — or one outside the six names — is itself a
# blocker rather than a descriptor with nothing to check.
STEPS = ("bookkeeping", "commit", "tag", "push", "deploy", "verify-live")
for a in auth:
    for x in a["actions"]:
        if x.get("step") not in STEPS:
            blockers.append("descriptor %r has step %r, which is not one of %s — the completeness "
                            "check below cannot see it" % (x.get("id"), x.get("step"), ", ".join(STEPS)))

# Completeness is keyed on the steps THIS REPO'S RELEASE HAS, derived from the
# profile exactly as §4 and §5 derive them — not on the descriptors that happen
# to exist. Keyed on the descriptors, an authorization that silently omitted the
# commit, tag and push steps would print SHIP COMPLETE for a release whose files
# were written and then left dirty in the tree.
try:
    prof = json.load(open(profile_path))
except (OSError, ValueError) as exc:
    raise SystemExit("NOT DONE — cannot read %s: %s" % (profile_path, exc))
try:
    remote = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
                                     cwd=snap["repo"], stderr=subprocess.DEVNULL)
    remote = remote.decode().strip().split("/")[0]
except subprocess.CalledProcessError:
    remote = (subprocess.check_output(["git", "remote"], cwd=snap["repo"]).decode().split() or [""])[0]
dep = prof["deploy"]
authorized = []
if prof["version"]["source"] or (prof.get("changelog") or {}).get("path"):
    authorized += ["bookkeeping", "commit"]
if prof["tag"]["enabled"]:
    authorized += ["tag"]
if remote:
    authorized += ["push"]
if dep is not None and dep["trigger"] in ("auto-on-push", "manual-command"):
    authorized += ["deploy"]
if dep is not None and dep["verify_live"]:
    authorized += ["verify-live"]
done_steps = {s["step"] for s in rel["steps"] if s["status"] == "done"}
# The escape hatch is an explicit list, not prose: `deployed` may begin
# "skipped: <step>, <step> | <why>". Substring-matching a sentence let
# "the push-button deploy dashboard was green" account for a push that never ran.
dep = rel.get("deployed")
m = re.match(r"^skipped:\s*([^|]*)\|(.*)$", dep, re.S) if isinstance(dep, str) else None
# The reason is the declaration. Without it the list names what did not happen
# and says nothing about why, which is the one thing it is being asked for —
# so a reason-free list buys no steps and every one of them blocks below.
if m and not m.group(2).strip():
    blockers.append("`deployed` declares steps skipped but gives no reason after the `|`: "
                    "say  skipped: %s | <why>  (§9)" % m.group(1).strip())
    m = None
skipped = {s.strip() for s in m.group(1).split(",")} & set(STEPS) if m else set()
print("steps this release has:", authorized or "(none)", "| done:",
      sorted(done_steps) or "(none)", "| declared skipped:", sorted(skipped) or "(none)")

open_f = [f["id"] for f in snap["findings"] if f["disposition"] == "open"]
print("open findings:", " ".join(open_f) or "(none)")
if open_f:
    blockers.append("findings still open: " + " ".join(open_f))

print("release: state=%s tag=%s deployed=%s verified_live=%s timestamp=%s"
      % (rel["state"], rel["tag"], rel["deployed"], rel["verified_live"], rel["timestamp"]))
print("stage:", snap["stage"])
if rel["state"] in TERMINAL:
    if snap["stage"] != "closed":
        blockers.append("state %r is terminal but the run is not closed — append run:closed" % rel["state"])
    # Terminal means finished, so every step this repo's release has either ran
    # or the release state says why not. Without this a run that tagged and never
    # pushed prints SHIP COMPLETE — the exact failure the release state machine
    # exists to prevent. (A resumable run is unfinished by definition, so the
    # same check there would be noise.)
    # A release called off before anything ran owes no per-step account; one that
    # started does, for every step this repo's release has.
    for st in (authorized if (rel["state"] != "abandoned" or rel["steps"]) else []):
        if st not in done_steps and st not in skipped:
            blockers.append("step %r is part of this repo's release and never completed, and "
                            "`deployed` does not declare it skipped — say  skipped: %s | <why>  "
                            "there" % (st, st))
    # Every step declared skipped, none done: nothing shipped. `not-deployed`
    # means the release exists and did not go live; it does not mean there was
    # no release. A run that did nothing has an honest ending and it is
    # `abandoned` (§9) — SHIP COMPLETE here would be a green light on a no-op.
    if rel["state"] != "abandoned" and authorized and not done_steps:
        blockers.append("no step of this release completed, so nothing shipped — a run where "
                        "nothing ran is `abandoned` (§9), not %r" % rel["state"])
elif rel["state"] in RESUMABLE:
    if snap["stage"] == "closed":
        blockers.append("state %r is resumable but the run was closed" % rel["state"])
    print("RESUMABLE — the run stays open on purpose; tell the user how to resume it")
else:
    blockers.append("release state %r is neither terminal nor resumable — the release is unfinished" % rel["state"])

for b in blockers:
    print("BLOCKER:", b)
print("SHIP COMPLETE — release %s" % rel["state"] if not blockers
      else "NOT DONE — %d blocker(s)" % len(blockers))
PY
```

**Reconcile telemetry** before closing: `python3 "$STATE" telemetry-sync
"$RUN_DIR" "$REPO/.clodex/runner"` (`clodex` → Telemetry). `run:closed` is the
log's last carrier — a `codex` block it prints here rides that event or rides
nothing, and a closed run with unrecorded invocations under-reports what it
cost forever. `duration_s` and `status` come from the envelope, never from
memory.

Close a terminal run — and only a terminal one:

```json
{"e": "run:closed"}
```

Two blockers that cannot be fixed by appending anything, and what to do instead:

- **`state … is resumable but the run was closed`** — `closed` is terminal in the
  reducer and §1 forbids appending to a closed run, so this cannot be undone. Say
  it plainly: the run says a step is unfinished and the run says it is over, and
  the log keeps both. Whatever is actually unfinished belongs to a follow-on run
  that `clodex` opens with this one as its `parent`.
- **`no start_head recorded`** from §3(b) — the run cannot tell its own commits
  from anyone else's, so it cannot bound a release at all. Stop and hand it to
  the user with that sentence.

Then say four things in chat, and nothing else:

1. **The release state**, and what proved it: `verified-live` with the check that
   passed, or `not-deployed` with the reason, or `abandoned`.
2. **What exists now**: the release commit sha, the tag, whether the remote has
   it, where it is deployed.
3. **The debt that was accepted**, by class — because it is now shipped, and this
   was the message where that became true.
4. **Anything still open for a human**: a merge someone has to do, a live check
   nobody could run, a finding they accepted.

A resumable run gets 2–4 as well, plus the resume line instead of 1.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Retrying a pending step on resume — pushing, tagging, or deploying again "to be safe" | Reconcile against reality first, every time (§8). The crash-after-push case has a concrete answer: `git ls-remote` the branch; if the remote already carries the release commit, the step is `done`. |
| Treating the run's own log as evidence that an action did or did not happen | The log says what was *appended*, and the gap between acting and appending is exactly where sessions die. Reality — the remote, the tag, the host — decides (§8). |
| Closing a step `done` because the command exited 0, without checking the world | Exit codes are one input. The push step confirms the remote sha; the deploy step confirms the version is serving (§7.4, §7.6). |
| Inferring debt acceptance from a "yes" that never mentioned it | Ask again, specifically, itemising every entry's class, reason, and risk. This is the only debt gate in clodex and there is no second chance at it (§5). |
| Summarising an `always-ask-exact` action, or asking once and reusing that yes | Literal filled argv, every execution, every retry, every resumed session (§5, §6). The repo marked it that way because its own rules demand it. |
| Composing a command from the profile and running it | §6 executes argv **out of the standing authorization**, and cross-checks it against the committed profile. An id in neither, a policy that disagrees with the profile, or an argv that does not match it all stop the run. |
| Trusting the `policy` you typed into the authorization | You typed it; the profile is the authority. A `policy` mistyped as `auto-with-authorization` would delete the `always-ask-exact` gate **and** show the user the same wrong label, so nobody would catch it. §6 opens `.clodex/profile.json` and refuses on disagreement. |
| Leaving a `{placeholder}` in an argv for §6 to fill | §6 substitutes nothing — it would pass `{commit}` to git as literal text. Fill every placeholder at authorization time; an argv needing the release sha cannot be authorized in v0.1 (§4). |
| Re-running a deploy on resume because nothing showed the new version | "Nothing showed it" and "nothing could have shown it" are different worlds. A retry needs an **affirmative negative** — a version-aware check that returned the old version. No version-aware check exists → stop and ask (§8). |
| `git add X && git commit -m "…"` | That commits the whole index, including the user's pre-staged work. `git commit -m "…" -- <paths>`, after the `git diff --quiet` guard, because a pathspec commit takes the working tree (§7.2). |
| Committing anything besides the changelog and the version source | Those are the only two files this stage writes. Code, tests, and docs were build's, under a contract with a review (§2). |
| Calling `date` again on a resumed session | The timestamp is release state. Read `release.timestamp` from the manifest (§7.1). |
| Recording `verified-live` because the deploy command succeeded | `verified-live` means something proved the new version is serving. Nothing proved it → `deploy-failed`, resumable, and say it means *not proven live* (§7.6). |
| Treating `not-deployed` as a failure to be avoided | It is a terminal, first-class ending with a reason recorded in `deployed` (§9). A run that will not deploy is closed honestly, not left hanging. |
| Closing a run in `push-failed` or `deploy-failed` | Those are resumable. Leave it open and give the user the resume line (§9). |
| Closing a terminal run with an authorized step that never ran | §10 blocks it. "Tagged but never pushed" is the failure the release state machine exists to catch: either run it, or name the step in the reason recorded in `deployed` (§10). |
| Letting a commit no batch owns ride along unmentioned | Record it as a finding, have the user dispose it, and itemise it in the authorization beside the debt (§3(b)). |
| Fixing a code finding here because it is small | This stage changes no code. The three legal outcomes are `clodex-verify` §8's, unchanged (§3(c)). |
| `git tag -f`, `git push --force`, or deleting a published ref to clean something up | Not in any authorization this skill writes, and not a decision this skill makes. Stop and hand it to the user (§2, §8). |
| Inventing an event name | The vocabulary is frozen at 23 names and the reducer refuses anything else. This stage appends ten of them (§0). Something the names do not cover is a **field** on one of them — the optional `preflight` and `codex` blocks, and `finding:recorded`'s `severity`/`summary`/`round`/`invocation`/`plan_hash` (`clodex` → Telemetry). |
