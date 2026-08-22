# opus-orchestration

## What it is

A process skill for running large multi-deliverable tasks — document sets,
research corpora, audits, migrations — end to end without burning the
premium main-thread model on delegable work. It's a strict split:

| Layer | Role | Cost |
|---|---|---|
| Orchestrator session (premium model) | The brain: specs, writes committed plan documents, holds gates between dependent phases, sequences merges, does the final full review, directs fixes | Spent sparingly |
| Local Opus worker terminals | The muscle: full Claude Code sessions (`claude --model opus`), one per independent lane, each executing one committed plan and reporting checkpoints back via SendMessage | The bulk of the work, on subscription quota |

Local terminals are the primary substrate: workers get the whole harness (live
ssh, hooks, skills, human-in-the-loop auth steps) and the committed plan file is
the entire interface between brain and muscle. A scripted **Workflow variant**
remains for wide mechanical fan-out (dozens of schema-validated agents,
zero-token control flow) — there the script *is* the orchestrator, since
subagents cannot spawn subagents. Ships with
[workflow-template.js](workflow-template.js), a production-proven skeleton for
that mode.

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
have to survive hostile review. Extracted from real end-to-end runs in both
modes (see below), every deliverable gated on adversarial verification before
its dependents started.

It assumes a harness where local sessions can message each other
(SendMessage/ListAgents or equivalent) for the primary mode, and a Workflow
(or equivalent scripted orchestration) tool with spawnable subagents for the
script variant; the user asking for the pattern is the explicit opt-in that
tool requires. Production runs: a five-deliverable research corpus (script
mode, ~36 agents) and the 2026-08-21 crew infrastructure build (local worker
mode, parallel terminals with orchestrator-held gates).

## Install

```bash
ln -s "$(pwd)/skills/opus-orchestration" ~/.claude/skills/opus-orchestration
```
