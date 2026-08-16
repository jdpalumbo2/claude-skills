<!-- clodex handoff artifact template (clodex-ship §7A, release_owner: "external").

The run's deliverable when the release is externally owned: everything the
orchestrator needs to merge and deploy this branch without re-deriving a single
claim. Written into $RUN_DIR, recorded via approval:granted scope "handoff",
referenced from release.deployed. Every angle-bracketed value is filled from a
LIVE READ at write time; a value the writer cannot live-read is written as
`<verify: how>` so the consumer knows it is theirs to check, never a guess
dressed as a fact. Distilled from the artifact shape a real five-lane weekend
converged on. Delete the comments; keep every numbered section. -->

# Handoff — <run-id> · <one line: what this branch delivers>

## 1. Status, including what did NOT happen

Branch **`<branch>`** at **`<head sha>`** — <N> commits on top of base
**`<base sha>`** (<what the base contained when this run forked, e.g. "main
after lane D's merge">). Reviewed: <plan rounds, batch reviews, findings
disposed — one line>. Gates green (§6 has counts).

**NOT merged. NOT deployed. NOT tagged.** <Extend the enumeration with
anything else a reader might wrongly assume happened: NOT pushed (if so), no
version bump, no changelog entry — the negative space is the point of this
section.>

## 2. Commits

| sha | subject | what it carries |
|---|---|---|
| `<sha>` | <subject> | <one line — the thing a reviewer of the merge needs> |

`git log <base sha>..<head sha>` is exactly these <N>; nothing else rides.

## 3. Merge conditions

- **Slot:** <where this branch goes in the merge order, and why — e.g. "after
  lane D (shares the deals query surface), before lane G">.
- **Expected conflicts:** <files/hunks a merger will hit, from a trial rebase
  or the lane's own conflict log; "none expected" only after saying how you
  know>.
- **Held back:** <commits deliberately NOT on this branch and where they live,
  or "nothing held back">.

## 4. Deploy actions

<Numbered, exact commands, in order. The consumer runs these essentially
verbatim, so a placeholder is a live-read you failed to do — or a marked
`<verify: how>`. Include the negative test: a check that FAILS if the deploy
did not land, not only checks that pass when it did.>

1. `<exact command>` — <what it does; values live-read or marked <verify>>
2. …
3. Post-deploy checks: `<positive check>` and the negative test:
   `<a probe that must FAIL/refuse, proving the boundary still holds>`

## 5. Accepted residuals — yours to overturn pre-merge

<Every finding accepted (or deferred) during this run that ships with the
branch, BY ID, with severity and one line each. The ids join to the run log's
findings, which carry location/detail. These were accepted under delegated
authority; the merge gate is where a human can still overturn them.>

| id | severity | one line | grounds |
|---|---|---|---|
| `<r2-F007>` | <sev> | <summary> | <accepted why / deferred to where> |

## 6. Evidence index

| gate / class | result | baseline → now |
|---|---|---|
| <suite> | <rc + pass count> | <e.g. 230 → 280 (+50)> |
| <class: real-data / visual / …> | <what proved it, with the artifact path> | — |

<Counts against the pre-run baselines ("grow it" semantics). Name evidence
file paths as they exist in the ARCHIVED run dir (see §7), not a worktree
path that dies with the worktree.>

## 7. Run log

Run dir: `<archived location — <main-checkout>/.clodex/archive/<run-id>/ once
closed; the live $RUN_DIR until then>`. `python3 clodex_state.py status <run
dir>` answers what happened; the findings above resolve there by id.
