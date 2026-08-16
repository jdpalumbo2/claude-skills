---
name: clodex-verify
description: Use when the clodex router or clodex-build hands off a run at stage `verify`, when a run's declared evidence classes have not all been produced or written off, or when a resumed run's manifest shows stage `verify`.
---

# clodex-verify — evidence per class, debt for the rest, no gate

## Overview

This stage turns "the batches are committed" into proof, and it owes the run
exactly two kinds of fact — both in the event log, neither in a transcript:

| Fact | Event | In the run manifest |
|---|---|---|
| a declared class was produced, and what showed it | `verification:evidence` | `verification.evidence[]` |
| a declared class was **not** produced, why, and what that risks | `verification:debt` | `verification.debt[]` |

**Every class `clodex-plan` declared ends in exactly one of those two states.
Never neither, never both.** §10 checks that property mechanically.

### This stage has no gate

**Verify records debt. It never accepts, waives, or blocks on it.** There is no
"is this debt OK?" question in this document, and you must not invent one: a run
with three debt entries and a run with none both leave this stage the same way —
handed to `clodex-ship`.

**Debt is accepted in exactly one place: `clodex-ship`'s release
authorization**, once, by the user, alongside the exact external actions they are
authorizing. That is the design's single binding debt gate. Asking the user to
approve debt here would double the gate and leave ship approving something
already half-approved — so you do not ask. You write it down, plainly, and you
say it out loud in the handoff.

### Where this stage ends

You do not commit, you do not edit tracked files, and you do not fix code (§2).
You do not write the changelog, bump the version, tag, push, or deploy — that is
`clodex-ship`. You read the `deploy` block of the repo's committed profile
(`<repo>/.clodex/profile.json`) only to know what ship will do, never to do any
of it.

You arrive here from `clodex` or from `clodex-build`, which hands you an absolute
run directory. If you were invoked without one, **stop and invoke `clodex`** — do
not go looking for a run yourself.

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
runs from `$REPO`: a test command, a lint command, and every `git` call resolve
relative paths against the current directory, so from a subdirectory they answer
the wrong question.

Engine verbs, payload on **stdin**:

```bash
python3 "$STATE" status  "$RUN_DIR"     # human summary; its `verify:` line counts evidence and debt
python3 "$STATE" rebuild "$RUN_DIR"     # the manifest: full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
```

"The **manifest**" below always means the output of `rebuild`. Append exit codes
and the lock rules live in the `clodex` skill, §"Paths and commands" and §2 —
read them there. The one that bites: exit **3** means the event *is* durably
logged; run `rebuild`, do not retry.

Write every event to a file with your file-writing tool and pipe the file in.
A `reason`, a `risk`, and a command line all contain quotes; shell interpolation
will corrupt them.

This stage appends five event types and no others: `stage:verify:entered`,
`verification:evidence`, `verification:debt`, `finding:recorded`,
`finding:disposed`.

**Artifacts you produce — logs, screenshots, diffs, prompts — go in `$RUN_DIR`,
which is gitignored.** The runner writes its own envelopes and logs under
`${CLODEX_RUNNER_STATE_DIR:-$REPO/.clodex/runner}`, also gitignored. Nothing this
stage produces lands anywhere else in the tree (§2).

---

## 1. Take the handoff

```bash
python3 "$STATE" status "$RUN_DIR"
```

- `stage: build` → append your entry event, once:
  ```json
  {"e": "stage:verify:entered"}
  ```
- `stage: verify` → a previous session already entered. **Do not append it
  again.** The engine accepts a duplicate silently — nothing stops you but this
  sentence — and a second entry event makes the log claim a stage started twice.
  Read the manifest and pick up from the resume map.
- `open`, `plan` → the work is not built yet. Hand back: *"clodex, run dir `<the
  absolute run dir>` — this run is at stage `<X>`, not verify."*
- `ship`, `closed` → you are past this stage. Hand back the same way. You
  **cannot** re-enter an earlier stage: the reducer refuses it with *"stage would
  move backwards"*.

**Resume map** — read what the run already has, and match the first row that is
true:

```bash
python3 "$STATE" rebuild "$RUN_DIR" | python3 -c '
import json,sys
v = json.load(sys.stdin)["verification"]
for d in v["declared"]: print("declared", d.get("class"), "|", d.get("proof"))
for e in v["evidence"]: print("evidence", e.get("class"), "|", e.get("how"))
for d in v["debt"]:     print("debt    ", d.get("class"), "|", d.get("reason"))'
```

| What you find | You are | Go to |
|---|---|---|
| no `declared` lines | the plan declared no evidence — there is no definition of done to prove | Stop. This run cannot reach ship and cannot be left open: the plan stage is closed to you, and a run parked here blocks the next one (§8, outcome A). Hand back to `clodex` and ask it to **close** the run — or abandon it, if the work is not going ahead — naming the plan defect as the reason. |
| no `evidence` and no `debt` lines | nothing produced yet | §2 |
| some classes covered, some not | mid-stage | §4, then §5 for **only the uncovered classes** |
| a finding with `disposition: "open"` | a finding you have not answered | §8 |
| every declared class covered | done | §10 |
| `$PLAN` is empty — the manifest's `plan.path` is null | the run is malformed: build cannot have run without a recorded plan, and nothing here can be checked against a plan that is not there | Stop, as in the first row: hand back to `clodex` and ask it to close or abandon the run, naming the null `plan.path`. §7 sends you here too. |

**The reducer does not de-duplicate.** A session that died mid-stage and resumed
will append the same evidence twice unless you read the lists above first and
append only what is missing. The natural key for an evidence item is
`(class, how)` — the class plus the exact command or action — and for a debt
entry it is `class`, since a class is deferred once or not at all.

---

## 2. What this stage may not do

**Verify never commits and never modifies a tracked file.** Commit authority
lives in exactly two places in clodex: `clodex-build` makes batch commits, and
`clodex-ship` makes the release commit. Not here, for any reason, including a
one-line fix that is obviously right.

| Never, in this stage | Why |
|---|---|
| `git commit`, `git add`, `git tag`, `git push`, `git checkout`, `git stash` | Commits belong to build and ship. A commit here is a delta nobody reviewed. |
| Editing code, a test, a fixture, or a config to make a gate pass | That is build's work, under a batch contract, with a delta review. Here it is a **finding** (§8). |
| Writing the changelog, bumping the version, tagging, deploying | `clodex-ship` closes all of those from this stage's evidence, under one authorization. |
| Writing an artifact anywhere but `$RUN_DIR` or the runner's own state dir | Screenshots, logs, and diffs go in `$RUN_DIR`; the runner writes its envelopes and logs under `${CLODEX_RUNNER_STATE_DIR:-<repo>/.clodex/runner}` itself. Both are gitignored. An artifact anywhere else becomes someone's next dirty-file problem. |
| `codex --role implementer` | The implementer runs `workspace-write`. Every delegation this stage makes is read-only (§7). |

If verification shows that code or tests must change, that is a finding, it goes
in the log, and it goes to the user — §8 has the whole procedure and the thing
you cannot do (hand the run back to `build`).

---

## 3. What you must prove

Two independent lists, and you run both. Read them together before you start:

```bash
python3 - "$STATE" "$RUN_DIR" "$PROFILE" <<'PY'
import json, subprocess, sys
state, run_dir, profile = sys.argv[1], sys.argv[2], sys.argv[3]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
prof = json.load(open(profile))
print("declared classes (the plan's — §5):")
for d in snap["verification"]["declared"]:
    print("   %-10s %s" % (d.get("class"), d.get("proof")))
print("profile gates (the repo's — §4):")
for name in ("test", "lint", "typecheck", "build"):
    print("   %-10s %s" % (name, prof["commands"][name] or "(null — nothing to run)"))
print("profile default classes:", ", ".join(prof["evidence"]["default_classes"]) or "(none)")
dep = prof["deploy"]
print("deploy (ship's, not yours):", "(this repo does not deploy)" if dep is None
      else "%s | trigger %s | %d verify_live check(s)" % (dep["target"], dep["trigger"], len(dep["verify_live"])))
PY
```

- **The declared classes** come from `clodex-plan` §10 and are what the user
  approved as the definition of done. The vocabulary is exactly four:
  `tests` · `real-data` · `live-check` · `visual`. There is no fifth, and you
  never invent one.
- **The profile gates** are the repo's own commands. They run **in addition to**
  the declared classes, every run, whether or not `tests` was declared: a repo's
  lint and typecheck catch things a plan's evidence table never thought about.

A class the plan declared that is **not** in the profile's defaults still runs.
A profile default the plan dropped does **not** come back — the plan argued the
drop in writing and the user approved that argument with the plan hash. Your job
is the declared list, not the default list.

---

## 4. Run the profile's gates

Four commands, from the repo root, each into its own log:

```bash
for GATE in test lint typecheck build; do
    CMD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commands"][sys.argv[2]] or "")' "$PROFILE" "$GATE")"
    if [ -n "$CMD" ]; then
        bash -c "$CMD" > "$RUN_DIR/gate-$GATE.log" 2>&1
        printf 'gate %-10s rc=%s   %s\n' "$GATE" "$?" "$CMD"
    else
        printf 'gate %-10s null in this profile — nothing to run, not a failure\n' "$GATE"
    fi
done
```

**Use the `if`/`else`, not `[ -n "$CMD" ] && bash -c "$CMD"; printf ... "$?"`.**
With a null command the test itself is what fails, so the one-liner prints
`rc=1` — a red gate in a repo that has no such gate, sending you to debug a
failure that does not exist.

- **Every gate rc 0** → §5.
- **A null gate** → not a failure and not debt. The repo genuinely has no such
  command; the profile says so as a recorded fact. Say it once in chat and move
  on. It becomes debt only when a *declared class* depended on it — a plan that
  declared `tests` in a repo whose `commands.test` is null has no way to produce
  that class, which §5 records as debt with that as the reason.
- **A gate rc non-zero** → stop and read `$RUN_DIR/gate-<gate>.log`. This is a
  **finding**, not debt (§9 draws that line: debt is evidence deferred, a red
  gate is evidence produced and negative). Do not fix it here — §8.

Two rules the printed block obeys. **Each rc must be the gate's own**: the
redirect form above is safe, but the moment a gate is piped (`| tail`,
`| tee`) the rc printed must be `${PIPESTATUS[0]}` under `set -o pipefail` —
`$?` after a pipe belongs to the last command, and it has printed `rc=0` for
an npm run that died on ENOENT. And **each green gate's line carries the
suite's own pass count**, quoted from its log (`142 passed`, `57/0/1`): a
bare rc is not evidence, and §5's `result` field demands the count anyway.

Keep the printed block. §5 quotes it into the `tests` evidence item, and §11
repeats it to ship.

---

## 5. Produce evidence, class by class

**Reconcile telemetry first** — `python3 "$STATE" telemetry-sync "$RUN_DIR"
"$REPO/.clodex/runner"` (`clodex` → Telemetry). An orphan build left behind, or
a worker round this stage runs, gets its printed `codex` block attached to one
of the evidence appends below — `duration_s` and `status` copied from the
envelope, never estimated or asserted. This is the stage's last stop with
plenty of carriers; run it now, not at exit.

Walk the declared list from §3. For each class, do the recipe, then append one
item — and only for classes not already covered (§1):

```json
{"e": "verification:evidence",
 "item": {"class": "tests",
          "how": "python3 -m unittest discover -s tests",
          "result": "rc=0, 142 tests; includes test_parser_rejects_empty, which is batch 2's Done when. lint rc=0, typecheck null, build rc=0. Logs in <run dir>/gate-*.log"}}
```

Three fields, all required, all non-empty:

| Field | Is | Is not |
|---|---|---|
| `class` | one of `tests`, `real-data`, `live-check`, `visual` | a name you made up |
| `how` | the exact command run, or the concrete action taken | "ran the tests" |
| `result` | what it showed — exit code, counts, the observation, the artifact path | "passed" |

`result` must answer the **plan's declared `proof`**, not merely report that
something ran. The check is not a feeling: **if the declared proof names a
thing — a test, an input file, a URL, a screen — `result` names that same
thing.** A plan that declared *"tests — covering the new parser"* is not
satisfied by a green suite that never touches the parser; that gap is a finding
(§8), and a suite you cannot make cover it is debt (§9).

### tests

§4's run is normally the whole of it: quote the gate lines into `how` and
`result`, and name the test that proves the plan's *Done when*. If the declared
proof names something beyond the profile's test command — an integration suite,
a specific target — run that too and append a second `tests` item for it, keyed
by its own `how`.

When the run's history contains a rebase or merge resolution, the `tests`
evidence must also include the **test-inventory diff** build §8 produced (or
produce one now: test names pre vs post, diffed). Counts survive a silently
deleted test; the name list does not.

When the suite is Python, `result` must also carry the **resolved module
path** — `python3 -c 'import <package>; print(<package>.__file__)'` — proving
the gate imported *this checkout's* code. In a worktree wired up with
symlinked venvs, a suite can run green against the parent checkout's copy of
the package; the counts look identical and the gate proves someone else's
tree. The printed `__file__` is what tells them apart, and an evidence item
without it does not prove what it claims in any multi-checkout repo.

Debt when: the profile's `commands.test` is null and no suite exists to run, or
the suite cannot run in this environment (a missing toolchain the router's
preflight did not cover).

### real-data

Run the change against the production-shaped input the plan's Evidence table
named — a sanitized export, a recorded fixture, a real file from the system this
code will meet.

**Read-only, always.** Live-data mutation is a human-owned decision and it is not
yours to take, so a check that would write to a production system is not
something you run: it is debt whose `reason` says so, unless the user runs it
themselves and tells you what they saw.

Credentials are checked by **name**, never printed:

```bash
printenv SOME_API_TOKEN >/dev/null && echo "SOME_API_TOKEN is set" || echo "SOME_API_TOKEN is NOT set"
```

Debt when: the input does not exist and obtaining it needs access you do not
have; a required credential is unset; the only real-data path would mutate a
live system.

### live-check

The deployed thing, observed working. Feasible **here** only when something is
already serving this change — a preview or staging deployment, or the service
running locally against production-shaped configuration.

**Do not run the profile's `deploy.verify_live` checks against the currently
live release and call it evidence.** Before ship deploys, those checks pass
against the *old* version: you would be recording proof that the thing you did
not change is still up. Run one only if it is version-aware — if it asserts the
new version, tag, or build id, and would fail today.

Debt when: nothing serves this change yet (the common case — see §6), the
profile's `deploy` is null, or `deploy.verify_live` is empty, which is the
profile saying live state cannot be verified in this repo at all.

### visual

Render the output, put the artifact in `$RUN_DIR`, and show it to the user.
Their acceptance is what makes it evidence — rendered output is a taste
judgment, and taste is theirs.

**Asking them to look at a screenshot is not a debt gate.** You are asking for a
subjective acceptance the design reserves for them; you are not asking them to
accept anything about debt, and nothing about this stage's exit depends on their
answer being yes. If they decline to look now, that is a deferral: debt, with
`reason` saying so.

Debt when: nothing can render here (no browser, no display, the UI does not
build), or the user defers the review.

Record what was rendered and where:

```json
{"e": "verification:evidence",
 "item": {"class": "visual",
          "how": "npm run build && npx serve dist, screenshot of / at 1440x900 -> <run dir>/home-1440.png",
          "result": "user reviewed <run dir>/home-1440.png and accepted it: 'spacing is right, ship it'"}}
```

---

## 6. Real-data and live checks run before tagging, when feasible

Tagging is `clodex-ship`'s action, and it happens after you hand off. So the
ordering constraint is satisfied by doing the work **here, now** rather than
leaving it for ship to remember — which is the whole reason this stage exists
between build and ship. Concretely: do not defer a `real-data` or `live-check`
class to "we'll see after the deploy" when you could run it in this session.

"Not feasible" is a short, checkable list. Each item is **debt with that as the
reason**, never a silent skip and never an evidence item with a hedge in it:

| Not feasible because | The `reason` names |
|---|---|
| a credential the check needs is unset | the variable **name** from `required_env` or the action's `env_refs` — never its value |
| there is no deploy target | `deploy: null` in the profile |
| live state cannot be verified in this repo | `deploy.verify_live` is `[]` |
| the environment does not exist yet | the release is not deployed; there is no staging target |
| production-shaped input is not obtainable | no fixture, no sanitized export, and getting one needs access you do not have |
| the only way to run it would mutate live data | that it is a human-owned decision, not a capability gap |

The last four are usually one situation: **this repo deploys on push, so nothing
serves the change until ship pushes.** That is ordinary, it is debt, and its
`risk` is the interesting part — what a defect that only shows up live would then
cost, given that ship's `verify_live` looks *after* the release is already out.

Reading `deploy` to write that reason is the only thing you do with it. You do
not deploy, you do not tag, and you do not pre-run ship's steps.

---

## 7. The tests-only worker — optional, read-only

An independent look at whether the tests actually prove the thing. **Not
default-on.** Each trigger below is checkable, not a mood — run the worker when
any one of them holds:

- the declared evidence is `tests` alone **and** the diff touches a file that is
  not a test, a fixture, a doc, or the plan file; or
- any declared class ended in debt (§9), so the classes that remain are carrying
  weight the plan did not intend them to carry; or
- the plan's Risks section names a path that appears in the diff.

None of the three holds → skip it, and say in chat that you did and which
trigger you checked.

Build the diff of everything this run committed, then run the worker:

```bash
START="$(python3 "$STATE" rebuild "$RUN_DIR" | python3 -c 'import json,sys;print(json.load(sys.stdin)["git"]["start_head"])')"
git diff "$START" HEAD > "$RUN_DIR/verify.diff"
PROMPT="$RUN_DIR/tests-review.prompt.md"      # written with your file tool, never a shell string
if [ -z "$PLAN" ]; then
    echo "STOP: this run's plan.path is null, so there is nothing to review against."
    echo "Do not run the worker and do not continue this section — hand back to clodex"
    echo "and ask it to close or abandon the run (§1, last row of the resume map)."
else
    OUT="$(bash "$RUNNER" --role code-reviewer --repo "$REPO" \
            --run-id "$(basename "$RUN_DIR")" \
            --prompt-file "$PROMPT" --input "$RUN_DIR/verify.diff" --input "$PLAN")"; RC=$?
    printf 'rc=%s line=%s\n' "$RC" "$OUT"
    ENVELOPE="${OUT#* }"   # strip the FIRST word only — a repo path may contain spaces
fi
```

**The `$PLAN` guard is a hard stop, not a fallback.** When it fires, leave §7
entirely: `$ENVELOPE` is never set, so the envelope check below would read a
stale path from an earlier invocation or nothing at all, and either way report on
a review that did not happen.

It is not decoration either. §0 defines `$PLAN` as `plan.path or ""`, and an
empty one makes the runner die with exit **64** and `input artifact not found:`
before codex ever starts — a usage error you would then debug as if the worker
had failed. A run at `verify` whose `plan.path` is null is malformed regardless:
build cannot have run without a recorded plan, and this stage's whole question is
"does this prove what the plan says". §1's resume map sends that run the same way
this branch does.

**The role is `code-reviewer`, always.** The runner puts it in codex's
`read-only` sandbox, so it cannot edit your tree even if the prompt slipped.
`implementer` is `workspace-write` and is forbidden here (§2).

The prompt, in this shape:

```markdown
Assess whether this change's automated tests actually prove what its plan says
done requires. You are reviewing tests, not writing them.

Plan: <the value of $PLAN> — read its Scope ("Done when"), Batches, and Evidence
table.
Diff under review: <$RUN_DIR/verify.diff> — every commit this run made.

The evidence this plan declared, and what each class was meant to prove:
<one line per declared class, class and proof, from the manifest>

Report as findings:
1. A "Done when" — the plan's or a batch's — that no test exercises.
2. A test that would still pass if the behaviour it names were removed or inverted.
3. A file in the diff that changes runtime behaviour with no test touching it.
4. A test that proves something narrower than its name claims.

Report findings only. Do not edit files, do not write tests, and do not propose
patches: this run's build stage is over and code is not changed here.
blocker/high/medium for anything that would let a real defect ship; low/info for
improvements. Return an empty findings list if you find nothing.
```

The findings schema is the runner's, not one you invent: read the envelope's
`findings[]`, where each entry has an `id` **minted by the runner** (`F001`,
`F002`, … in the order the model reported them) plus the four fields the model
itself wrote — `severity` from `blocker|high|medium|low|info`, `summary`,
`detail`, `location`. Those four are `$defs.model_report` in
`$CLODEX_HOME/runner/envelope.schema.json`; `id` is not there, because the model
never supplies it.

The runner prints one line, `"<status> <envelope-path>"`, and **its exit code is
the authority**. Never read status out of prose or stderr.

| rc | Status | What to do |
|---|---|---|
| 0 | `complete` | Read the findings; §8. |
| 2 | `partial` | It stopped short. Resume with the one-command line the runner printed on stderr — do not start a fresh invocation. |
| 3 | `interrupted` | Same: resume with the printed command. |
| 1 | `failed` | Read the envelope's `error` and `output.stderr`. A failed worker is not a verdict — it is an absent review, so decide whether to re-run it or say in the handoff that it did not run. |
| 64 | usage error | You called the runner wrong. Fix the arguments. |
| — | empty `$OUT` | The runner died before writing an envelope. Read its stderr. |

Only a `complete` envelope is a review. Confirm it worked from the current diff:

```bash
python3 - "$ENVELOPE" "$RUN_DIR/verify.diff" <<'PY'
import hashlib, json, sys
env = json.load(open(sys.argv[1]))
want = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
print("status:", env["status"], "invocation:", env["invocation_id"])
print("reviewed this exact diff:", any(i["sha256"] == want for i in env["inputs"]))
for f in env["findings"]:
    print(f["id"], f["severity"], "|", f["summary"], "|", f["location"])
PY
```

A worker that found nothing is not evidence on its own — it is one input to the
`tests` class you already recorded in §5. Do not append a second evidence item
for "the reviewer was happy".

---

## 8. Findings — nothing is dropped, and nothing is fixed here

Everything this stage turns up that is not a clean result is a finding: a red
gate (§4), a declared proof the evidence does not actually meet (§5), and every
finding the worker returned (§7).

Record it before acting on it. Namespace ids by stage, because the runner mints
`F001` fresh every invocation and this run's build stage already used `b<N>-`:

```json
{"e": "finding:recorded", "id": "v-F001", "source": "code-reviewer",
 "severity": "high", "summary": "<one line, verbatim from the envelope>",
 "location": "<the envelope finding's location, verbatim>",
 "detail": "<the envelope finding's detail, verbatim>",
 "invocation": "<the envelope's invocation id>",
 "codex": {"invocation_id": "<same>", "role": "code-reviewer",
           "status": "complete", "envelope": "<path>", "duration_s": 180}}
```

`source` is the Codex role that produced it — `code-reviewer` — or `verify` for
one you found yourself, such as a red gate. A finding you found yourself has no
invocation and carries neither field; a delegated one carries both, with the
`codex` block on the first finding of that invocation (`clodex` → Telemetry).

What carries over unchanged from `clodex-plan` §9: the dispositions that
apply here (`fixed`, `accepted`, `rejected`), that **only the user** may
accept or reject one and their words go in the `note` — or a standing mandate
granting `finding-disposition` (`clodex-plan` §6), with `by: "mandate"` and
the note citing it — that nothing is ever dropped, and that severity does not
restrict disposition: an `accepted` blocker is a legitimate end state that
survives into ship's final review.

```json
{"e": "finding:disposed", "id": "v-F001", "disposition": "accepted",
 "note": "<the user's own words>"}
```

### `fixed` here means the code changed — and you did not change it

You cannot fix it, and **you cannot hand the run back to `clodex-build`**: the
reducer refuses a backwards stage transition — *"stage would move backwards,
verify -> build"* — and `clodex-build` bounces a run whose stage is `verify`.
There is no path that re-opens build in this run.

So: record the finding, then put it to the user in one message with the exact
command, its exit code, the failing output from `$RUN_DIR/gate-<gate>.log`, and
which declared class it touches. Then take their call, which is one of three:

| They choose | You do |
|---|---|
| **A — a follow-on run fixes it** | **This run ends here.** It cannot reach ship, so §10 and §11 do not apply — use the block below instead. |
| **B — they fix and commit it themselves** | Re-run the affected gate (§4) and the affected class (§5). Dispose `fixed` **only once the gate is green**, with their commit sha in the `note`. §10 will print `SOMETHING COMMITTED DURING VERIFY`; carry that sha into the handoff (§11, item 5). |
| **C — they accept it** | `accepted`, their words in the `note`. It stands as a known risk and ship's final review reads it. The run continues to §10. |

#### Outcome A in full — it is the one with a trap in it

Say this, in this shape:

> clodex, run dir `<the absolute run dir>` — verification found `<finding id>`,
> which needs a code change. This run cannot re-enter build, so it has to be
> **closed** before the follow-on can open with `parent` set to `<this run id>`.

**You append neither event.** `run:closed` and `run:opened` belong to the router
— §0 lists the five events that are yours — and `clodex` already owns both: its
§2 offers Close on an open run, its §6 opens the new one.

**Leave the finding `open`.** The reducer accepts `run:closed` with an open
finding, and a closed run carrying an unresolved finding is the honest record:
the run ended, and that is what it ended on. Do not invent a disposition to tidy
the log, and do not run §10 looking for `VERIFY COMPLETE` — an open finding is a
blocker there, correctly, because §10 answers "may this go to ship?" and this
path is not going to ship.

**Why it must be closed, not merely left behind.** The router allows one open run
per repo (`clodex` §2), so a run parked at `verify` stops the follow-on from
opening at all — and the router's resume offer routes stage `verify` straight
back to this skill. That loop is exactly what this outcome exists to avoid, and
leaving the run open recreates it.

**What it costs — say this out loud as well.** This run's evidence and debt die
with it: they never reach a release authorization, and the follow-on run has to
produce them again from scratch. That is the price of a one-way state machine. It
is not a reason to relabel the finding as something that lets the run continue.

**A red gate is not debt.** Debt is a class whose evidence could not be
produced; a red gate is evidence that was produced and came back negative.
Recording a failing suite as debt would hand ship a "deferred" label for a
defect that is sitting right there, and the release authorization would be
accepting the wrong thing.

---

## 9. Record the debt

One entry per class you could not produce, appended before you leave:

```json
{"e": "verification:debt",
 "item": {"class": "live-check",
          "reason": "nothing serves this change yet — the profile's deploy.trigger is auto-on-push, so the release goes live only at ship's push step",
          "risk": "a defect that only appears in the deployed environment (wrong env var, wrong build output path) would first be visible in production; ship's verify_live would catch it minutes after the release is already serving, so the remedy is a revert rather than a fix before release"}}
```

**Exactly three fields. No more, no fewer:**

| Field | Is | Is not |
|---|---|---|
| `class` | the class deferred: `tests`, `real-data`, `live-check`, `visual` | a description of the work |
| `reason` | why it could not be produced, naming the specific blocker (§6's table) | "not done", "out of scope", "will do later" |
| `risk` | **what could go wrong because it wasn't** — the defect this class would have caught, where it would surface, and what it would cost to fix from there | a restatement of `reason` |

`risk` is the field ship's authorization is really about, and it is the one that
gets written lazily. "Live behaviour unverified" is `reason` said twice. A real
risk names a failure this missing evidence would have caught and says what
happens when it is found later instead.

### Where debt is accepted: `clodex-ship`, once. Not here.

You do not ask the user to approve, waive, sign off on, or "be OK with" any of
this. You do not weigh whether the debt is small enough to proceed. You write the
entries, you say them out loud in the handoff (§11), and the run moves on.
`clodex-ship` puts every debt entry in front of the user inside the single
release authorization, together with the exact commands and targets it is about
to run, and **that** is where a human accepts it — in the same breath as
authorizing the release it affects. Splitting that decision in two is how a
release gets approved twice and understood once.

An empty debt list is a normal, good outcome. So is a debt list with four entries
in it. Neither changes what you do next.

---

## 10. The completeness check

Run it from the repo root. It answers the property this stage exists to
guarantee — every declared class ends in evidence or debt — from the manifest
alone:

```bash
python3 - "$STATE" "$RUN_DIR" <<'PY'
import json, subprocess, sys
state, run_dir = sys.argv[1], sys.argv[2]
snap = json.loads(subprocess.check_output(["python3", state, "rebuild", run_dir]))
ver, blockers = snap["verification"], []
CLASSES = ("tests", "real-data", "live-check", "visual")

declared = sorted({d.get("class") for d in ver["declared"]})
if not declared:
    blockers.append("the plan declared no evidence classes")
have_ev = {e.get("class") for e in ver["evidence"]}
have_debt = {d.get("class") for d in ver["debt"]}
for c in declared:
    ev, debt = c in have_ev, c in have_debt
    verdict = ("evidence" if ev and not debt else "debt" if debt and not ev else
               "BOTH — a class is produced or deferred, never both" if ev else
               "NEITHER — no evidence and no debt")
    print("class %-11s %s" % (c, verdict))
    if ev == debt:
        blockers.append("class %s: %s" % (c, verdict))

for item in ver["debt"]:
    if set(item) != {"class", "reason", "risk"}:
        blockers.append("debt %r: keys are %s, not exactly class/reason/risk"
                        % (item.get("class"), sorted(item)))
    for key in ("class", "reason", "risk"):
        if not str(item.get(key) or "").strip():
            blockers.append("debt %r: %s is empty" % (item.get("class"), key))
for item in ver["evidence"]:
    for key in ("class", "how", "result"):
        if not str(item.get(key) or "").strip():
            blockers.append("evidence %r: %s is empty" % (item.get("class"), key))
for item in list(ver["debt"]) + list(ver["evidence"]):
    if item.get("class") not in CLASSES:
        blockers.append("class %r is not one of: %s" % (item.get("class"), ", ".join(CLASSES)))

open_f = [f["id"] for f in snap["findings"] if f["disposition"] == "open"]
print("open findings:", " ".join(open_f) or "(none)")
if open_f:
    blockers.append("findings still open: " + " ".join(open_f))

committed = [b["commit"] for b in snap["batches"] if b["commit"]]
expected = committed[-1] if committed else snap["git"]["start_head"]
head = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
print("HEAD %s, last committed by the run %s -> %s" % (
    head[:8], (expected or "-")[:8],
    "unchanged" if head == expected else "SOMETHING COMMITTED DURING VERIFY"))


def under(path, prefix):                  # path IS prefix, or sits inside it
    return path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")


acknowledged = snap["git"]["dirty_at_start"]
raw = subprocess.check_output(
    ["git", "status", "--porcelain", "-z", "--untracked-files=no"]).decode()
fields, i, theirs, since = raw.split("\0"), 0, [], []
while i < len(fields) and fields[i]:
    entry = fields[i]; i += 1
    paths = [entry[3:]]
    if entry[0] in ("R", "C"):
        paths.append(fields[i]); i += 1        # a rename's origin path counts too
    line = "%s %s" % (entry[:2], " <- ".join(paths))
    bucket = theirs if all(any(under(p, d) for d in acknowledged) for p in paths) else since
    bucket.append(line)
print("tracked, dirty before the run opened:", " | ".join(theirs) or "(none)",
      "— the user's, not a finding")
print("tracked, modified since:", " | ".join(since) or "(none)")

print("debt entries: %d  (not a blocker — ship accepts debt, verify does not)" % len(ver["debt"]))
for b in blockers:
    print("BLOCKER:", b)
print("VERIFY COMPLETE" if not blockers else "NOT DONE — %d blocker(s)" % len(blockers))
PY
```

**Debt never appears in `blockers`.** A run with four debt entries prints
`VERIFY COMPLETE`. That is the design, not an oversight: this stage has no gate.

**`-z` is load-bearing in that last read.** Plain `git status --porcelain`
C-quotes any path with a space or a non-ASCII character — `a b.txt` comes back as
`"a b.txt"` — so it never matches its `dirty_at_start` entry, lands in `modified
since`, and the next bullet tells you it is a finding. That is the round-1 bug
again, narrowed to paths with spaces or accents. `-z` emits raw paths, NUL
separated, and never quotes; it also puts a rename's origin in its own field
instead of an unquoted-but-ambiguous ` -> `. Both siblings do the same thing —
`clodex-build` §3/§7 parse `-z` for exactly this reason.

Three lines it prints are yours to interpret, not the script's. **The first two**
go into the handoff as §11's item 5 when they fire; the third never does:

- **`SOMETHING COMMITTED DURING VERIFY`** — verify makes no commits, so it is one
  of three: the user committed a fix (§8, row B), the user committed unrelated
  work of their own mid-session, or this stage broke its own rule (§2). Name
  which, with the sha — `git log --oneline <expected>..HEAD` shows what landed.
  Either kind of user commit is a fact ship needs; a commit this stage made is a
  defect ship needs.
- **`tracked, modified since`** — a suite that rewrites snapshots, a formatter
  that ran as a side effect. You do not commit it and you do not revert it: it is
  a finding (§8), and it means the gate mutates the tree, which ship's commit
  step would otherwise sweep up.
- **`tracked, dirty before the run opened`** — the user's own uncommitted work,
  acknowledged at run open and subtracted here on purpose. **It is not a
  finding**, it is not yours to stage, revert, or clean, it is never repeated in
  the handoff, and recording one would put someone else's work in front of ship's
  final review forever. Repos where a clodex run coexists with unrelated edits are
  the normal case, not the odd one.

**What the subtraction cannot tell you.** `git status` prints one line per path
and no provenance, so a path that is *both* acknowledged and touched by this run
reads as acknowledged, and the run's own edit hides inside the user's. Nothing
here can separate them. What actually keeps a run off acknowledged paths is the
router's fold / isolate / abort resolution at `clodex` §5B, settled with the user
before build opened its first batch — this line is a blind spot downstream of
that decision, not a second line of defence for it.

---

## 11. Exit

Run `python3 "$STATE" telemetry-sync "$RUN_DIR" "$REPO/.clodex/runner"` once
more; it should now print nothing (§5 attached everything). A block it does
print rides ship's appends — say nothing about it in prose.

`VERIFY COMPLETE`, then hand off the way the router does: invoke `clodex-ship`
and give it the absolute run directory — *"clodex-ship, run dir
`<repo>/.clodex/r-2026-08-11-a`"*. Tell it the branch if build created one, since
the manifest does not record it.

Do not append `stage:ship:entered`. Each stage appends its own entry event.

Say these things in chat, in this order — this is the prose that matters, because
ship reads the manifest for everything else:

1. **The gates**, as §4 printed them: each command and its rc, and each null one.
2. **Evidence, per class**: the class and one line of what proved it.
3. **Debt, per entry**: class, reason, risk — all three, in full. Not "some
   verification debt"; the entries.
4. **One sentence naming where it gets decided**: *"`clodex-ship` will put this
   debt in the release authorization — that is where it is accepted, and nothing
   about it has been accepted yet."*
5. **Only when §10 printed one of its interpretive lines** — omit this item
   entirely otherwise: the commit that landed during verify and its sha, or the
   tracked files modified since the run opened and what you concluded about them.
   These are facts about the tree that live in no event, so this sentence is the
   only way they reach ship. The acknowledged-dirt line is **not** one of them
   and is never repeated here.

Beyond those five, carry nothing forward in prose. If a fact matters to ship, it
is in the plan file, a commit, the log — or in item 5, which exists precisely
because §10 found something none of the other three can hold.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Asking the user to approve, waive, or sign off on verification debt | This stage has no gate. Record it, say it, hand off. `clodex-ship`'s release authorization is the one place debt is accepted (§9). |
| Holding the run at verify because the debt "feels like too much" | Not your call and not a state this stage has. Debt is surfaced, not weighed (§9). |
| Fixing a failing test, or a one-line code fix, because it is obviously right | Verify never edits tracked files. It is a finding, and the fix belongs to build — which this run cannot re-enter (§8). |
| Committing anything | Commit authority is `clodex-build` and `clodex-ship`, nowhere else (§2). |
| Handing the run back to `clodex-build` to fix something | Refused: *"stage would move backwards, verify -> build"*, and build bounces a verify-stage run. The three legal ways forward are in §8. |
| Leaving the run open at `verify` after handing a code-change finding back | The router allows one open run per repo, so the follow-on can never open — and the resume offer routes stage `verify` straight back here. Outcome A ends the run through `clodex` (§8). |
| Recording a finding about a file that was already dirty when the run opened | §10 subtracts `git.dirty_at_start` on purpose. The user's uncommitted work is not this run's finding, and a finding lives in the log forever, in front of ship's final review (§10). |
| Recording a red gate as debt | Debt is evidence deferred; a red gate is evidence produced and negative. Recording it as debt hands ship the wrong label for a live defect (§8). |
| `[ -n "$CMD" ] && bash -c "$CMD"; printf 'rc=%s' "$?"` for a gate | With a null command the test is what fails and it prints `rc=1` — a red gate in a repo that has none. Explicit `if`/`else` (§4). |
| Treating a null gate command as debt | Null is a recorded fact about the repo, not a deferral. It becomes debt only when a declared class depended on it (§4). |
| Running `deploy.verify_live` before ship deploys and recording it as a live check | It passes against the **old** release. Only a version-aware check proves anything before the deploy (§5). |
| Skipping a real-data or live check quietly because it "isn't practical here" | Every infeasibility is one of §6's rows and every one becomes a debt entry with that as the reason. A silent skip leaves the class in neither state, and §10 fails. |
| A debt entry whose `risk` restates its `reason` | `reason` is why it could not be produced. `risk` is the defect it would have caught, where it surfaces, and what fixing it from there costs (§9). |
| Adding a field to a debt entry, or inventing a fifth evidence class | Exactly `class`, `reason`, `risk`; exactly `tests`, `real-data`, `live-check`, `visual`. §10 fails both. |
| Re-appending evidence after a resume | The reducer does not de-duplicate. Read `verification.evidence` first and append only the missing `(class, how)` (§1). |
| Delegating with `--role implementer` | Every delegation here is read-only. `code-reviewer` is the role, and the runner sandboxes it accordingly (§7). |
| Reading the worker's status out of its prose | The runner's exit code and the envelope decide. Only `complete` is a review; a `partial` is resumed, not restarted (§7). |
| Inventing an event name | The vocabulary is frozen at 23 names and the reducer refuses anything else. This stage appends five of them (§0). Something the names do not cover is a **field** on one of them — the optional `preflight` and `codex` blocks, and `finding:recorded`'s `severity`/`summary`/`round`/`invocation`/`plan_hash` (`clodex` → Telemetry). |
