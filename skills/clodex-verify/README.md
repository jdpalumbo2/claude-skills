# clodex-verify

## What it is

The evidence stage of the clodex core path (`plan → build → verify → ship`).
`clodex-build` hands it a series of commits; it hands `clodex-ship` a run whose
every claim about "done" is either proven or written down as a known gap.

It runs two lists: the repo's own gates from `.clodex/profile.json` — test,
lint, typecheck, build — and the evidence classes `clodex-plan` declared and the
user approved. Every declared class ends in exactly one of two states, and the
run manifest can be checked for it mechanically:

| Outcome | Recorded as | In the run manifest |
|---|---|---|
| the class was produced | `verification:evidence` | `verification.evidence[]` |
| the class was deferred | `verification:debt` | `verification.debt[]` |

A debt entry carries three fields: the class, the reason it could not be
produced, and the risk of shipping without it.

**This stage has no gate.** It records debt and surfaces it; it never accepts,
waives, or blocks on it. Acceptance happens once, later, inside `clodex-ship`'s
release authorization — the same message that enumerates the exact commands and
targets the release will run.

You do not invoke this skill directly. Invoke `clodex`; it works out which stage
you are in.

## What it's good for

- **"All tests pass" no longer standing in for "it works."** The plan said what
  proof done required — automated tests, production-shaped data, the deployed
  thing observed, the rendered thing looked at — and this stage produces those
  specific things. A green offline suite satisfies the class it covers and
  nothing else.
- **Deferred proof that survives to the decision that needs it.** Real work
  defers checks: the credential is not on this machine, nothing is deployed yet,
  the fixture does not exist. Each of those becomes a debt entry naming what it
  is and what could go wrong because of it, carried in the run manifest to the
  release authorization — instead of a sentence in a chat log nobody re-reads.
- **One debt decision, in the right place.** Verify does not ask you to bless
  anything. The single time you are asked to accept verification debt is when
  you are also being shown the exact push, tag, and deploy it applies to, so the
  question is "ship this, with these gaps?" rather than an abstract "OK?" hours
  earlier.
- **A verification stage that cannot quietly become a fixing stage.** It makes
  no commits and touches no tracked file. A red gate or a test that does not
  prove what it claims is recorded as a finding and goes to you, because fixing
  it is build's work under a batch contract with a delta review — not an
  unreviewed edit made by whoever happened to be running the suite.
- **An independent read on whether the tests prove anything.** When the evidence
  is carrying real weight, a read-only Codex reviewer looks for the "done when"
  no test exercises and the test that would still pass with its behaviour
  removed. It reports findings; it cannot write to your tree.
- **A completeness property you can check rather than trust.** One script over
  the manifest prints, per declared class, whether it ended in evidence or in
  debt, and refuses to say `VERIFY COMPLETE` while any class is in neither — or
  in both.

## Who it's for

Someone running the clodex workflow on their own repositories, who has shipped
behind a green test suite and found the defect in production anyway, or agreed
to "we'll check that after the deploy" and never checked, or discovered at
release time that the thing everyone meant to verify was never written down
anywhere.

It needs the `clodex` skill installed beside it (the state engine, the Codex
runner, and the repo's `.clodex/profile.json` all live there), a run built by
`clodex-build`, a logged-in `codex`, git, and Python 3.9+.

## Install

```bash
ln -s "$(pwd)/skills/clodex-verify" ~/.claude/skills/clodex-verify
```
