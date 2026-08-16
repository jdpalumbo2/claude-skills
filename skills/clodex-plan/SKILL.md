---
name: clodex-plan
description: Use when the clodex router hands off a run at stage `open` or `plan`, when a run the router resumed shows no recorded plan or a plan with no standing approval, or when plan-review findings on such a run still need dispositions before work can start.
---

# clodex-plan — ground, decide, get an approved plan

## Overview

This stage owes the run exactly four things, all of them facts in the run's
event log:

1. A **plan file** in the repo, at the profile's plans directory.
2. `plan:recorded` (or `plan:amended`) carrying that file's **version, path, and
   sha256 hash**.
3. Every plan-review **finding disposed** — `fixed`, `accepted`, `rejected`, or
   `deferred-to-build`.
4. `verification:declared` for each evidence class, then `plan:approved` **bound
   to the current plan hash**.

When those exist, the plan is approved and `clodex-build` can start.

**Where this stage ends.** You declare *owned paths* and *done when* per batch.
`clodex-build` composes the full batch contract from them (forbidden paths,
test expectations) and executes. You never write code, never open a batch, and
**never commit anything at all** — `clodex-ship` commits run-owned paths.

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
SNAP="$(python3 "$STATE" rebuild "$RUN_DIR")"
REPO="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["repo"])')"
PLAN="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["plan"]["path"] or "")')"
cd "$REPO"
PROFILE="$REPO/.clodex/profile.json"
```

Shell variables do not survive between command invocations — **re-establish this
block at the top of every shell you run these procedures in.** Everything below
runs from `$REPO`.

`$PLAN` is empty until §6 records a plan; after that it is whatever the manifest
says, never a path you remember. §8 hands it to the runner, so a shell that
skipped this block passes `--input ''` and dies with usage error 64.

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
  stage. Say so and hand back, in these words: *"clodex, run dir
  `<the absolute run dir>` — this run is at stage `<stage>`, not plan."* The
  router owns picking the right stage skill; do not pick one yourself.

**Resume map** — read the manifest (`python3 "$STATE" rebuild "$RUN_DIR"`) **and
the plan file it points at** in `plan.path`. Match the first row that is true:

| What you find | You are | Go to |
|---|---|---|
| `plan.hash` is `null` | nothing written yet | §2 |
| plan recorded, the plan file's `Direction gate:` line says `yes`, and `approvals` has no entry with `scope: "direction"` — **ever, revoked or not** | premise never approved | §7 |
| any `findings` entry with `disposition: "open"` | mid review loop | §9 (dispose what is open), then §8 for the next round |
| all findings disposed, and no un-revoked `approvals` entry with `scope: "plan"` on the current hash | ready to ask | §10 |
| an un-revoked `approvals` entry with `scope: "plan"` on the current hash | approved | §11 |

Row 2 asks whether a direction approval was **ever** granted, not whether one
stands. Every amendment revokes it, including one that only fixed a review
finding — so testing for a *standing* one would re-present the premise after
every revision. A revoked direction approval is re-granted inside the single
approval message (§7, §10), not at its own gate.

An approval whose `revoked` is non-null does not count anywhere else. An
amendment revoked it on purpose; the plan needs approving again.

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
   add. Reinventing one is a finding the reviewer will hand back. What you find
   — or where you looked and found nothing — becomes the plan's `## Prior art`
   section (§5). This duty used to live only in prose, and prose duty fails
   under load; a required section in a hashed file, interrogated at review
   (§8), does not.

`plans_dir` unset or `null` → use the conventional default `docs/plans/`, tell
the user once — *"this repo's profile has no `docs.plans_dir`; I am using
`docs/plans/`, and you may want to add the key"* — and carry on.

**Do not write the profile and do not commit it.** `.clodex/profile.json` is
committed state that this stage does not own: `git add` stages the whole file, so
a pre-existing edit to `commands`, or a stale-profile repair the router made
without committing, would ride along inside a clodex commit — exactly the
file-level provenance the change boundary exists to protect. It would also commit
to whatever branch is checked out, ignoring the profile's own `branch` rule.
This stage makes **no commits at all**.

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
plan. Assumptions are stated, not asked. Prior art is always in that category:
which mechanism this repo already uses for an isomorphic problem is answered by
reading the repo (§5's `## Prior art`), never by asking the user.

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
pattern it follows — the same mechanism its `## Prior art` section (§5) cites;
name one pattern, in both places, so the two cannot drift. Adding a button built
from the design system to an existing page is not a taste decision. Designing
what that page looks like is.

Write the answer into the plan as a required line (§5). It is auditable: a
reader can check it against the ask and the owned paths.

| Gate | The plan must contain | Before the review loop |
|---|---|---|
| **no** | one line: `Direction gate: no — <why, or the existing pattern it follows>` | nothing extra |
| **yes** | a `## Direction` section: the **premise** (one paragraph: what this will be and why that is the right call), **comps** (2–3 references, or 2–3 named alternatives you rejected and why), and **acceptance criteria for taste** (what "good" means here, in checkable words) | run §7, the direction checkpoint |

---

## 5. Write the plan

**Every plan declares, without exception:** the brief verbatim · what in the repo
it is grounded in · its prior art — the existing mechanism here that solves an
isomorphic problem, and why it is or is not the shape used · its assumptions ·
its direction-gate answer · one *Done when* · what is in and out of scope · its
batches, each with owned paths and its own *Done when* · its evidence classes ·
its risks · its docs impact.

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

## Prior art
The existing mechanism in this repo that solves an isomorphic problem, cited by
path, and why it is or is not the shape used here. "None exists" is legal only
after naming where you looked. When the direction gate's tie-break (§4) answered
`no` because this follows an existing pattern, cite the same mechanism here.

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

Release-owned — no batch may own these:
- version source: `<the profile's version.source, e.g. package.json>`
- changelog: `<every file under the profile's changelog.path>`
- tags: `<the profile's tag format, or "tagging off">`

Print the set resolved from the profile, the way `clodex-build` §2 derives it —
not the rule in the abstract. The changelog, the version source, and tags belong
to `clodex-ship`, which closes them from evidence inside the release
authorization; build categorically forbids them whatever the plan says, so a
batch that owns one is a plan defect that otherwise surfaces at the first line
of build — after every review round has passed it.

Docs impact: none | <paths>

Does this change alter behavior the profile's `docs.architecture` files
describe? `none` is an answer. Paths mean a batch listed above owns updating
them — name the batch. Architecture docs are read at plan time; without an
owner here, nothing ever maintains them.

Claims: <resources, or omit the line>       <!-- only when .clodex/claims.json exists -->

Collision-prone resources this plan takes: migration numbers, ports, workflow
ids, property names. Check each against the ledger (`clodex` §1 check 8)
before recording the plan — a resource already held stops the plan here, at
the cheapest possible moment. The ledger is orchestrator-owned; this plan
NAMES what it needs, it never writes the file.

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
PLAN="<plans_dir>/<the plan file you just wrote>.md"    # then keep it in $PLAN (§0)
python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$PLAN"
```

(`shasum -a 256 "$PLAN" | awk '{print $1}'` gives the same digest.)

**First plan** — write to `$RUN_DIR/plan-recorded.json` and append:

```json
{"e": "plan:recorded", "version": 1,
 "path": "<plans_dir>/<plan file>.md",
 "hash": "<sha256>"}
```

**Every revision after that is `plan:amended`, never a second `plan:recorded`.**
A second `plan:recorded` with a different hash is refused: *"a plan is already
recorded; supersede it with plan:amended"*. Bump the version, carry a real new
hash different from the one it supersedes, and declare what re-review it needs:

```json
{"e": "plan:amended", "version": 2,
 "path": "<plans_dir>/<plan file>.md",
 "hash": "<new sha256>",
 "note": "fixed r1-F001: batch 2 owned paths were missing the migration",
 "required_review": ["plan-reviewer"]}
```

### Material or immaterial — the test that fills `required_review`

An amendment is **material** when it touches any of: **Brief · Scope** (including
the top-level *Done when*) **· Batches** (any owned path, any batch *Done when*)
**· Evidence · Direction**. An amendment that changes none of those — wording,
formatting, a clarification that adds no new claim — is **immaterial**. That is
the whole test; there is no third category and no judgment beyond reading which
sections the diff touched.

| | `required_review` | The review loop | Approval |
|---|---|---|---|
| **material** | `["plan-reviewer"]` | **re-opens** — it needs a `complete` round against the new hash (§8) | approve again, on the new hash |
| **immaterial** | `[]` | **stays converged** — nothing the last round examined changed | approve again, on the new hash |

Either way the hash moved, so the plan must be approved again. There is no
amendment that costs nothing.

**Do not invent values for `required_review`.** It names Codex **roles**, and the
vocabulary is fixed outside this skill: `properties.role.enum` in
`$CLODEX_HOME/runner/envelope.schema.json` — `plan-reviewer`, `implementer`,
`code-reviewer`, `advisor`. The same enum names a finding's `source` (§9), so the
whole run uses one set of names. `clodex-ship` is blocked until every declared
re-review exists against the current hash, so a `["plan-reviewer"]` you never
satisfy is a run that cannot ship.

An amendment revokes every approval bound to the superseded hash. Inside this
stage, before approval, that revokes nothing — which is exactly why revising
during the review loop is cheap and revising after approval is not.

### The typed mandate — pre-granted gates for a delegated run

A lane run under an orchestrator's standing brief satisfies some gates on
that brief's authority. Untyped, that authority lived in free text — and two
lanes of the same weekend answered the same gate class differently: one
satisfied plan approval on the brief, the other raised a blocking modal, same
skill, same repo. Typed, it is one event, recorded immediately after
`plan:recorded` when the brief (or the user, asked once) pre-grants gate
classes:

```json
{"e": "approval:granted", "scope": "mandate", "by": "user",
 "plan_version": 1, "plan_hash": "<current plan hash>",
 "actions": [{"grants": "finding-disposition"},
             {"grants": "plan-approval"},
             {"grants": "direction-approval"}]}
```

`actions[].grants` draws on a vocabulary of exactly three:
`finding-disposition` (accept or reject a finding, with grounds),
`plan-approval`, and `direction-approval`. **Verification-debt acceptance and
release authorization cannot be granted** — those gates open their modal in
every run, mandate or not; they are the human-owned core the design reserves,
and a mandate claiming them is ignored where those gates read it.

**Consult it before every modal it could cover.** A standing (un-revoked)
mandate whose grants cover the gate: satisfy the gate on its authority, set
`by: "mandate"` on the event so the manifest says which kind of run this was,
and let the disposition `note` cite the mandate instead of quoting a user who
was never asked — `"under mandate (grants finding-disposition): <the
grounds>"`. No standing mandate, or a gate outside its grants → the modal
opens as ever.

The mandate binds to the plan hash like every approval, so **every amendment
revokes it**. Accepted v0.2 behavior, not an accident: re-grant it against
the new hash on the authority that granted it first — one append, and the
log shows the re-grant. A mandate you cannot honestly re-grant after an
amendment is a mandate the amendment invalidated, which is the system
working.

---

## 7. The direction checkpoint — only when the gate is yes

Present it **after** the plan is recorded (the approval must bind to a hash) and
**before** the review loop (so a rejected premise does not burn review rounds).

One message: the premise, the comps, the acceptance criteria, and the explicit
ask — *approve this direction, or tell me what to change.* Do not start the
review loop until they answer. A standing mandate granting
`direction-approval` (§6) answers this gate itself: present the same content
as a record rather than a question, and append the direction approval with
`by: "mandate"`.

**Approved** → append:

```json
{"e": "approval:granted", "scope": "direction", "by": "user",
 "plan_version": 1, "plan_hash": "<current plan hash>"}
```

**Changed** → revise the `## Direction` section, amend (§6), re-present. The
amendment revoked the old direction approval mechanically; the new one binds to
the new hash.

Every later amendment revokes this approval too, including ones that only fixed
a review finding. **Run the checkpoint a second time only when the `## Direction`
section itself changed** — that is the same materiality test as §6, narrowed to
one section. For every other amendment, re-grant the approval on the final hash
inside the single approval message (§10). Same gate, one message.

---

## 8. Codex plan review, to convergence

Plan review is **default-on**. It is not skipped because the plan looks simple,
and it is not skipped because the ask was small.

**One round** = one runner invocation against the current plan file.

Write the prompt to a file (never a shell string):

`$RUN_DIR/plan-review-r<N>.prompt.md` — `<N>` is the round number.

Everything in angle brackets below is a placeholder to fill in, not literal text:

```markdown
You are reviewing an implementation plan before any code is written. The repo
root is your working directory; read whatever you need.

Plan: <the value of $PLAN>

The ask it must satisfy, verbatim:
<brief, from the manifest>

Round: <N>

Check, in this order:
1. Does the plan satisfy the ask? Name anything asked for that no batch delivers.
2. Is it grounded in this repo? Open the files it names. Flag any assumption the
   code contradicts, and any file it plans to edit that does not exist.
3. Interrogate `## Prior art`, with the repo open — not from the plan's prose.
   Is the cited mechanism actually isomorphic to this problem? Is the stated
   reason for using or diverging from its shape real? Search the repo for a
   mechanism the author missed that solves an isomorphic problem — this
   question has passed the most expensive defects when nobody owned it. Cite
   repo paths for every claim, including "found nothing".
4. Are the batches' owned paths sufficient and disjoint? Flag work no batch
   owns, any path two batches own, and any owned path that appears in the
   release-owned set printed beside the Batches table (version source,
   changelog files, tags) — build refuses those categorically, so a batch that
   owns one is a plan defect now, not at the first line of build.
5. Is each "done when" checkable by someone who did not write the plan?
6. Does the declared evidence actually prove the change works? Flag a class that
   cannot be produced in this repo, and any risk the evidence would not catch.
7. Does the change alter behavior that any of the profile's `docs.architecture`
   files describe while the plan's `Docs impact:` line says `none`, or names
   paths no batch owns updating?
8. What breaks in production that this plan does not consider?

Report findings only. Do not edit the plan and do not write code. Use
blocker/high/medium for anything that would produce wrong or unshippable work,
low/info for improvements. Return an empty findings list if you find nothing.
```

Run it:

```bash
PROMPT="$RUN_DIR/plan-review-r1.prompt.md"     # r2, r3 on later rounds
OUT="$(bash "$RUNNER" --role plan-reviewer --repo "$REPO" \
        --run-id "$(basename "$RUN_DIR")" \
        --prompt-file "$PROMPT" --input "$PLAN")"; RC=$?
printf 'rc=%s line=%s\n' "$RC" "$OUT"
ENVELOPE="${OUT#* }"     # strip the FIRST word only — a repo path may contain spaces
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

**Convergence — measured on findings you have not already disposed.** A round
converges when all three hold:

1. it is `complete`, and
2. it hashed the current plan (`reviewed this exact plan: True`), and
3. every blocker/high/medium finding it returned is a **restatement of one
   already disposed** as `accepted`, `rejected`, or `deferred-to-build`.

Zero blocker/high/medium findings is the ordinary case and satisfies (3)
vacuously. A round that re-reports a finding the user already accepted is
**also converged** — that finding has an answer.

Convergence is defined this way because the alternative cannot terminate. An
accepted-but-unfixed finding is still in the plan by construction, so every
later round reports it again; a rule keyed to what a round *returns* would loop
forever on exactly the findings the user already settled. Match a returned
finding to a disposed one by **what it says**, not by id — the reviewer mints
fresh ids every invocation. When it matches, record and dispose it the same way
with `"note": "restates r1-F002"` (§9); it does not buy another round.

`low` and `info` findings never buy a round either, whatever they say. Record
and dispose them, and carry anything unresolved into the approval message.

**A `fixed` disposition re-opens the loop only when its amendment is material**
(§6). Fixing a wording nit is immaterial: the hash moves, you approve against
the new one, and the converged round still stands because nothing it examined
changed. Fixing an owned path, a *Done when*, an evidence class, or the scope is
material: run another round against the new hash before asking for approval.
Without this rule, disposing a single `info` finding as `fixed` would silently
void the convergence you just reached.

Each round after an amendment is a **new invocation**, not `--resume`: the
artifact changed and the envelope must hash the new file. `--resume` exists only
to finish a `partial` or `interrupted` invocation. Give round N's prompt the
history so the reviewer is not re-deriving it:

```markdown
Round: <N>. The plan changed since your last review.
- r1-F001 (high) <summary> — fixed: <what changed in the plan>
- r1-F003 (medium) <summary> — rejected: <the user's reason>
- r1-F004 (blocker) <summary> — ACCEPTED by the user, deliberately not fixed:
  <their reason>
- r1-F005 (medium) <summary> — deferred-to-build: implementation detail, not a
  plan defect; batch <N>'s prompt re-surfaces it
Re-check the fixes and report anything still wrong or newly introduced. You may
flag the accepted item again; it is decided, and reporting it will not change
the plan.
```

**When the reviewer keeps finding new things.** The exit condition is the
**severity trend**, not a round count: the loop is done when a round produces
zero blocker/high findings after dispositions. Falling finding counts are not
that — a pilot run's counts fell 8, 6, 5, 4, 3 while round 4 caught a defect
that would have shipped silent data corruption, so "three rounds is enough" was
wrong the one time it was tested. What a round-3 check *is* for: when
blockers/highs are still arriving, stop spending silently and take it to the
user in one message — what keeps coming back, whether each item is a
restatement of something already disposed or genuinely new, and the ways out:
keep iterating (say how many more rounds and why), dispose the open findings
(`accepted`/`rejected` need their word; `deferred-to-build` is yours when §9's
test holds), or re-scope the plan and start the loop over from round 1.

---

## 9. Dispose every finding

Record each finding from a `complete` round **before** acting on it:

```json
{"e": "finding:recorded", "id": "r1-F001", "source": "plan-reviewer",
 "severity": "high", "summary": "<one line, verbatim from the envelope>",
 "location": "<the envelope finding's location, verbatim>",
 "detail": "<the envelope finding's detail, verbatim>",
 "round": 1, "invocation": "<the envelope's invocation id>",
 "plan_hash": "<plan.hash this round reviewed>",
 "codex": {"invocation_id": "<same>", "role": "plan-reviewer", "round": 1,
           "status": "complete", "envelope": "<path>",
           "input_hashes": ["<plan.hash>"], "duration_s": 366}}
```

`source` is the Codex **role** that produced it, from the same fixed enum that
`required_review` draws on (§6): `plan-reviewer` here, always.

**`location` and `detail` are copied from the envelope's finding verbatim** —
they are the envelope's own field names, adopted so nothing is re-worded on
the way into state. The overturn authority that gates accepted findings reads
the manifest, not the envelopes; a finding recorded without them gives that
gate one sentence and no file:line to rule from. A `recommendation` is carried
the same way when the source gave one. (The engine refuses a finding with an
empty `severity` or `summary`, and a Codex-sourced one without `invocation`.)

**Namespace the id by round.** Envelope ids (`F001`, `F002`, …) are unique only
within one invocation, so round 2's `F001` collides with round 1's and the
reducer refuses it: *"finding 'F001' already recorded"*. Use `r<N>-F0NN`.

**`round`, `invocation` and `plan_hash` are not decoration.** The id convention
is a string only you remember; these are fields anything can read. Together they
answer, from `rebuild` alone, how many rounds ran, which envelope produced a
finding, and **which plan version it was raised against** — and they are what
makes the severity trend visible, which §8 needs and a round count cannot see.
Put the `codex` block (`clodex` → Telemetry) on the **first** finding of the
round; the remaining findings of that round carry `round`/`invocation` but no
second `codex` block, since one round is one leg. A round that returns **no**
findings still has to be recorded, or the log cannot tell a clean round from a
round that never ran: put its `codex` block on the `plan:approved` event (§10),
or on the `plan:amended` if something else forced one.

Then dispose it. Every recorded finding reaches one of exactly four
dispositions — nothing is dropped, and "we talked about it" is not a state:

| Disposition | Means | Who decides |
|---|---|---|
| `fixed` | the plan was changed to address it — so this implies an amendment (§6) and a new hash, and §6's materiality test decides whether the review loop re-opens | you |
| `accepted` | legitimate, and the user chose not to act on it. It stands as a known risk and **survives into ship** | the user, explicitly — or a standing mandate granting `finding-disposition` (§6) |
| `rejected` | wrong — the reviewer misread the repo or the ask | the user, explicitly — or a standing mandate granting `finding-disposition` (§6) |
| `deferred-to-build` | true, but implementation detail rather than a plan defect — the plan is right; the finding is about how the owning batch should build it | you |

```json
{"e": "finding:disposed", "id": "r1-F001", "disposition": "fixed",
 "note": "batch 2 now owns migrations/; plan v2"}
```

`accepted` and `rejected` are overrides of an independent review, which is a
human-owned decision. Propose them — do not append them until the user has said
so, and quote their words in `note`. The one exception is a standing mandate
granting `finding-disposition` (§6): then the disposition is appended on its
authority, and the `note` cites the mandate plus the grounds instead of
quoting a user who was never asked. `fixed` is your own work and needs no
approval.

`deferred-to-build` is yours the way `fixed` is, but it is narrow: the finding
must be **true** and belong to implementation, not to the plan — a plan defect
deferred is a plan defect shipped. Its `note` must name the batch that answers
it, because deferral moves a finding, never deletes one: `clodex-build` §6
re-surfaces every deferred finding in the owning batch's prompt when that batch
opens, so what you defer is read again at exactly the moment it is actionable.

The snapshot keeps everything `finding:recorded` carried — id, source,
disposition, severity, summary, location, detail, recommendation, round,
invocation, plan hash — and the disposition's `note` is promoted into it too,
so the gate that reads the manifest sees the grounds. The event log remains
the authoritative record.

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

The reducer appends to `verification.declared` without de-duplicating, so two
things are on you. Declaring early and then amending leaves stale classes from a
superseded version in the manifest forever — hence "declare last". And a session
that died between these appends and `plan:approved` already declared some of
them, so on resume **append only the classes not already there**:

```bash
python3 "$STATE" rebuild "$RUN_DIR" |
  python3 -c 'import json,sys;print(" ".join(sorted({d.get("class") for d in json.load(sys.stdin)["verification"]["declared"]})))'
```

Anything that command prints is done. Declare the rest.

`clodex-verify` reads this list; do not describe or pre-empt what it does with it.

**Reconcile telemetry first** — `python3 "$STATE" telemetry-sync "$RUN_DIR"
"$REPO/.clodex/runner"` (`clodex` → Telemetry). Attach every block it prints
across the appends this section is about to make (`finding:disposed`,
`verification:declared`, `plan:approved` — one block per event): a review
round whose record is missing here is a round the run never provably spent.
`duration_s` and `status` in those blocks are the envelope's, never yours.

**Under a mandate granting `plan-approval`** (§6) the message below is
written to chat as a record rather than a question, and the appends carry
`by: "mandate"` — including any dispositions its `finding-disposition` grant
covers. A gate class the mandate does not grant still opens its modal.

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

On no: if they asked for a change, revise, amend (§6), re-open the review loop
when §6's materiality test says the amendment is material, and re-ask. If the
work should not go ahead at all, hand back to `clodex` — it owns closing and
abandoning a run, and this stage never does.

**Always pass `plan_hash` explicitly, recomputed from the file on disk.** The
reducer accepts an approval only against the **current** `plan.hash`; anything
else — a hash you copied from an earlier round, or the hash of a file you edited
without amending — is refused with *"approval binds to plan hash 'X' but the
current plan hash is 'Y'"*. Both mistakes fail loudly at append time, and the fix
for both is the same: amend first (§6) if the file really did change, then
approve the hash you actually have.

### What "approved" means, exactly

Read `python3 "$STATE" rebuild "$RUN_DIR"`. The plan is approved when **all
three** hold — and this is answerable from the manifest alone:

1. `plan.hash` is non-null.
2. `approvals` contains an entry with `scope: "plan"`, `plan_hash` equal to
   `plan.hash`, and `revoked: null`.
3. No entry in `findings` with `source: "plan-reviewer"` has
   `disposition: "open"`. Every one is `fixed`, `accepted`, `rejected`, or
   `deferred-to-build`.

Plus, when the direction gate was **yes**, a fourth: an `approvals` entry with
`scope: "direction"`, the same `plan_hash`, and `revoked: null`.

Fact 2's equality is now also an engine guarantee — an approval can only be
appended against the current hash — so a `revoked: null` approval is necessarily
on `plan.hash`. Keep testing it anyway: it is the clearest statement of the rule,
and it costs one comparison.

None of these is a feeling, and none of them is "the user seemed happy." If any
is missing, the plan is not approved.

**A separate question:** is the file on disk still the approved plan? Recompute
the sha256 of `plan.path` and compare it to `plan.hash`. Different means someone
edited the file without amending — append `plan:amended` (which revokes the
approval), re-open the review loop if §6's test calls the change material, and
approve again.

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
| Approving against any hash but the current one — a copied one, or the hash of a file you edited without amending | Refused: *"approval binds to plan hash 'X' but the current plan hash is 'Y'"*. Amend if the file changed, then approve `plan.hash`. |
| Looping forever because the reviewer keeps re-reporting a finding the user accepted | Convergence is measured on findings **not already disposed** (§8). A round that only restates disposed findings has converged. |
| Letting a `fixed` typo-grade finding void a converged round, or re-reviewing after every wording change | §6's materiality test decides: material ⇒ `required_review: ["plan-reviewer"]` and another round; immaterial ⇒ `[]` and no round. Either way, re-approve — the hash moved. |
| Committing the profile to record `docs.plans_dir` | This stage makes no commits. Use `docs/plans/`, say so once, move on (§2). |
| Declaring evidence right after recording the plan, or re-declaring on resume | Amendments leave stale classes in `verification.declared`, and the reducer does not de-dup. Declare immediately before `plan:approved`, and only the classes not already declared (§10). |
| Asking a question a file answers | Ground first (§2). Only blocking or decision-bearing questions reach the user. |
| Running the direction checkpoint for a data or refactor change | The gate is a predicate (§4), not a mood. `no` means no checkpoint. |
| Marking a finding `accepted` because it seemed minor | Only the user accepts or rejects a finding. Propose it in the approval message. |
| Disposing a plan defect as `deferred-to-build` to end the loop | Deferral is only for findings that are true **and** implementation detail (§9). A defect in scope, batches, or evidence is `fixed` or goes to the user. The note names the owning batch, and build re-surfaces it there. |
| Writing forbidden paths, batch contracts, or code | That is `clodex-build`. This stage declares owned paths and done-when. |
| Inventing an event name | The vocabulary is frozen at 23 names; the reducer refuses anything else. This stage appends eight of them: `stage:plan:entered`, `plan:recorded`, `plan:amended`, `approval:granted`, `finding:recorded`, `finding:disposed`, `verification:declared`, `plan:approved`. Something the names do not cover is a **field** on one of them — the optional `preflight` and `codex` blocks, and `finding:recorded`'s `severity`/`summary`/`location`/`detail`/`recommendation`/`round`/`invocation`/`plan_hash` (`clodex` → Telemetry). |
