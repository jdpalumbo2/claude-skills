---
name: clodex-audit
description: Use when the clodex router hands off a run whose lane is `audit` — a review / inventory / assessment ask with no change requested yet — or when a resumed run's manifest shows lane `audit` and the run is not closed.
---

# clodex-audit — investigate, tag every claim, route the follow-ons

## Overview

This lane earns its existence from usage evidence: two major audit asks ran
manually in one weekend, both excellent, and their report shape is encoded
here. It owes the run exactly three things:

1. A **report file** in the repo, at the profile's plans directory (or a
   `reports/` sibling when the repo has one), in the §5 shape.
2. Every claim in it **tagged** — `VERIFIED (<method>)` or `HYPOTHESIS
   (<what would confirm it>)` — with the load-bearing ones also recorded as
   findings (`finding:recorded`, `source: "audit"`) and the artifacts that
   prove them as evidence (`verification:evidence`).
3. The run **closed** with `release.state` untouched at `not-started` — an
   audit releases nothing, and its manifest must say so without ceremony.

**The manifest's stage stays `open` for the life of an audit.** The lane's
operational shape — open → investigate → report → closed — lives in this
document's sections, not in stage events: the vocabulary is frozen at 23
names, `stage:plan:entered` would be a lie, and a run at stage `open` with
lane `audit` is exactly how the router and the `runs` index recognize an
audit in flight. No build, no verify, no ship, ever; the follow-on work an
audit surfaces is routed per item (§5) into **new** runs.

You arrive here from `clodex`, which owns preflight, the profile, and the
run directory. Invoked without an absolute run dir → stop and invoke
`clodex`.

---

## 0. Paths and commands

```bash
CLODEX_HOME="${CLODEX_HOME:-$HOME/.claude/skills/clodex}"
STATE="$CLODEX_HOME/state/clodex_state.py"
RUN_DIR="<the absolute run dir the router handed you>"
SNAP="$(python3 "$STATE" rebuild "$RUN_DIR")"
REPO="$(printf '%s' "$SNAP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["repo"])')"
cd "$REPO"
```

Engine verbs, exit codes, and the lock rules are the `clodex` skill's
§"Paths and commands" and §2. Events are written to files and piped on
stdin, or passed inline with `append -e` for small ones.

---

## 1. Take the handoff

`python3 "$STATE" status "$RUN_DIR"` — expect `lane audit`, stage `open`.
Stage `closed` → this audit is done; say so and stop. Any other lane → wrong
skill; hand back to `clodex` naming the run dir.

Resume map, from the manifest: no findings and no evidence → §2. Findings or
evidence present but no report file at the path the log's latest evidence
item names → §4 mid-flight, keep investigating. Report file exists → §6.

---

## 2. The guardrail preamble — read-only, asserted up front

An audit that mutates what it audits has contaminated its own evidence. The
report **opens** with the guardrail preamble (§5), and you honor it from the
first command:

- **No writes to the repo** except the report file and `$RUN_DIR` artifacts.
  No fixes "while you are in there" — a defect you can fix in one line is
  still a finding, not an edit.
- **No live-data mutation, no credentialed writes, no deploys.** Live reads
  that a credential permits are legal when the profile's evidence
  expectations allow them; say in the preamble which live surfaces were read.
- **No git state changes**: no checkout, no stash, no branch. `git log`,
  `git show`, `git diff` are your instruments.

---

## 3. Corrections to the premises — mandatory, early

The prompt that commissioned the audit embeds assumptions, and auditing on
top of a false one produces a confident report about a world that does not
exist. Before investigating in depth, test every premise the ask states or
implies, and write the section even when the answer is "all premises held" —
the section existing is what forces the test. A premise correction that
re-scopes the audit goes to the user **now**, not in the final report.

---

## 4. Investigate

Work the repo, the history, the live-read surfaces the guardrails allow.
The discipline that made the manual audits trustworthy:

- **Every claim carries its tag.** `VERIFIED` claims name the method in the
  tag — `VERIFIED (ran the suite: 280 passed)`, `VERIFIED (read
  scheduler config live)` — because a VERIFIED with no method is a HYPOTHESIS
  wearing a costume. `HYPOTHESIS` claims name what would confirm them.
- **Load-bearing claims become findings.** Anything the report's verdicts
  rest on: `finding:recorded` with `source: "audit"`, non-empty severity and
  summary, `location`/`detail` filled the way `clodex-plan` §9 fills them
  from envelopes — here from your own investigation, file:line included.
  Findings are disposed before close (§6); most audit findings end
  `accepted` (they are the report's content, acknowledged by the user), and
  the engine's append-time validation holds here as everywhere.
- **Artifacts become evidence.** Command outputs, counts, screenshots,
  extracted tables land in `$RUN_DIR` and are recorded as
  `verification:evidence` items whose `how` is the exact command and whose
  `result` carries the numbers. An audit's authority is exactly its
  evidence discipline.
- **An evidence constraint is recorded, not worked around.** What you could
  not read — no access, no fixture, too risky live — shapes the report's
  §"evidence constraint" note. Never substitute inference for the missing
  read without downgrading the tag to HYPOTHESIS.

Codex roles are available through the runner (`advisor` for a second
opinion, read-only) with `--run-id "$(basename "$RUN_DIR")"`, telemetry
attached per `clodex` → Telemetry. Most audits need none.

---

## 5. The report

Write it in the §Overview's location, in this shape — every heading, in this
order. The shape is transcribed from the two reports that proved the lane.

```markdown
# <title> — audit, <date>

Run: <run-id> · guardrails: read-only <+ the live surfaces read, by name>

## Verdict
<Lead with the answers, one short paragraph per question the ask posed.
Verdict-first: a reader who stops here leaves correctly informed.>

## Corrections to the prompt's premises
<§3's findings, even when "all premises held". Each correction: the premise,
what is actually true, VERIFIED tag with method.>

## Evidence constraint that shaped this run
<What could not be read and why, and which conclusions are HYPOTHESIS
because of it. "None" is a legal entry.>

## Candidates — ranked by payoff against cost
<The changes worth making. FIXED SCHEMA per candidate, every field present:>
### C1 · <name>
- Problem: <what is wrong, VERIFIED/HYPOTHESIS tagged>
- Target: <what it should become>
- Size: <S/M/L, in batches or days>
- Migration risk: <what could break in the transition>
- What breaks if unaddressed: <the cost of doing nothing>
- Client benefit: <what the user of the system gains>
- Case-study benefit: <what the portfolio/story gains; "none" is honest>

## Deliberate-simplicity keeps
<What looks naive and is right — named so nobody relitigates it next
quarter. Each entry: the thing, why the simple form wins here.>

## Locked constraints
<What cannot change and why (contract, platform, client rule) — with an
ideal-world column that says what you would do absent the lock. Noted only;
the lock stands.>

## Surprises
<What the investigation found that nobody asked about. Often the section
that pays for the audit.>

## Small items
| item | fix | size |
|---|---|---|

## Routing — per item, which lane
<Every candidate and small item routed: feature-shaped → a clodex run with
this report as grounding; chore/repair/sync-shaped → named as such (those
lanes stay manual); "no action" is a routing. This section is what makes the
audit actionable instead of shelfware.>

## Sequencing
<Tiers gated by INSERTION COST, not abstract priority: what can land now
with nothing in flight, what must wait for X to merge, what wants its own
quiet window.>
```

Record the report the way plan records a plan — it is this lane's hashed
artifact:

```bash
python3 "$STATE" append "$RUN_DIR" -e "{\"e\": \"verification:evidence\",
 \"item\": {\"class\": \"tests\", \"how\": \"audit report written\",
  \"result\": \"<path> sha256 <hash>\"}}"
```

*(The `class` vocabulary is fixed; an audit report rides the evidence bucket
with its hash in `result` — the log then pins which bytes the user saw.)*

---

## 6. Dispose, present, close

Every `source: "audit"` finding gets a disposition. Present the report and
the findings in **one message**: the verdicts, each finding with your
proposed disposition (`accepted` for report-content findings the user
acknowledges; `rejected` for anything they show you misread), and the
routing section as the explicit next-actions list. A standing mandate
granting `finding-disposition` (`clodex-plan` §6) covers these dispositions
like any others.

Then close — release untouched:

```bash
python3 "$STATE" append "$RUN_DIR" -e '{"e": "run:closed"}'
```

`release.state` must still read `not-started`; if anything moved it, stop
and say so — an audit that touched release machinery has a finding to record
about itself. Archive per `clodex` §2's close step when the run lives in a
worktree. The follow-on work goes through `clodex` as new runs, each carrying
this run's id as `parent` when it directly executes a routed item.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Fixing a defect mid-audit "while you are in there" | Read-only guardrail (§2). It becomes a finding with a location, and the Routing section sends it to a lane. |
| A VERIFIED tag with no method | That is a HYPOTHESIS in costume. The tag carries the method or it downgrades. |
| Skipping the premise check because the prompt seemed right | §3 is mandatory and early — auditing on a false premise produces a confident report about a world that does not exist. |
| Appending `stage:plan:entered` to look like progress | An audit's stage stays `open` until `run:closed`. The lane field is what identifies it; a stage event here is a lie the manifest keeps. |
| Moving `release.state` | An audit releases nothing. `not-started` at close is the correctness condition, not an omission. |
| Content-free findings | The engine refuses empty severity/summary at append time; give every finding its location and detail — the overturn reader rules from state. |
| Ranking candidates by abstract priority | Sequencing tiers are gated by insertion cost — what the repo can absorb now vs after the next merge. |
