<!-- clodex lane-brief template.

The 16-part anatomy that demonstrably carried output quality across a
five-lane weekend — including its bare control lane, whose equally good brief
produced an indistinguishable report. Brief anatomy, not run machinery, is
the quality engine; this file makes it reproducible instead of one
orchestrator's habit.

Two standing rules, before any brief is written:
1. The ORCHESTRATION PLAN IS COMMITTED before lanes fork. Lanes read merge
   order, rulings, and sibling scopes from a committed file, never from
   another worktree's uncommitted state or a chat scrollback.
2. Every brief requires the lane's report to OPEN WITH ITS RUN ID — or the
   word "bare" and why. That one line makes silent non-adoption impossible at
   gate time; a quintessential build lane once ran bare and nothing noticed.

Numbered parts below. Keep every one; write "none" rather than deleting a
heading — an absent part is an unanswered question, an explicit "none" is an
answer. Delete the comments. -->

# Lane <letter> — <one line: the deliverable>

## 1. Label and plan
Lane <letter> of <orchestration plan path, AT ITS COMMITTED SHA>. Your lane's
section: <heading/anchor>. Read it before anything below.

## 2. Where you work
Worktree `<path>` · branch `<name>` · base `<sha>` — which contains <what the
base holds that this lane depends on, e.g. "lane D's merged liveness work">.
Verify the base sha before your first commit; a lane fired early once absorbed
two extra merges because its prescribed base did not exist yet.

## 3. Prohibitions (caps-lock on purpose)
- NEVER push to <default branch>. NEVER merge. NEVER tag.
- NEVER touch <version source>, <changelog path>, <other release-owned files>.
- NEVER edit shared coordination state (`.clodex/claims.json`, the
  orchestration plan).
- <repo-specific: e.g. NEVER run the live-spend suite casually.>

## 4. Scoped exceptions
<Explicit, narrow releases from the rules above or from repo defaults —
"you MAY renumber your migration to 010 if 008/009 are taken", "you MAY push
your own feature branch". No exception listed = no exception.>

## 5. Required reading, section-precise
<File → section, not whole documents: "docs/ARCHI.md §transport", "the
orchestration plan §merge-order". A reading list without sections gets
skimmed; one with sections gets read.>

## 6. Human context
<One paragraph of why: what the client/user actually experiences, what
happened last time, why this lane exists. The implementer makes a hundred
small calls; this paragraph is what aligns them.>

## 7. Contract guardrails (non-negotiable)
<The behavioral invariants this lane must not break, stated as testable
sentences: "the fence stays fail-closed", "no live-data mutation", "existing
API responses byte-stable except the fields named in item 3".>

## 8. The work, numbered, with hooks
<Each item pre-located: file:line or function name, found by the brief's
author before the lane starts. An item without a hook costs the lane a search
and risks the wrong site.>
1. <item> — hook: `<file:line>` · done when: <checkable>
2. …

## 9. Out of scope
<Named carve-outs the lane might otherwise absorb: "the dashboard rendering
of this data is lane F's", "do not fix the flaky test you will trip over in
X — it is known". Prevents both scope creep and helpful trespassing.>

## 10. Decisions assigned to you
<For each: the decision, the 2–3 pre-named alternatives, and the CRITERION —
what "better" means here — so the lane decides instead of asking, and the
gate can audit the choice. "Choose between A/B for the retry shape; criterion:
fewest new failure modes under partial outage.">

## 11. Verification hints
<Where the proof lives: the suite that covers this area, the fixture that
exercises it, the real-data input to run, how to eyeball the visual class.>

## 12. Gate baselines — grow-them semantics
<Numeric: "extraction pytest 230 · dashboard vitest 495/84 · tsc clean".
The lane's exit counts must be >= these with its new tests on top. A baseline
that "moves during a rebase" is no baseline — pin the numbers here.>

## 13. Cross-lane conventions
<Shared naming, shared types, the claims your siblings hold
(`.clodex/claims.json`), which lane owns shared surfaces you touch, and what
to poll for if you must wait on a sibling (`git ls-tree <default> -- <path>`
via a Monitor — read-only, from committed truth).>

## 14. Sequencing inside the lane
<The order that avoids rework: "port the predicate before the trigger; the
trigger's tests pin the predicate's names".>

## 15. Style rules
<The repo's voice: comment discipline, naming, test style, commit-message
convention. Two lines, not a treatise — the codebase is the reference.>

## 16. REPORT BACK
Your report's FIRST LINE is your clodex run id — or the word "bare" and why.
Then exactly these sections, in this order: <enumerate — e.g. branch+commits ·
rebase/conflict log · contract-guardrail status · gate counts vs §12 baselines
· deploy/merge notes for the orchestrator · accepted residuals with finding
ids · what is still open for a human>. Use the lane-report template
(`$CLODEX_HOME/templates/lane-report.md`); the report structure you are given
here is the structure the merge gate reads, so treat it as an API.
