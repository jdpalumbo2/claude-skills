---
name: opus-orchestration
description: Use when orchestrating a large multi-deliverable task (document set, research corpus, audit, migration, parallel build) that should run end to end while conserving main-thread premium-model tokens, when the user asks for the Fable-plans-Opus-executes split or to protect usage limits on delegated work, or when dependent deliverables need adversarial verification to pass before dependents build on them. Primary substrate is local Opus worker terminals executing committed plans under an orchestrator session; a scripted Workflow variant remains for wide mechanical fan-out.
---

# Opus Orchestration

## Overview

Two-layer split, local-first. The **orchestrator session** (premium model, e.g. Fable) is the brain: it specs, writes committed plan documents, holds gates between dependent phases, sequences merges, does the final full review, and directs fixes. **Local Opus worker terminals** are the muscle: each is a full Claude Code session (`claude --model opus`) the user opens in another terminal, executing exactly one committed plan and reporting back to the orchestrator via `SendMessage` (workers locate it with `ListAgents`).

Why local terminals first: workers get the whole harness — live ssh, hooks, skills, human-in-the-loop steps like logins and token mints — and draw on subscription quota instead of API spend, while the orchestrator's context stays reserved for judgment. First production run: the crew build (mission-control, 2026-08-21) — two parallel workers, orchestrator-held go/no-go gates.

## When to use

- Multiple deliverables with dependencies, verification requirements, or research/build fan-out
- The user invokes this pattern, a goal prompt names it, or usage-limit pressure makes premium-model execution wasteful

**Not for:** single documents, small edits, or tasks with no verification bar. Just do those directly.

## Local worker mechanics

- **Plans are committed files** written to the executing-plans standard: assume a zero-context worker; exact paths, real code, verify steps, explicit stop-gates. The plan is the interface between orchestrator and worker — nothing load-bearing lives only in chat.
- **One worker per independent lane.** Dependent lanes don't get a worker until the upstream gate passes. The orchestrator writes the next plan only once the interfaces it consumes actually exist.
- **Worker prompt contract:** name the plan path, the executor skill (superpowers:executing-plans or the repo's clodex build lane), the checkpoint duty (SendMessage the orchestrator at each task checkpoint, blocker, and completion), and every stop-gate ("stop at the go/no-go and wait for the orchestrator").
- **Orchestrator duties:** never fabricate or predict a pending worker's state; field gates and blockers; sequence merges across workers and neighbor threads; schedule human-in-the-loop steps so two never collide; keep the final full review for itself.
- **Verification stays adversarial:** review goes to a different session than the one that wrote — a verifier worker, codex-plan-review for plans, codex-code-review for diffs. A worker never passes its own gate.
- **Models:** workers run Opus; drop lower only for purely mechanical lanes. The orchestrator stays premium.

## The phase recipe (per deliverable)

1. **Research fan-out.** Parallel Opus researchers, each a distinct angle, each instructed to load web tools via ToolSearch, cite every claim with URL and date, and label vendor versus third-party versus paper sources. Their output is raw data for the writer, not prose for a human.
2. **One writer.** Reads the binding rule files and upstream verified docs from disk, receives research inline. Returns a `summary` (max 200 words) plus a deviations log (every place a specific number or claim tempted it and what it wrote instead).
3. **Two adversarial verifiers in parallel.** One lens checks grounding: claims match cited sources and upstream docs, spot-checked by fetching. One lens checks rules: repo constraints, style, confidentiality, required coverage. Both return a verdict (`pass`, `issues[]` with severity). "Your job is to find problems, not to approve."
4. **Fix loop until pass** (see convergence rules), then the gate opens for dependents.

Every research sweep the documents cite gets persisted into the repo marked unaudited, so internal citations resolve to something a reader can open; unpersisted evidence is the most common verifier finding. Cleanest shape: each researcher writes its own sweep to an evidence directory (first line: an unaudited banner with the capture date) and also returns it inline for the writer.

## Convergence rules for fix loops

Learned the hard way: fix rounds that rewrite claims without re-checking sources introduce new errors, and a fresh full-document adversarial pass every round finds new tail issues forever.

1. **Fixer contract:** minimal edits only; before writing ANY comparative, pattern, or absence claim, verify it against the printed table or fetched primary source; print inputs, never derive numbers; update reuse sites when a fixed claim appears elsewhere; decline a listed issue only with fetched evidence quoted back.
2. **Reverify is scoped:** confirm each listed issue resolved, read 10 lines around each edit for collateral damage, treat newly rewritten claims as guilty until verified, then a mechanical style sweep. No new full-document expedition after the first round's full pass.
3. **Endgame:** when only small precisely specified issues remain, run one minimal-edit polish with the verifier's own quoted evidence embedded in the prompt, then a scoped check. Converge; do not whack-a-mole.

## Final review and report

After all gates pass, the orchestrator personally reads every deliverable in full against the source-of-truth docs. Trivial residual fixes: apply directly with Edit. Anything substantive: back to an Opus fix round. **Final report to the user, per file:** one-paragraph summary, verification status (rounds run, what was found and fixed), the deviations log, ending with the judgment calls only the user can make.

## Alternate substrate: Workflow scripts

When the fan-out is wide and mechanical — dozens of agents, schema-validated outputs, zero-token control flow — the scripted variant beats a handful of terminals: a deterministic **Workflow script** is the taskmaster (stages, fan-out, verify loops, gates in JavaScript), with Opus agents inside it as the muscle (`model: 'opus'` on every `agent()` call). Subagents cannot spawn subagents, so the script IS the orchestrator; the user asking for this pattern is the explicit opt-in the Workflow tool requires. Use [workflow-template.js](workflow-template.js) as the skeleton; it ran in production (~36 agents, five gated deliverables). Script constraints: only `agent()`, `parallel()`, `pipeline()`, `phase(title)`, `log()`, `args`, `budget`, `workflow()` exist — no `bash()`, no `Date.now()`, no filesystem; `phase()` takes a title string, pass `opts.phase` inside `parallel()`. Main thread blocks with `TaskOutput` (10-minute timeouts, repeat) and peeks at `journal.jsonl` for progress; between phases it reads verified summaries only, never raw research output.

## Common mistakes

| Mistake | Fix |
|---|---|
| Load-bearing instructions only in chat, not the plan file | The committed plan is the worker's whole world |
| A worker reviewing its own output | Adversarial review is a different session, always |
| Orchestrator narrates a pending worker's "probable" state | Report only received checkpoints |
| Two human-in-the-loop steps scheduled at once | Orchestrator owns the calendar of auth/login moments |
| Fresh full adversarial pass every fix round | Scoped reverify after round one; see convergence rules |
| Fixer rewrites a comparison from memory | Verify-before-writing; print inputs, never derive |
| Evidence lives only in the prompt | Persist sweeps to the repo, marked unaudited |
| (script mode) Spawning an orchestrator agent to spawn workers | Agents cannot nest; the script is the orchestrator |
| (script mode) `bash()` / `Date.now()` / `phase(fn)` | Not in the API; see template |
| (script mode) Omitting `model: 'opus'` | Agents inherit the session model; override every call |
| Ending with "workflow complete" | Deliver the per-file report contract |
