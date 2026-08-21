# opus-orchestration

## What it is

A process skill for running large multi-deliverable tasks — document sets,
research corpora, audits, migrations — end to end without burning the
premium main-thread model on delegable work. It's a strict three-layer split:

| Layer | Role | Cost |
|---|---|---|
| Main thread (premium model) | The brain: plans, authors the workflow script, holds gates between dependent phases, does the final full review, directs fixes | Spent sparingly |
| Deterministic Workflow script | The taskmaster: stages, fan-out, verify loops, and gate logic live in JavaScript | Zero model tokens |
| Opus agents inside the script | The muscle: research, drafting, adversarial verification, fixes | The bulk of the work |

One structural fact drives the whole design: subagents cannot spawn subagents,
so an "orchestrator agent" middle layer stalls — the script *is* the
orchestrator. Ships with [workflow-template.js](workflow-template.js), a
production-proven script skeleton.

## How it works

Each deliverable moves through the same phase recipe: a **research fan-out**
(parallel Opus researchers, distinct angles, every claim cited with URL and
date), **one writer** (reads the binding rule files and upstream verified docs
from disk, logs every deviation), **two adversarial verifiers in parallel**
(one lens checks grounding against sources, one checks rules and required
coverage — "your job is to find problems, not to approve"), then a **fix loop
until pass**. Dependent deliverables don't start until the upstream verify
passes.

The fix loop carries hard-won convergence rules: minimal edits only,
verify-before-writing on any comparative claim, scoped reverification after
the first round instead of a fresh full-document expedition every round —
because fresh verifiers find new tail issues forever, and fixers rewriting
claims from memory introduce new errors while fixing old ones.

## What it's good for

Protecting usage limits on big delegated builds without giving up verification
rigor. The verify machinery is the point — adversarial review per deliverable
plus a fix loop that actually terminates instead of playing whack-a-mole. The
main thread reads verified summaries between phases, never raw research
output, and ends with a per-file report: what was verified, what was fixed,
what deviated, and the judgment calls only the user can make.

## Who it's for

People whose main-thread model is the expensive one and whose deliverables
have to survive hostile review. Extracted from a real five-deliverable
research build where the pattern ran end to end: ~36 Opus agents, every
document gated on adversarial verification before its dependents started.

It assumes an agent harness with a Workflow (or equivalent scripted
orchestration) tool and spawnable subagents; the user asking for the pattern
is the explicit opt-in that tool requires.

## Install

```bash
ln -s "$(pwd)/skills/opus-orchestration" ~/.claude/skills/opus-orchestration
```
