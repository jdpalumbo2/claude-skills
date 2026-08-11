---
name: opus-orchestration
description: Use when orchestrating a large multi-deliverable task (document set, research corpus, audit, migration) that should run end to end while conserving main-thread premium-model tokens, when the user asks for the Fable-plans-Opus-executes split or to protect usage limits on delegated work, or when dependent deliverables need adversarial verification to pass before dependents build on them.
---

# Opus Orchestration

## Overview

Three-layer split. The **main thread** (premium model, e.g. Fable) is the brain: it plans, authors workflow scripts, holds gates between phases, does the final full review, and directs fixes. A deterministic **Workflow script** is the taskmaster: stages, fan-out, verify loops, and gate logic live in JavaScript that costs zero model tokens. **Opus agents inside the script** are the muscle: research, drafting, adversarial verification, and fixes, every `agent()` call carrying `model: 'opus'` (drop to `sonnet`/`haiku` only for purely mechanical stages).

Subagents cannot spawn subagents. An "Opus orchestrator agent" middle layer stalls; the script IS the orchestrator. The user asking for this pattern is the explicit opt-in the Workflow tool requires.

## When to use

- Multiple deliverables with dependencies, verification requirements, or research fan-out
- The user invokes this pattern, a goal prompt names it, or usage-limit pressure makes premium-model drafting wasteful

**Not for:** single documents, small edits, or tasks with no verification bar. Just do those directly.

## The phase recipe (per deliverable)

1. **Research fan-out.** Parallel Opus researchers, each a distinct angle, each instructed to load web tools via ToolSearch, cite every claim with URL and date, and label vendor versus third-party versus paper sources. Their final text is raw data for the writer, not prose for a human.
2. **One writer.** Reads the binding rule files and upstream verified docs from disk, receives research inline. Returns structured output: `summary` (max 200 words) plus a deviations log (every place a specific number or claim tempted it and what it wrote instead).
3. **Two adversarial verifiers in parallel.** One lens checks grounding: claims match cited sources and upstream docs, spot-checked by fetching. One lens checks rules: repo constraints, style, confidentiality, required coverage. Both return a verdict schema (`pass`, `issues[]` with severity). "Your job is to find problems, not to approve."
4. **Fix loop until pass** (see convergence rules), then the gate opens for dependents.

Every research sweep the documents cite gets persisted into the repo marked unaudited, so internal citations resolve to something a reader can open; unpersisted evidence is the most common verifier finding. Cleanest shape: each researcher writes its own sweep to an evidence directory (first line: an unaudited banner with the capture date) and also returns it inline for the writer.

## Convergence rules for fix loops

Learned the hard way: fix rounds that rewrite claims without re-checking sources introduce new errors, and a fresh full-document adversarial pass every round finds new tail issues forever.

1. **Fixer contract:** minimal edits only; before writing ANY comparative, pattern, or absence claim, verify it against the printed table or fetched primary source; print inputs, never derive numbers; update reuse sites when a fixed claim appears elsewhere; decline a listed issue only with fetched evidence quoted back.
2. **Reverify is scoped:** confirm each listed issue resolved, read 10 lines around each edit for collateral damage, treat newly rewritten claims as guilty until verified, then a mechanical style sweep. No new full-document expedition after the first round's full pass.
3. **Endgame:** when only small precisely specified issues remain, run one minimal-edit polish with the verifier's own quoted evidence embedded in the prompt, then a scoped check. Converge; do not whack-a-mole.

## Main-thread mechanics

- Launch the workflow, then block with `TaskOutput` (10-minute timeouts, repeat). Peek at the run's `journal.jsonl` event counts for progress. Never fabricate or predict a pending result.
- Between phases read verified summaries only, never raw research output.
- Dependent deliverables do not start until the upstream verify passes. Independent ones may share one workflow concurrently.
- **Final review:** after all gates pass, personally read every deliverable in full against the source-of-truth docs. Apply trivial residual fixes directly with Edit; direct anything substantive back to an Opus fix round.
- **Final report to the user, per file:** one-paragraph summary, verification status (rounds run, what was found and fixed), the deviations log, ending with the judgment calls only the user can make.

## Script template

Use [workflow-template.js](workflow-template.js) as the starting skeleton; it ran in production. Inside a workflow script ONLY these exist: `agent()`, `parallel()`, `pipeline()`, `phase(title)`, `log()`, `args`, `budget`, `workflow()`. There is no `bash()`, no `Date.now()`, no filesystem. `phase()` takes a title string, not a callback; pass `opts.phase` on `agent()` calls inside `parallel()`. Shell work happens through an agent or in the main thread.

## Common mistakes

| Mistake | Fix |
|---|---|
| Spawning an Opus orchestrator agent to spawn workers | Script is the orchestrator; agents cannot nest |
| `bash()` / `Date.now()` / `phase(fn)` in scripts | Not in the API; see template |
| Omitting `model: 'opus'` | Agents inherit the session (premium) model; override every call |
| Fresh full adversarial pass every fix round | Scoped reverify after round one; see convergence rules |
| Fixer rewrites a comparison from memory | Verify-before-writing; print inputs, never derive |
| Evidence lives only in the workflow prompt | Persist sweeps to the repo, marked unaudited |
| Main thread reads raw research shards | Summaries and final files only |
| Ending with "workflow complete" | Deliver the per-file report contract |
