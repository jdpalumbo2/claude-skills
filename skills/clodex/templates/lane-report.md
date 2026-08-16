<!-- clodex lane-report template.

The shape six independent lane reports converged on in one weekend — because
each brief's REPORT BACK line demanded it, and the merge gate consumed it
essentially verbatim. It is the handoff artifact's sibling
(templates/handoff.md): a report tells the ORCHESTRATOR what happened in the
lane; the handoff artifact equips the EXTERNAL OWNER to release. When the
run is `release_owner: "external"`, write both and let §4 here point at the
artifact rather than duplicating its deploy-actions section.

Every claim traces to something checkable — an exec id, a file:line, a count,
an md5, a screenshot path IN THE ARCHIVED RUN DIR. The gate spot-checks;
untraceable claims fail the spot-check by existing. Delete the comments. -->

<run-id — THE FIRST LINE, before anything else; or "bare" and why>

# Lane <letter> complete — <one line: what exists now>

## 1. Status, and what did NOT happen
Branch **`<name>`** at **`<head sha>`**, <N> commits on **`<base sha>`**.
**NOT merged, NOT deployed, NOT tagged<, NOT pushed — extend as true>.**
Release state recorded: `<handed-off | not-deployed | …>`. Verification:
<N evidence, N debt> — quote `status`'s line.

## 2. The work, against the brief
<One block per numbered brief item: what was built, where (file:line), and
the evidence that its "done when" holds. Item numbers are the brief's — the
orchestrator diffs this section against what they asked for.>

## 3. Contract guardrails
<Each §7 guardrail from the brief, with the proof it still holds — the test
that pins it, the probe that refused, the diff that shows the surface
untouched.>

## 4. Gates, counts against baselines
| gate | baseline → now |
|---|---|
| <suite> | <230 → 280 (+50: what the new tests cover)> |

<Counts, never bare rcs. A rebase or merge resolution in this lane adds the
test-inventory NAME diff here (clodex-build §8) — counts survive a silently
deleted test; the name list does not.>

## 5. Rebase / conflict log
<Only when the lane rebased or merged: picks clean vs conflicted, files and
hunk counts, both-sides resolutions, anything skipped by design, any
resolution casualty caught and restored. "No rebase" is the whole section
otherwise.>

## 6. Accepted residuals — with finding ids
<Every accepted/deferred finding riding this branch, BY ID, one line each.
The ids resolve in the run log with location/detail and the disposition
grounds. These are the orchestrator's to overturn pre-merge.>

## 7. For the orchestrator
<Merge slot and expected conflicts; anything held back; the deploy-window
actions — or, for an external-owner run, one line: "deploy actions are in the
handoff artifact: <path>". Then what is still open for a human, named.>

## 8. Run log
<The archived run dir path (`<main-checkout>/.clodex/archive/<run-id>/` once
closed), so every pointer above outlives the worktree.>
