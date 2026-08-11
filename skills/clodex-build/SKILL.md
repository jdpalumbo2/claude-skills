---
name: clodex-build
description: Use when the clodex router or clodex-plan hands off a run at stage `build`, when a resumed run has an approved plan whose batches are not all committed and reviewed, or when a plan assumption turns out to be wrong while implementation is already in flight.
---

# clodex-build — small batches, an explicit contract, a reviewed delta

## Overview

This stage turns an approved plan into commits. It owes the run one thing per
batch, and all of it is fact in the event log rather than claim in a transcript:

| Fact | Event | In the manifest |
|---|---|---|
| what this batch may touch | `batch:opened` | `batches[].owned_paths` |
| the delta was reviewed, and the verdict | `batch:reviewed` | `batches[].delta_review` |
| the commit it landed in | `batch:committed` | `batches[].commit` |

Plus, when an assumption breaks mid-flight, a **plan amendment** — never silent
drift.

**Where this stage ends.** You prove each batch against its own test
expectations: the profile's test command green, plus your review of the delta.
You do **not** run the plan's declared evidence classes, record
`verification:evidence`, or decide anything about verification debt — that is
`clodex-verify`. You do not write the changelog, bump the version, tag, push, or
deploy — that is `clodex-ship`, and §2 makes those files forbidden to you.

You arrive here from `clodex` (which owns preflight, the profile, and the run
directory) or from `clodex-plan` (which owns the plan, its owned paths, and its
approval). If you were invoked without an absolute run directory, **stop and
invoke `clodex`** — do not go looking for a run yourself.

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
cd "$REPO"
PROFILE="$REPO/.clodex/profile.json"
```

Shell variables do not survive between command invocations — **re-establish this
block at the top of every shell you run these procedures in.** Everything below
runs from `$REPO`; `git add`, `git status`, and the profile reads all resolve
relative paths against the current directory, so from a subdirectory they answer
the wrong question.

Engine verbs, payload on **stdin**:

```bash
python3 "$STATE" status  "$RUN_DIR"     # human summary
python3 "$STATE" rebuild "$RUN_DIR"     # the manifest: full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
```

"The **manifest**" below always means the output of `rebuild`. Append exit codes
and the lock rules live in the `clodex` skill, §"Paths and commands" and §2 —
read them there. The one that bites: exit **3** means the event *is* durably
logged; run `rebuild`, do not retry.

Write every event to a file with your file-writing tool and pipe the file in.
Plan notes, finding summaries, and commit subjects contain quotes; shell
interpolation will corrupt them.

This stage appends eight event types and no others: `stage:build:entered`,
`batch:opened`, `batch:reviewed`, `batch:committed`, `finding:recorded`,
`finding:disposed`, `plan:amended`, `approval:granted`.

---

## 1. Take the handoff

```bash
python3 "$STATE" status "$RUN_DIR"
```

- `stage: plan` → append your entry event, once:
  ```json
  {"e": "stage:build:entered"}
  ```
- `stage: build` → a previous session already entered. **Do not append it
  again.** The engine accepts a duplicate silently — nothing stops you but this
  sentence — and a second entry event makes the log claim a stage started twice.
  Read the manifest and pick up from the resume map.
- `open` → there is no approved plan yet. Hand back: *"clodex, run dir `<the
  absolute run dir>` — this run is at stage `open`, not build."*
- `verify`, `ship`, `closed` → you are past this stage. Hand back the same way.
  You **cannot** re-enter an earlier stage: the reducer refuses it with *"stage
  would move backwards"*.

**Then, before any batch: confirm the plan is actually approved.** Building
without a standing approval is building against nothing:

```bash
python3 - "$STATE" "$RUN_DIR" <<'PY'
import json, subprocess, sys
snap = json.loads(subprocess.check_output(["python3", sys.argv[1], "rebuild", sys.argv[2]]))
plan = snap["plan"]
live = [a for a in snap["approvals"] if a["revoked"] is None and a["scope"] == "plan"]
print("plan:", plan["path"], "v%s" % plan["version"], (plan["hash"] or "-")[:12])
print("standing plan approval:", bool(live))
print("open findings:", [f["id"] for f in snap["findings"] if f["disposition"] == "open"] or "none")
PY
```

No standing approval, or an open finding → the plan stage did not finish. Say so
and hand back to `clodex`. An approval with `revoked: null` is necessarily bound
to the current `plan.hash` (the engine refuses any other), so that one boolean
is the whole test.

Then **recompute the plan file's hash and compare it to `plan.hash`**:

```bash
python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$PLAN"
```

Different means someone edited the plan without amending. That is §11, not a
shrug.

**Resume map** — read the manifest and match the first row that is true:

| What you find | You are | Go to |
|---|---|---|
| no `batches` entries | nothing started | §2 |
| a batch with `delta_review: null` | opened — whether the implementer ran is a fact about the tree, not the log | §7 first: its check is read-only and tells you which. If `git status --porcelain --untracked-files=all -- <that batch's owned paths>` also prints nothing, no work exists yet — go to §6 and run the implementer. |
| a batch with `delta_review: "fail"` | a review you have not answered | §9 |
| a batch reviewed `pass` with `commit: null` | reviewed, not committed | §10 |
| `plan.amendments` non-empty and its `required_review` unsatisfied | mid amendment | §11, step 6 |
| every planned batch committed and passed | done | §12 |

---

## 2. What the profile forbids you

Read it before you write a contract. Every batch is bound by what it says:

```bash
python3 - "$PROFILE" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
cl, ver, tag, br = p.get("changelog"), p["version"], p["tag"], p["branch"]
print("test (the micro-gate):", p["commands"]["test"] or "(none)")
print("FORBIDDEN changelog:  ", (cl or {}).get("path") or "(repo keeps none)")
print("FORBIDDEN version:    ", ver.get("source") or "(repo is unversioned)")
print("FORBIDDEN tags:       ", (tag["format"] or "?") if tag["enabled"] else "(tagging off)")
print("branch:               ", br["default"], "| work_on_default:", br["work_on_default"],
      "| naming:", br.get("naming") or "-")
PY
```

### The release-owned set — build never touches it

**The changelog, the version source, and tags belong to `clodex-ship`.** Ship
closes them from evidence, with one authoritative timestamp, inside the release
authorization the user approves. A batch that edits them has written the release
before anyone authorized it, and ship cannot tell your edit from its own.

So, in every batch, whatever the plan says:

| Forbidden | Which file, concretely | Owner |
|---|---|---|
| the changelog | the profile's `changelog.path` (e.g. `CHANGELOG.md`) | `clodex-ship` |
| the version | the profile's `version.source` (e.g. `package.json`, `pyproject.toml`, `VERSION`) | `clodex-ship` |
| tags | no `git tag` in this stage, at all | `clodex-ship` |
| the repo profile | `.clodex/profile.json` — never edited, never staged, never committed here | the router, with the user |
| run state | `.clodex/<run-id>/` — only the state engine writes there | the engine |

**May build touch the changelog? No.** Not "usually not", not "unless the plan
asked": no. If the plan's Batches table lists the changelog or the version source
as an owned path, that is a defect in the plan — amend it (§11) with the path
removed, and say why. If the user asks for a changelog entry mid-build, the
answer is that ship writes it from the run's evidence and it will be there.

The lockfile a package manager rewrites, a formatter's incidental reflow, a
config file "while we're in there" — none of these is owned unless the plan says
so. Not owned means forbidden (§5).

---

## 3. The change boundary — before you open your first batch

The `clodex` skill's §5B is **yours to execute**. It could not run earlier: the
router has no owned paths yet, and the approval event it may need binds to a plan
hash the reducer refuses until a plan is recorded. Run it now, once, before the
first `batch:opened`.

Compare the plan's owned paths (its Batches table, all rows) against the dirty
snapshot the user acknowledged at open:

```bash
python3 - "$STATE" "$RUN_DIR" "src/thing/" "docs/plans/<plan file>.md" <<'PY'
import json, subprocess, sys
state, run_dir, owned = sys.argv[1], sys.argv[2], sys.argv[3:]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
dirty = snap["git"]["dirty_at_start"]
hits = sorted({d for d in dirty for o in owned
               if d == o or d.startswith(o.rstrip("/") + "/")})
print("dirty at start:", " ".join(dirty) or "(clean tree)")
print("overlap:       ", " ".join(hits) if hits else "(none)")
PY
```

Pass every owned path of every batch as an argument — an overlap the second batch
will hit is still an overlap.

- **`overlap: (none)`** → proceed to §4. The other dirty paths are not yours:
  never stage them, never revert them, never mention them in a contract except as
  forbidden.
- **Anything listed** → stop and take it to the user under `clodex` §5B, which
  defines the three legal outcomes and the exact commands and event payload for
  each. Do not paraphrase them and do not invent a fourth. Fold is the only one
  that continues this run in place; isolate restarts from the router in a
  worktree; abort ends here.

---

## 4. Branch discipline

You make the run's first commit, so the profile's branch rule binds here.

`work_on_default: true` → commit on the current branch, nothing to do.

`work_on_default: false` → the run works on its own branch. Check where you are,
and if you are on the default branch, say the exact command in chat and run it in
the same turn:

```bash
git rev-parse --abbrev-ref HEAD
git checkout -b clodex/<run-id>        # or whatever branch.naming says, filled in
```

The manifest's `branch` field records where the run *opened*; it is not updated
by a checkout, and no event changes it. Tell the user the branch name you created
— `clodex-ship` will need it, and the manifest will not say it.

---

## 5. The batch contract

A **batch** is one bounded unit of implementation work. `clodex-plan` gave each
one its owned paths and its *Done when*. The contract is the rest, and it is a
**file you write**, not an intention you hold: it goes to the implementer as a
hashed input, and the envelope proves which contract the work was done under.

Write `$RUN_DIR/batch-<N>.contract.md`. Every heading is required.

```markdown
# Batch <N> contract — run <run-id>

Plan: <plan path> v<version>, hash <first 12 of plan.hash>
Done when: <the batch's "Done when", verbatim from the plan's Batches table>

## Owned paths — the only paths this batch may create or modify
- `src/thing/`
- `docs/plans/<plan file>.md`

## Forbidden paths
- `<profile changelog.path>` — release-owned, written by clodex-ship
- `<profile version.source>` — release-owned, written by clodex-ship
- git tags — no `git tag` in this stage, at all
- `.clodex/profile.json` — committed repo state this stage never edits or stages
- `.clodex/<run-id>/` — run state; only the state engine writes there
- `<every other batch's owned paths, listed>`
- `<every path in git.dirty_at_start this batch does not own>` — someone else's
  uncommitted work
- **Everything else in the repo. Not owned means forbidden.**

## Test expectations
- `<profile commands.test>` exits 0 — the micro-gate
- <the new or changed test that proves this batch's Done when, by name>
- <or, when commands.test is null: "this repo has no test command; the delta
  review is the whole gate", and say what you will read instead>
```

Three things make this contract useful rather than decorative:

1. **Owned paths are copied from the plan, not reinterpreted.** If they are
   wrong or insufficient, that is an amendment (§11), not a quiet widening.
2. **Forbidden paths are named literally**, filled in from §2's output — not
   "release files".
3. **Test expectations are commands**, not adjectives. "Tests pass" is not a test
   expectation; `python3 -m unittest discover -s tests` exiting 0 is.

Batches run one at a time, in the plan's order. **The next batch does not open
until the current one is reviewed `pass` and committed** (§12's exit check is the
same rule).

---

## 6. Open the batch, then run the implementer

Append, with the owned paths exactly as the contract lists them:

```json
{"e": "batch:opened", "id": 1, "owned_paths": ["src/thing/", "docs/plans/2026-08-11-thing.md"]}
```

Ids are unique for the life of the run: a second `batch:opened` with the same id
is refused — *"batch 1 is already open"*. A batch is never re-opened; work that
has to be redone gets a **new** batch (§11).

Write the prompt to `$RUN_DIR/batch-<N>.prompt.md` with your file-writing tool —
never as a shell string. It has exactly these parts, in this order:

```markdown
Implement one batch of an approved plan. The repo root is your working directory
and you may edit files in it directly.

Plan: <the value of $PLAN> — read it. This is batch <N> of its Batches table.
Contract: <$RUN_DIR/batch-<N>.contract.md> — read it. It binds you.

What to build:
<the batch's Done when, plus the two or three sentences of the plan that give it
context. Do not restate the plan; it is a file you just told them to read.>

Rules, and they override anything the plan implies:
- Create or modify only the contract's owned paths. Nothing else — not a config,
  not a lockfile, not a neighbouring module you noticed on the way past.
- Never touch a forbidden path.
- Never run `git add`, `git commit`, `git tag`, `git push`, `git checkout`, or
  `git stash`. You edit the working tree; the orchestrator reviews and commits.
- This tree contains other people's uncommitted work. Leave it exactly as it is.

Done means: <the profile's test command> exits 0, and <the batch's test
expectation>.

Report what you changed, file by file, and anything you could not finish. Set
status `partial` if any part of this assignment is undone — a `complete` you
cannot stand behind costs more to unwind than a `partial` costs to resume.
```

Run it. The implementer role runs in codex's `workspace-write` sandbox and edits
files directly:

```bash
CONTRACT="$RUN_DIR/batch-1.contract.md"
PROMPT="$RUN_DIR/batch-1.prompt.md"
OUT="$(bash "$RUNNER" --role implementer --repo "$REPO" \
        --prompt-file "$PROMPT" --input "$CONTRACT" --input "$PLAN")"; RC=$?
printf 'rc=%s line=%s\n' "$RC" "$OUT"
ENVELOPE="${OUT#* }"     # strip the FIRST word only — a repo path may contain spaces
```

The runner prints one line, `"<status> <envelope-path>"`, and **its exit code is
the authority**. Never read status out of prose, stderr, or the model's summary.

| rc | Status | What to do |
|---|---|---|
| 0 | `complete` | Go to §7. "Complete" means it finished its assignment, not that the work is right. |
| 2 | `partial` | It stopped short. Resume: the runner printed a runnable one-command resume line on stderr — surface it and run it. Do not start a fresh invocation; the work is half-done in the tree. |
| 3 | `interrupted` | Same as partial: resume with the printed command. |
| 1 | `failed` | Read the envelope's `error` and `output.stderr`. The tree may still have been edited — run §7 before deciding anything. |
| 64 | usage error | You called the runner wrong. Fix the arguments. |
| — | empty `$OUT` | The runner died before writing an envelope. Read its stderr. |

Confirm the envelope worked from the contract you wrote, the same way
`clodex-plan` confirms a review hashed the current plan:

```bash
python3 - "$ENVELOPE" "$CONTRACT" <<'PY'
import hashlib, json, sys
env = json.load(open(sys.argv[1]))
want = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
print("status:", env["status"], "invocation:", env["invocation_id"])
print("worked from this exact contract:", any(i["sha256"] == want for i in env["inputs"]))
for f in env["findings"]:
    print(f["id"], f["severity"], "|", f["summary"], "|", f["location"])
PY
```

An implementer may report findings of its own — something it could not do, a
defect it noticed. Record and dispose them like any other (§9).

---

## 7. The boundary check — did it stay inside the contract?

Run this **every time the implementer returns**, whatever its status. A
`workspace-write` sandbox can write anywhere in the repo; the contract is a
promise, and this is the check.

```bash
python3 - "$STATE" "$RUN_DIR" "src/thing/" "docs/plans/<plan file>.md" <<'PY'
import json, subprocess, sys
state, run_dir, owned = sys.argv[1], sys.argv[2], sys.argv[3:]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
acknowledged = set(snap["git"]["dirty_at_start"])
raw = subprocess.check_output(
    ["git", "status", "--porcelain", "-z", "--untracked-files=all"]).decode()
fields, i, stray = raw.split("\0"), 0, []
while i < len(fields) and fields[i]:
    entry = fields[i]; i += 1
    xy, path = entry[:2], entry[3:]
    if xy[0] in ("R", "C"):        # rename/copy: the origin path is its own field
        i += 1
    if any(path == o or path.startswith(o.rstrip("/") + "/") for o in owned):
        continue
    stray.append((path, path in acknowledged))
for path, ack in sorted(stray):
    print("OUTSIDE  %-38s %s" % (path, "acknowledged dirt" if ack else "NOT owned by this batch"))
unexplained = [p for p, ack in stray if not ack]
print("clean — the contract held" if not unexplained
      else "STOP — %d path(s) the contract does not allow: %s"
           % (len(unexplained), " ".join(unexplained)))
PY
```

Pass this batch's owned paths only. `--untracked-files=all` is not optional:
plain `git status --porcelain` collapses an untracked directory to `docs/`, so a
new file at an owned path — the plan file, most runs — reads as a stray and the
check cries wolf on its first use. What comes back:

| Result | What it means | What to do |
|---|---|---|
| `clean — the contract held` | nothing changed outside the owned paths except dirt the run already acknowledged | §8 |
| `STOP` + a path marked **NOT owned by this batch** | the implementer strayed | Stop. This is a scope change, and scope changes are the user's call. Capture it, show it, ask (below). |
| a path marked **acknowledged dirt** | it was already dirty when the run opened | Leave it alone. It is not yours to stage, revert, or clean. The check cannot tell "still only the user's edit" from "the implementer edited it too" — if you suspect the latter, diff it against the capture §3 made and treat it as a stray. |
| `.clodex/profile.json` | the router repaired the profile and did not commit it, or the user edited it | Leave it, and say so in chat. It is the one file `git check-ignore` lets through, and it is never yours to stage (§2). |

For a stray path, capture the evidence before anything changes:

```bash
git diff -- <stray tracked paths> > "$RUN_DIR/batch-<N>.stray.diff"
git status --short -- <stray paths>
```

Then put it to the user with the diff and exactly two ways forward: **the stray
edit is needed** — that is a scope change, so amend the plan (§11) to own the
path, and the work continues; or **it is not needed** — restore those paths and
re-run the batch. Only restore after they say so, and only paths that were clean
at start and are not in `dirty_at_start`:

```bash
git checkout -- <stray tracked paths>     # tracked, was clean at start
mv <stray untracked path> "$RUN_DIR/stray/"   # untracked: move aside, never rm
```

A release-owned file among the strays (§2) is the one case where the answer is
not open: it is restored, never folded. Ship owns it.

---

## 8. The micro-gate

**The gate is the profile's `commands.test`, green.** One command, run from the
repo root:

```bash
TEST_CMD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commands"]["test"] or "")' "$PROFILE")"
[ -n "$TEST_CMD" ] && bash -c "$TEST_CMD"; echo "gate rc=$?"
```

- **rc 0** → green. Continue to §9.
- **non-zero** → red. The delta does not leave this stage. Fix it — yourself, or
  by running the implementer again with the failure output in the prompt — and
  run the gate again. Do not review a red delta, do not commit one, and never
  "fix" a gate by changing the test to match the code unless the plan says the
  test was wrong.
- **`commands.test` is null** → there is no gate to run. Say so out loud, in
  chat, once per run: *"this repo's profile has no test command, so batches have
  no automated micro-gate; the delta review is the whole gate."* The verdict in
  §9 is then `pass-no-test-command`, which is how the manifest tells
  `clodex-verify` and `clodex-ship` that nothing was executed here.

`lint` and `typecheck` are `clodex-verify`'s gates. Run them here only if this
batch's contract named them as a test expectation; otherwise leave them, and do
not report their state as if it were a gate you passed.

---

## 9. The delta review — every batch, before the next one opens

"Locally reviewed" is not a feeling. It is these three things, in order.

**(a) Stage the owned paths and read the whole delta yourself.**

```bash
git add -- src/thing/ docs/plans/<plan file>.md      # explicit paths, never -A, never .
git status --short                                    # see what else is in the index
git diff --cached -- src/thing/ docs/plans/<plan file>.md > "$RUN_DIR/batch-<N>.diff"
```

Something you do not own may already be staged — a user who ran `git add` on
their own work before the run. **Do not unstage it**; their index is theirs. §10
commits by pathspec, which cannot pick it up.

Read that file end to end and answer all five, in writing, in chat:

1. Is every changed file an owned path? (§7 said yes; the staged diff is the
   second look, and it is the one that becomes a commit.)
2. Does it meet the batch's *Done when* — the checkable sentence, not the vibe?
3. Is anything stubbed, `TODO`-ed, hardcoded, or commented out that the batch
   claims as done?
4. Does it add a credential, token, or key **value** anywhere? Names are fine;
   values never are.
5. Did the micro-gate cover this delta, or does it pass without touching it?

**(b) Run the Codex code-reviewer role when the delta is consequential.**
Consequential is checkable, not a mood — any one of these makes it so:

- it changes anything that runs outside the test suite (any file that is not a
  test, a fixture, a doc, or the plan file); or
- it touches authentication, credentials, permissions, money, data deletion or
  migration, or an external side effect (a network call, a write to a shared
  system); or
- the plan's Risks section names any of this batch's owned paths.

A delta that is only tests, fixtures, docs, comments, or the plan file is not
consequential; your own read (a) is the whole review, and you say so in the
event's note. Everything else gets the reviewer:

```bash
REVIEW_PROMPT="$RUN_DIR/batch-<N>.review.prompt.md"     # written with your file tool
OUT="$(bash "$RUNNER" --role code-reviewer --repo "$REPO" \
        --prompt-file "$REVIEW_PROMPT" --input "$RUN_DIR/batch-<N>.diff" --input "$PLAN")"; RC=$?
ENVELOPE="${OUT#* }"
```

The prompt says: review this diff against this plan's batch <N> and its *Done
when*; report findings only; do not edit files; blocker/high/medium for anything
that would produce wrong or unshippable work, low/info for improvements. The rc
table in §6 applies unchanged — only a `complete` round is a review.

**(c) Dispose every finding.** Record each one, then dispose it `fixed`,
`accepted`, or `rejected`. The rules are `clodex-plan` §9 and they are identical
here, including that only the user may accept or reject one. Namespace ids by
batch, because the runner mints `F001` fresh every invocation:

```json
{"e": "finding:recorded", "id": "b1-F001", "source": "code-reviewer",
 "severity": "high", "summary": "<one line, verbatim from the envelope>"}
```

`source` is the Codex role that produced it — `code-reviewer`, or `implementer`
for a finding the implementer reported itself. A second review round on the same
batch uses `b1r2-F001`.

### The verdict

Append it as soon as you have it, before you commit:

```json
{"e": "batch:reviewed", "id": 1, "delta_review": "pass",
 "note": "gate green; code-reviewer complete, 2 findings fixed",
 "invocation": "<the review invocation id, or omitted when there was no review>"}
```

| `delta_review` | When |
|---|---|
| `pass` | micro-gate green, your five answers clean, and every finding from this batch disposed |
| `pass-no-test-command` | the same, in a repo whose `commands.test` is null (§8) |
| `fail` | anything else |

**When it fails.** Append `fail` first — the log records the verdict you actually
reached, not the one you ended up with. Then fix it inside this same batch: you
fix it, or you run the implementer again with the findings in the prompt (a new
invocation, not `--resume`; the assignment changed). Re-run §7, §8, and §9, then
append `batch:reviewed` again with `pass`. The later event wins;
`batches[].delta_review` shows the current verdict and the log shows both.

**The next batch does not open while any batch's `delta_review` is not a pass.**
That is the rule the whole stage rests on: a delta nobody reviewed cannot be
distinguished, later, from one that was fine.

If the fix turns out to require changing the plan rather than the code — the
finding is right and the plan is wrong — that is §11.

---

## 10. Commit the batch

Only after a `pass` verdict, and immediately after it: a commit is a record of a
reviewed delta, so anything you change between the verdict and the commit makes
the review stale and sends you back to §9.

```bash
git commit -m "<type>(<scope>): <the batch's Done when, in one line>" \
           -- src/thing/ docs/plans/<plan file>.md      # the batch's owned paths
COMMIT="$(git rev-parse HEAD)"
git show --stat --oneline "$COMMIT"     # read it: owned paths only, nothing else
```

**Name the paths on the commit too, not just on the `git add`.** A bare `git
commit -m` commits the whole index, and the index is not only yours: a user who
staged their own work before the run has it swept into your commit, silently,
and `git show` is where you would find out. With the pathspec, git commits those
paths and nothing else, and their staged work stays staged.

Never `git add -A`, `git add .`, or `git commit -a`, and never `git add <dir>`
when that directory holds files the batch does not own. The change boundary
exists so that other people's work never lands in a clodex commit, and one
convenience flag undoes all of it.

Then append:

```json
{"e": "batch:committed", "id": 1, "commit": "<the full sha from git rev-parse HEAD>"}
```

The batch must already exist — `batch:committed` for an unknown id is refused
with *"no such batch: 9"*.

Now go back to §5 for the next batch, or to §12 if that was the last one.

---

## 11. When an assumption changes: the amendment protocol

Amend when the **plan's text is now false or incomplete**:

- an entry in its Assumptions section turns out not to hold;
- a batch's *Done when* cannot be met as written;
- the work needs a path no batch owns (including a stray the user wants kept, §7);
- an evidence class the plan declared cannot be produced;
- a review finding is right and the fix is in the plan, not the code.

Do **not** amend for something the plan is simply silent about. An implementation
detail it never specified is work, not drift: decide it, write it in the batch
contract, and carry on.

**You cannot hand this back to `clodex-plan`.** The reducer refuses a backwards
stage transition — *"stage would move backwards, build -> plan"* — so the
amendment, its re-review, and its re-approval all happen here.

### Four effects. All four, every time.

| # | Effect | Where you see it |
|---|---|---|
| 1 | **The plan hash is superseded.** A new version, a new content hash, and the amendment recorded with its note. | `plan.hash`, `plan.version`, `plan.amendments[]` |
| 2 | **Every approval bound to the old hash is revoked, mechanically.** The reducer sweeps them when the amendment is reduced and marks each **in place** with the superseding hash — kept as revoked, never dropped. It takes the original plan approval, and any `dirty-fold` approval from §3, not just recent ones. | `approvals[].revoked` |
| 3 | **The amendment declares its required re-review.** `clodex-ship` is blocked until that re-review exists against the new hash. | `plan.amendments[].required_review` |
| 4 | **Completed work the change affects is identified** — by batch id and commit sha — and redone in a new batch. | the amendment note, plus the new `batch:opened` |

### The recipe

1. **Stop.** Do not open the next batch and do not keep editing. Say what
   changed, in one message: the assumption, the evidence that broke it, and what
   in the plan is now false.

2. **Identify the affected completed work.** For every batch already committed,
   ask whether the change touches its owned paths or invalidates its *Done when*:

   ```bash
   python3 "$STATE" rebuild "$RUN_DIR" | python3 -c '
   import json,sys
   for b in json.load(sys.stdin)["batches"]:
       print(b["id"], b["commit"], b["delta_review"], b["owned_paths"])'
   ```

   Name them by id and sha in the amendment note. "Nothing completed is affected"
   is a real answer, and it goes in the note too.

3. **Edit the plan file** — the Assumptions entry that broke, plus every section
   the change reaches (Scope, Batches, Evidence, Direction). Bump its version
   line.

4. **Recompute the hash and append `plan:amended`:**

   ```json
   {"e": "plan:amended", "version": 2,
    "path": "docs/plans/<plan file>.md",
    "hash": "<new sha256>",
    "note": "assumption 3 (the API returns ids) is false; batch 1 (sha 1a2b3c4) reworked in batch 3",
    "required_review": ["plan-reviewer", "code-reviewer"]}
   ```

   `required_review` names Codex **roles** and the vocabulary is fixed outside
   this skill: `properties.role.enum` in `$CLODEX_HOME/runner/envelope.schema.json`.
   Whether an amendment is **material** — and therefore whether it needs a
   plan-review round at all — is `clodex-plan` §6's test, unchanged: material
   means it touched Brief, Scope, Batches, Evidence, or Direction. Add
   `code-reviewer` when the amendment invalidates a committed batch's review, so
   the redone work gets looked at against the new plan.

   Two refusals to expect: *"plan:amended must carry the new plan hash"* and
   *"plan:amended does not supersede anything: the hash is unchanged"*. Both mean
   you appended before saving the file.

5. **Look at what it revoked** — this is effect 2, and it is worth reading rather
   than assuming:

   ```bash
   python3 "$STATE" rebuild "$RUN_DIR" | python3 -c '
   import json,sys
   for a in json.load(sys.stdin)["approvals"]:
       r=a["revoked"]
       print(a["scope"], "revoked" if r else "STANDING", r["superseding_hash"][:8] if r else "")'
   ```

6. **Satisfy the declared re-review.** `plan-reviewer` → one round against the
   new plan file, run and read exactly as `clodex-plan` §8 describes, with every
   finding disposed per §9. `code-reviewer` → the affected batches' deltas
   reviewed again against the new plan.

7. **Re-approve, in one message.** Present: what changed and why, the affected
   completed work, the re-review outcome, and — when §3 folded pre-existing work
   — that the `dirty-fold` acknowledgment was revoked with everything else and is
   being re-granted. Then append, bound to the **new** hash:

   ```json
   {"e": "approval:granted", "scope": "plan", "by": "user",
    "plan_version": 2, "plan_hash": "<the new sha256, recomputed from the file>"}
   ```

   This reduces to exactly the entry `clodex-plan`'s `plan:approved` produces —
   same handler, same `scope: "plan"` — so the standing-approval test in §1 and
   at ship is satisfied either way. An approval against the superseded hash is
   refused: *"approval binds to plan hash 'X' but the current plan hash is 'Y'"*.
   Re-grant the `dirty-fold` approval too, with its own `approval:granted`, if
   the folded work is still in scope.

8. **Redo the affected work in a new batch.** Batch ids are never reused —
   `batch:opened` refuses a duplicate. Open the next free id with a fresh contract
   (§5). Its owned paths may overlap an earlier batch's on purpose: the plan-level
   rule that batches are disjoint is about parallel scope, and a remediation batch
   deliberately revisits committed work. The amendment note is the record of why.

---

## 12. Exit

Check it from the manifest, not from memory:

```bash
python3 - "$STATE" "$RUN_DIR" <<'PY'
import json, subprocess, sys
snap = json.loads(subprocess.check_output(["python3", sys.argv[1], "rebuild", sys.argv[2]]))
ok = True
for b in snap["batches"]:
    good = bool(b["commit"]) and b["delta_review"] in ("pass", "pass-no-test-command")
    ok &= good
    print("batch %-4s commit=%-9s delta_review=%-22s %s" % (
        b["id"], (b["commit"] or "-")[:8], b["delta_review"], "ok" if good else "NOT DONE"))
open_f = [f["id"] for f in snap["findings"] if f["disposition"] == "open"]
live = [a for a in snap["approvals"] if a["revoked"] is None and a["scope"] == "plan"]
print("open findings:", " ".join(open_f) or "(none)")
print("standing plan approval on the current hash:", bool(live))
print("declared re-reviews:", [r for a in snap["plan"]["amendments"] for r in a["required_review"]] or "(none)")
ok &= not open_f and bool(live)
print("BUILD COMPLETE" if ok else "NOT DONE")
PY
```

All five must hold:

1. Every batch in the plan's Batches table has been opened, and every batch in
   the manifest has a `commit` and a passing `delta_review`.
2. No finding is `open`.
3. A plan approval stands on the current hash, and every re-review an amendment
   declared has actually been run. The manifest cannot answer the second — no
   event records "a review happened" — so the evidence is the envelope on disk: a
   `complete` one, in that role, whose inputs hash the **current** plan file.

   ```bash
   python3 - "$PLAN" "$REPO/.clodex/runner" <<'PY'
   import glob, hashlib, json, os, sys
   want = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
   for path in sorted(glob.glob(os.path.join(sys.argv[2], "*", "*.envelope.json"))):
       env = json.load(open(path))
       if env["status"] == "complete" and any(i["sha256"] == want for i in env["inputs"]):
           print("ran against the current plan:", env["role"], env["invocation_id"])
   PY
   ```

   (Python does the globbing, so this behaves the same in a shell that errors on
   an unmatched glob.) An `implementer` row is expected — §6 passes the plan as
   an input too. What matters is that every role in every amendment's
   `required_review` appears. One that does not is §11 step 6, not a judgment
   call.
4. `git status --porcelain --untracked-files=all -- <every owned path>` prints
   nothing: no owned path is left uncommitted. A plan file amended after its
   batch was committed is the usual culprit — it belongs to the remediation
   batch.
5. Every plan item is done **or** amended. An item you neither built nor amended
   is not an exit; it is §11.

Then hand off the way the router does: invoke `clodex-verify` and give it the
absolute run directory — *"clodex-verify, run dir
`<repo>/.clodex/r-2026-08-11-a`"*. Tell it the branch you are on if §4 created
one, since the manifest does not record it.

Do not append `stage:verify:entered`. Each stage appends its own entry event.

Carry nothing else forward in prose. If a fact matters to verify, it is in the
plan file, a commit, or the log — or it does not exist.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Writing the changelog, bumping the version, or tagging "while the context is fresh" | All three are `clodex-ship`'s, always (§2). A plan that assigns them to a batch is a plan to amend. |
| `git add -A`, `git add .`, or `git commit -a` | Stage the batch's owned paths by name (§9). The tree holds other people's work and one flag sweeps it in. |
| A bare `git commit -m` after staging correctly | It commits the **whole index**, including anything the user staged before the run. Name the owned paths on the commit as well (§10). |
| Staging or committing `.clodex/profile.json` | This stage never edits, stages, or commits the profile. `git add` takes the whole file, including an edit that is not yours. |
| Opening the next batch with the current one unreviewed or uncommitted | One batch at a time; the verdict and the commit come first (§9, §12). |
| Reusing a batch id to redo work | Refused: *"batch 1 is already open"*. Redone work is a new batch with a new contract (§11). |
| Treating the implementer's `complete` as "the code is right" | `complete` means it finished its assignment. §7, §8, and §9 decide whether the work is right. |
| Reading the implementer's status out of its prose or stderr | The runner's exit code and the envelope decide. A `partial` is resumed, not restarted (§6). |
| Widening owned paths because the work "obviously" needs one more file | That is a scope change: amend (§11). The plan is the thing that got approved. |
| Amending without re-approving, because the change was small | Every amendment revokes every approval bound to the old hash — the plan approval included. There is no amendment that costs nothing (§11). |
| Handing back to `clodex-plan` to fix the plan | Refused: *"stage would move backwards, build -> plan"*. Build runs the amendment itself. |
| Reverting or stashing a dirty file that was not yours | Acknowledged dirt is left exactly as it is (§7). Only the user moves their own work. |
| Recording `delta_review: "pass"` in a repo with no test command | `pass-no-test-command`, so verify and ship can see that nothing executed (§8). |
| Inventing an event name | The vocabulary is frozen at 23 names and the reducer refuses anything else. This stage appends eight of them (§0). |
