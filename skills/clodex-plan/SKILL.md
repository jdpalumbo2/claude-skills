---
name: clodex-plan
description: Use when the clodex router hands off a run at stage `open` or `plan`, when a run's snapshot shows no recorded plan or a plan with no standing approval, when review findings need dispositions before work can start, or when someone asks to plan a feature in a repo that already has a `.clodex/` run directory.
---

# clodex-plan — ground, decide, get an approved plan

## Overview

This stage owes the run exactly four things, all of them facts in the run's
event log:

1. A **plan file** in the repo, at the profile's plans directory.
2. `plan:recorded` (or `plan:amended`) carrying that file's **version, path, and
   sha256 hash**.
3. Every plan-review **finding disposed** — `fixed`, `accepted`, or `rejected`.
4. `verification:declared` for each evidence class, then `plan:approved` **bound
   to the current plan hash**.

When those exist, the plan is approved and `clodex-build` can start.

**Where this stage ends.** You declare *owned paths* and *done when* per batch.
`clodex-build` composes the full batch contract from them (forbidden paths,
test expectations) and executes. You never write code, never open a batch, never
commit anything but the profile.

You arrive here from `clodex`, which owns preflight, the profile, lane
classification, the change boundary, and the run directory. If you were invoked
without an absolute run directory, **stop and invoke `clodex`** — do not go
looking for a run yourself.

---

## 0. Paths and commands

```bash
CLODEX_HOME="${CLODEX_HOME:-$HOME/.claude/skills/clodex}"   # the router's dir, not this one
STATE="$CLODEX_HOME/state/clodex_state.py"
RUNNER="$CLODEX_HOME/runner/run-codex.sh"
RUN_DIR="<the absolute run dir the router handed you>"
REPO="$(python3 "$STATE" rebuild "$RUN_DIR" |
        python3 -c 'import json,sys;print(json.load(sys.stdin)["repo"])')"
cd "$REPO"
PROFILE="$REPO/.clodex/profile.json"
```

Shell variables do not survive between command invocations — **re-establish this
block at the top of every shell you run these procedures in.** Everything below
runs from `$REPO`.

Engine verbs, payload on **stdin**:

```bash
python3 "$STATE" status  "$RUN_DIR"     # human summary
python3 "$STATE" rebuild "$RUN_DIR"     # the manifest: full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
```

"The **manifest**" below always means the output of `rebuild`. Append exit codes
and the lock rules are in the `clodex` skill, §"Paths and commands" and §2 —
read them there, they are not repeated here. The one that bites: exit **3** means
the event *is* durably logged; run `rebuild`, do not retry.

Write every event to a file with your file-writing tool and pipe the file in.
Briefs, plan paths, and finding summaries contain quotes; shell interpolation
will corrupt them.

---

## 1. Take the handoff

```bash
python3 "$STATE" status "$RUN_DIR"
```

- `stage: open` → append your entry event, once:
  ```json
  {"e": "stage:plan:entered"}
  ```
- `stage: plan` → a previous session already entered. **Do not append it again.**
  Read the manifest and pick up from the table below.
- Anything later (`build`, `verify`, `ship`, `closed`) → you are in the wrong
  stage; hand back to `clodex`.

**Resume map** — read `python3 "$STATE" rebuild "$RUN_DIR"` and match the first
row that is true:

| Manifest shows | You are | Go to |
|---|---|---|
| `plan.hash` is `null` | nothing written yet | §2 |
| plan recorded, its `Direction gate:` line says `yes`, and no un-revoked `approvals` entry has `scope: "direction"` on the current hash | premise not yet approved | §7 |
| any `findings` entry with `disposition: "open"` | mid review loop | §9 (dispose what is open), then §8 for the next round |
| all findings disposed, no un-revoked `plan:approved` on the current hash | ready to ask | §10 |
| an un-revoked approval with `scope: "plan"` on the current hash | approved | §11 |

An approval whose `revoked` is non-null does not count. An amendment revoked it
on purpose; the plan needs approving again.

---

## 2. Ground before you ask anything

Read the profile and the repo first. Every question you ask that a file already
answers costs the user a round trip and buys nothing.

```bash
python3 - "$PROFILE" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
docs = p.get("docs") or {}
print("plans_dir:      ", docs.get("plans_dir") or "(unset)")
print("architecture:   ", " ".join(docs.get("architecture") or []) or "(none)")
print("default_classes:", " ".join(p["evidence"]["default_classes"]) or "(none)")
print("test:           ", p["commands"]["test"])
print("build:          ", p["commands"]["build"])
print("deploy:         ", "none" if p.get("deploy") is None else p["deploy"]["target"])
PY
```

Then, in this order:

1. **Read every path in `docs.architecture`.** The profile says a plan must be
   grounded in them before it proposes structure.
2. **Read the files the brief names**, and the tests that cover them.
3. **Find the pattern this repo already uses** for the thing you are about to
   add. Reinventing one is a finding the reviewer will hand back.

`plans_dir` unset or `null` → use `docs/plans`, say so in one line, and record it
so the next run does not re-ask:

```bash
python3 - "$PROFILE" <<'PY'
import json, sys
path = sys.argv[1]
p = json.load(open(path))
p.setdefault("docs", {})["plans_dir"] = "docs/plans"
json.dump(p, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY
git add .clodex/profile.json && git commit -m "chore(clodex): record docs.plans_dir"
```

That is the only commit this stage makes, and it stages one explicit path. Never
`git add -A`, `git add .`, or `git commit -a`.

---

## 3. Ask only blocking or decision-bearing questions

Grounding (§2) always runs. **Discovery — putting questions to the user — runs
only when your question list is still non-empty after grounding.** There is no
unconditional requirements step; most briefs arrive with the "what" already
specified and go straight to §4.

A question qualifies only if it is one of these:

- **Blocking** — you cannot write the plan without the answer, because you would
  have to guess at behavior the user can observe.
- **Decision-bearing** — two defensible answers produce materially different
  plans and the choice belongs to the user: product direction, taste, scope
  boundary, cost, an external side effect, or a data/privacy boundary.

Everything else you **resolve by reading** and write down as an assumption in the
plan. Assumptions are stated, not asked.

Ask the whole list in **one message**. Before sending it, delete every question
you could answer by opening a file — that is the entire test. If the list is
empty, say "no blocking questions" and go to §4.

---

## 4. Decide the direction gate

Some work is accepted by taste: someone looks at it and says yes or no. Bulk
implementation before that judgment is work you may throw away. So taste-shaped
work gets its premise approved first — and non-taste work does not, because that
gate would be pure ceremony.

Answer this **now**, before writing the plan, because it changes what the plan
must contain. Answer **yes** if either test passes:

**Test A — the ask.** It names a new or reworked user-facing surface, visual
design, copy or content, or brand/positioning. Signals: "landing page", "new
screen", "redesign", "make it look…", "rewrite the copy", "name it", "tagline",
"logo", "theme", "empty state", "onboarding flow".

**Test B — the owned paths.** The paths this work will touch include files whose
acceptance is judged by looking at the result rather than by running it:

- stylesheets and design tokens (`*.css`, `*.scss`, tailwind config, palette or
  type-scale files)
- markup or components that render a user-visible page or route (`*.html`,
  page/route components, layouts, templates)
- user-visible copy and content (`content/`, `*.mdx`, marketing or landing
  routes, email templates)
- brand assets (logo, favicon, illustration, OG image)

**Answer no** when the work is data, pipeline, refactor, infrastructure, build or
CI, tests, schema, or an internal API.

**The tie-break, and it overrides Test B:** if the plan makes no new visual, copy,
or positioning decision — it reuses an existing component, existing copy,
existing layout — the answer is **no**, and the plan must name the existing
pattern it follows. Adding a button built from the design system to an existing
page is not a taste decision. Designing what that page looks like is.

Write the answer into the plan as a required line (§5). It is auditable: a
reader can check it against the ask and the owned paths.

| Gate | The plan must contain | Before the review loop |
|---|---|---|
| **no** | one line: `Direction gate: no — <why, or the existing pattern it follows>` | nothing extra |
| **yes** | a `## Direction` section: the **premise** (one paragraph: what this will be and why that is the right call), **comps** (2–3 references, or 2–3 named alternatives you rejected and why), and **acceptance criteria for taste** (what "good" means here, in checkable words) | run §7, the direction checkpoint |

---

## 5. Write the plan

**Every plan declares, without exception:** the brief verbatim · what in the repo
it is grounded in · its assumptions · its direction-gate answer · one *Done when*
· what is in and out of scope · its batches, each with owned paths and its own
*Done when* · its evidence classes · its risks.

File: `<plans_dir>/<YYYY-MM-DD>-<slug>.md`, slug kebab-cased from the brief. If
`plans_dir` already holds files, match their naming convention instead.

Every heading below is required. An empty section is an answer ("Out: nothing")
— a missing one is an unanswered question the reviewer will find.

```markdown
# <title>

Run: <run-id> · Plan version: <N> · Repo: <repo root>

## Brief
<the ask, verbatim from the manifest's `brief` field>

## Grounding
What in this repo this builds on: the files read, the existing pattern followed,
the architecture docs consulted. Name paths.

## Assumptions
One line each, falsifiable, resolved by reading — not by asking.

## Direction gate
Direction gate: yes|no — <trigger, or the existing pattern this follows>

## Direction            <!-- only when the gate is yes; otherwise omit -->
Premise · Comps · Acceptance criteria for taste.

## Scope
Done when: <one sentence a stranger could check>
### In
### Out
Named things this deliberately does not do.

## Batches
| # | Owned paths | Done when |
|---|---|---|
| 1 | `src/thing/`, `docs/plans/<this file>` | <checkable> |

Owned paths are the only paths that batch may touch. They must be disjoint
across batches. Include this plan file itself in a batch — otherwise ship, which
commits run-owned paths only, will leave it uncommitted.

## Evidence
| Class | What will prove it |
|---|---|
| tests | `<the profile's test command>` — covering <what> |
| real-data | <the production-shaped input it runs against> |

Classes come from: tests · real-data · live-check · visual. Any default class
this plan drops gets a line here saying why.

## Risks
What could go wrong, and what the plan does about it.
```

---

## 6. Record the plan

The plan hash is the **sha256 of the plan file's bytes**. Compute it after the
file is final and before you append:

```bash
PLAN="docs/plans/<file>.md"
python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$PLAN"
```

(`shasum -a 256 "$PLAN" | awk '{print $1}'` gives the same digest.)

**First plan** — write to `$RUN_DIR/plan-recorded.json` and append:

```json
{"e": "plan:recorded", "version": 1,
 "path": "docs/plans/2026-08-11-thing.md",
 "hash": "<sha256>"}
```

**Every revision after that is `plan:amended`, never a second `plan:recorded`.**
A second `plan:recorded` with a different hash is refused: *"a plan is already
recorded; supersede it with plan:amended"*. Bump the version, carry a real new
hash different from the one it supersedes, and say what re-review it needs:

```json
{"e": "plan:amended", "version": 2,
 "path": "docs/plans/2026-08-11-thing.md",
 "hash": "<new sha256>",
 "note": "fixed r1-F001: batch 2 owned paths were missing the migration",
 "required_review": ["plan-review"]}
```

An amendment revokes every approval bound to the superseded hash. Inside this
stage, before approval, that revokes nothing — which is exactly why revising
during the review loop is free and revising after approval is not.

---

## 7. The direction checkpoint — only when the gate is yes

Present it **after** the plan is recorded (the approval must bind to a hash) and
**before** the review loop (so a rejected premise does not burn review rounds).

One message: the premise, the comps, the acceptance criteria, and the explicit
ask — *approve this direction, or tell me what to change.* Do not start the
review loop until they answer.

**Approved** → append:

```json
{"e": "approval:granted", "scope": "direction", "by": "user",
 "plan_version": 1, "plan_hash": "<current plan hash>"}
```

**Changed** → revise the `## Direction` section, amend (§6), re-present. The
amendment revoked the old direction approval mechanically; the new one binds to
the new hash.

Every later amendment revokes this approval too, including ones that only fixed
a review finding. Do **not** run a second checkpoint for those: re-run the
checkpoint only when the `## Direction` section itself changed. Otherwise
re-grant the approval on the final hash inside the single approval message
(§10) — same gate, one message.

---

## 8. Codex plan review, to convergence

Plan review is **default-on**. It is not skipped because the plan looks simple,
and it is not skipped because the ask was small.

**One round** = one runner invocation against the current plan file.

Write the prompt to a file (never a shell string):

`$RUN_DIR/plan-review-r1.prompt.md`

```markdown
You are reviewing an implementation plan before any code is written. The repo
root is your working directory; read whatever you need.

Plan: docs/plans/2026-08-11-thing.md

The ask it must satisfy, verbatim:
<brief>

Round: 1

Check, in this order:
1. Does the plan satisfy the ask? Name anything asked for that no batch delivers.
2. Is it grounded in this repo? Open the files it names. Flag any assumption the
   code contradicts, any pattern it reinvents, any file it plans to edit that
   does not exist.
3. Are the batches' owned paths sufficient and disjoint? Flag work no batch owns,
   and any path two batches own.
4. Is each "done when" checkable by someone who did not write the plan?
5. Does the declared evidence actually prove the change works? Flag a class that
   cannot be produced in this repo, and any risk the evidence would not catch.
6. What breaks in production that this plan does not consider?

Report findings only. Do not edit the plan and do not write code. Use
blocker/high/medium for anything that would produce wrong or unshippable work,
low/info for improvements. Return an empty findings list if you find nothing.
```

Run it:

```bash
OUT="$(bash "$RUNNER" --role plan-reviewer --repo "$REPO" \
        --prompt-file "$RUN_DIR/plan-review-r1.prompt.md" --input "$PLAN")"; RC=$?
printf 'rc=%s line=%s\n' "$RC" "$OUT"
ENVELOPE="${OUT##* }"
```

The runner prints one line, `"<status> <envelope-path>"`, and its exit code is
the authority. **Never read the status out of prose, stderr, or the model's
summary.**

| rc | Status | What to do |
|---|---|---|
| 0 | `complete` | Read the envelope. This round counts. |
| 2 | `partial` | The reviewer stopped short. Findings are **not** the review. Resume: the runner printed a runnable one-command resume line on stderr — surface it and run it. Do not start a fresh round. |
| 3 | `interrupted` | Same as partial: resume with the printed command. |
| 1 | `failed` | No usable review. Read the envelope's `error` and `output.stderr`. Report to the user; do not approve a plan on a failed round. |
| 64 | usage error | You called the runner wrong. Fix the arguments. |
| — | empty `$OUT` | The runner died before writing an envelope. Read its stderr. |

Read the envelope — status, whether it reviewed *this* plan, and the findings:

```bash
python3 - "$ENVELOPE" "$PLAN" <<'PY'
import hashlib, json, sys
env = json.load(open(sys.argv[1]))
want = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
print("status:", env["status"], "invocation:", env["invocation_id"])
print("reviewed this exact plan:", any(i["sha256"] == want for i in env["inputs"]))
for f in env["findings"]:
    print(f["id"], f["severity"], "|", f["summary"], "|", f["location"])
PY
```

`reviewed this exact plan: False` means the file changed under the reviewer.
That round is stale — discard it and run a new one.

**Convergence.** The loop ends when a `complete` round against the **current**
plan hash returns **no blocker, high, or medium findings**. `low` and `info`
findings do not buy another round; record and dispose them (§9) and carry them
into the approval message.

Each round after an amendment is a **new invocation**, not `--resume`: the
artifact changed and the envelope must hash the new file. `--resume` exists only
to finish a `partial` or `interrupted` invocation. Give round N's prompt the
history so the reviewer is not re-deriving it:

```markdown
Round: 2. The plan changed since your last review.
- r1-F001 (high) <summary> — fixed: <what changed in the plan>
- r1-F003 (medium) <summary> — rejected: <the user's reason>
Re-check those and report anything still wrong or newly introduced.
```

**When the reviewer keeps finding new things.** Cap the loop at **3 rounds**.
A fourth round is not the answer — a reviewer still surfacing blockers on round
3 is telling you the plan is under-specified or the scope is wrong, and more
rounds spend money to hear it again. Stop and take it to the user in one
message: what keeps coming back, whether each item is a restatement of something
already disposed or genuinely new, and the three ways out — keep iterating (say
how many more rounds and why), accept the open findings as `accepted`
dispositions, or re-scope the plan and start the loop over from round 1.

---

## 9. Dispose every finding

Record each finding from a `complete` round **before** acting on it:

```json
{"e": "finding:recorded", "id": "r1-F001", "source": "plan-review",
 "severity": "high", "summary": "<one line, verbatim from the envelope>"}
```

**Namespace the id by round.** Envelope ids (`F001`, `F002`, …) are unique only
within one invocation, so round 2's `F001` collides with round 1's and the
reducer refuses it: *"finding 'F001' already recorded"*. Use `r<N>-F0NN`.

Then dispose it. Every recorded finding reaches one of exactly three
dispositions — nothing is dropped, and "we talked about it" is not a state:

| Disposition | Means | Who decides |
|---|---|---|
| `fixed` | the plan was changed to address it — so this implies an amendment (§6) and a new hash | you |
| `accepted` | legitimate, and the user chose not to act on it. It stands as a known risk and **survives into ship** | the user, explicitly |
| `rejected` | wrong — the reviewer misread the repo or the ask | the user, explicitly |

```json
{"e": "finding:disposed", "id": "r1-F001", "disposition": "fixed",
 "note": "batch 2 now owns migrations/; plan v2"}
```

`accepted` and `rejected` are overrides of an independent review, which is a
human-owned decision. Propose them — do not append them until the user has said
so, and quote their words in `note`. `fixed` is your own work and needs no
approval. The snapshot keeps only `id`, `source`, and `disposition`; the `note`
lives in the event log, which is the authoritative record.

**Severity does not restrict disposition.** A `blocker` the user decides to live
with is `accepted` — that is exactly what an override is, and it is a legitimate
end state, not a loophole. §8's convergence rule ends the *review loop*; it does
not forbid an unfixed blocker. The consequence is that the finding stays in the
manifest's `findings` with `disposition: "accepted"` for the life of the run, and
`clodex-ship`'s final review against the approved plan reads it there. An
override you take is an override that shows up at release, by construction.

Consolidate the asking: propose all `accepted` / `rejected` dispositions in the
**same message** as the approval ask (§10), not one gate per finding.

A later round that restates something already disposed: record it and dispose it
the same way, with `"note": "restates r1-F002"`. Cheap, and the log stays honest.

---

## 10. Declare evidence, then ask for approval

**Declare last.** Append one `verification:declared` per class from the Evidence
table of the version you are about to get approved, immediately before
`plan:approved`:

```json
{"e": "verification:declared",
 "item": {"class": "tests", "proof": "python3 -m unittest discover -s tests"}}
```

`class` is one of exactly `tests`, `real-data`, `live-check`, `visual`. Default
to the profile's `evidence.default_classes`; add more freely; drop one only with
the argument written in the plan's Evidence section — the approval binds to the
plan hash, so the user is approving that argument too. **At least one class is
required**, whatever the profile's defaults are: a plan declaring no evidence is
a plan with no definition of done.

The reducer appends to `verification.declared` without de-duplicating. Declare
early and then amend, and stale classes from a superseded version stay in the
manifest forever. `clodex-verify` reads this list; do not describe or pre-empt
what it does with it.

**The approval message** — one message, and for most runs the only gate this
stage spends:

1. The plan: path, version, and a three-line summary of what it will do.
2. The review outcome: rounds run, and every finding with what you did about it.
3. Anything you are asking them to `accept` or `reject`, each with your reason.
4. The declared evidence classes.
5. The explicit ask: *approve this plan?*

On yes: append the `finding:disposed` events for anything they just settled, then
the `verification:declared` events, then — when the direction gate was `yes` and
amendments revoked the earlier direction approval — `approval:granted` with
`scope: "direction"` on the final hash, and then:

```json
{"e": "plan:approved", "scope": "plan", "by": "user",
 "plan_version": 3, "plan_hash": "<sha256, recomputed from the file>"}
```

On no: if they asked for a change, revise, amend (§6), re-review when the change
is material, and re-ask. If the work should not go ahead at all, hand back to
`clodex` — it owns closing and abandoning a run, and this stage never does.

**Always pass `plan_hash` explicitly, recomputed from the file on disk** — not
copied from an earlier round. The reducer only refuses a hash it has never seen
(*"approval references unknown plan hash"*), which catches an edited-but-
unrecorded file. It does **not** catch a hash that is merely superseded: a hash
from before an amendment is still a known hash, so an approval bound to it is
accepted and reads `revoked: null` forever — the revocation sweep runs at
amendment time and never revisits approvals appended afterwards. That approval
looks valid and approves nothing. The only defence is recomputing, and the
`plan_hash == plan.hash` test below.

### What "approved" means, exactly

Read `python3 "$STATE" rebuild "$RUN_DIR"`. The plan is approved when **all
three** hold — and this is answerable from the manifest alone:

1. `plan.hash` is non-null.
2. `approvals` contains an entry with `scope: "plan"`, `plan_hash` equal to
   `plan.hash`, and `revoked: null`.
3. No entry in `findings` with `source: "plan-review"` has
   `disposition: "open"`. Every one is `fixed`, `accepted`, or `rejected`.

Plus, when the direction gate was **yes**, a fourth: an `approvals` entry with
`scope: "direction"`, the same `plan_hash`, and `revoked: null`.

None of these is a feeling, and none of them is "the user seemed happy." If any
is missing, the plan is not approved.

**A separate question:** is the file on disk still the approved plan? Recompute
the sha256 of `plan.path` and compare it to `plan.hash`. Different means someone
edited the file without amending — append `plan:amended` (which revokes the
approval), re-review if the change is material, and approve again.

---

## 11. Exit

Confirm all of §10's facts, then hand off exactly the way the router does
(`clodex` §6): invoke `clodex-build` and give it the absolute run directory —
*"clodex-build, run dir `<repo>/.clodex/r-2026-08-11-a`"*. It reads everything
else from the run.

Do not append `stage:build:entered`. Each stage appends its own entry event.

Carry nothing forward in prose. If a fact matters to build, it is in the plan
file or in the log, or it does not exist.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| A second `plan:recorded` with a new hash | Refused: *"a plan is already recorded; supersede it with plan:amended"*. Everything after the first record is an amendment. |
| Reusing envelope finding ids across rounds | Refused: *"finding 'F001' already recorded"*. Namespace them `r<N>-F001`. |
| Treating a `partial` envelope's findings as the review | Only a `complete` round counts. Resume with the command the runner printed. |
| Starting a fresh round to recover from an interruption | `--resume <invocation-id>` finishes the interrupted one. Fresh rounds are for a changed plan. |
| Approving after editing the plan file | The reducer refuses the unknown hash. Amend, then approve. |
| Declaring evidence right after recording the plan | Amendments leave stale classes in `verification.declared`. Declare immediately before `plan:approved`. |
| Asking a question a file answers | Ground first (§2). Only blocking or decision-bearing questions reach the user. |
| Running the direction checkpoint for a data or refactor change | The gate is a predicate (§4), not a mood. `no` means no checkpoint. |
| Marking a finding `accepted` because it seemed minor | Only the user accepts or rejects a finding. Propose it in the approval message. |
| Writing forbidden paths, batch contracts, or code | That is `clodex-build`. This stage declares owned paths and done-when. |
| Inventing an event name | The vocabulary is frozen at 23 names; the reducer refuses anything else. This stage appends eight of them: `stage:plan:entered`, `plan:recorded`, `plan:amended`, `approval:granted`, `finding:recorded`, `finding:disposed`, `verification:declared`, `plan:approved`. |
