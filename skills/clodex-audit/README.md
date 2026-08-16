# clodex-audit

## What it is

The audit lane of the clodex workflow: review / inventory / assess asks that
request no change yet. The `clodex` router opens a run with `lane: "audit"`
and hands it here; the lane investigates read-only, tags every claim
`VERIFIED (method)` or `HYPOTHESIS (what would confirm it)`, and closes with
a report whose last sections route every item to the lane that would execute
it.

It shipped in v0.2 on its own entry criterion — usage evidence: two major
audit asks ran manually in one weekend, both excellent, and this skill is
their report shape and discipline made repeatable. Repair, chore, and sync
remain deferred (the router still names those shapes and proposes the manual
approach); unused lanes rot, and those three have no such evidence yet.

The run model stays honest: an audit's manifest holds `lane: "audit"`, stage
`open` until close, `release.state` at `not-started` forever, findings with
`source: "audit"`, and evidence items for every artifact the report leans on
— all inside the frozen 23-event vocabulary.

## What it's good for

- **Verdict-first reports** a reader can stop reading at any depth of.
- **Premise correction before investigation** — the mandatory early section
  that catches an audit commissioned on a false assumption.
- **The three-bucket discipline** — candidates ranked by payoff/cost,
  deliberate-simplicity keeps (so nobody relitigates them), locked
  constraints with the ideal-world note.
- **Per-item lane routing and insertion-cost sequencing** — the difference
  between an audit and shelfware.

You do not invoke this skill directly. Invoke `clodex`; audit-shaped asks
route here from its §4.
