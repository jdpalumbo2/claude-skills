---
name: red-team-pressure-test
description: Use when about to present, ship, or commit to a plan, pitch, contract, or decision, and want every gap and weak assumption found before a client, stakeholder, or reality finds it.
---

# Red Team Pressure Test

## Overview

The work isn't finished until someone has tried to destroy it. Dispatch an adversary whose only job is to find every gap, loophole, and weak assumption — ruthlessly, not softened.

## When to Use

- About to present a plan, launch something, or defend a position, and want to hear every gap from a fresh source before someone in the room finds it.
- High-stakes decision where being wrong is expensive: a contract, a client-facing plan, a change to a production automation.

Not for: quick low-stakes checks — the point of this skill is genuine independence, which costs a subagent dispatch. Don't reach for it on something that doesn't warrant that cost. Also not for a code change or build plan that already runs through a dedicated review lane (a `clodex`/TRIP-style pipeline, a `codex-plan-review`/`codex-code-review` pass) — those exist precisely so code doesn't need this skill on top. This is for the plans and decisions with no other adversarial pass built in: strategy, pitches, contracts, anything client-facing or belief-shaped rather than code-shaped.

## Core Pattern

Self-critique from the same context that produced the plan is weak — it's anchored on the reasoning that already convinced itself the plan was good. Real adversarial pressure needs a fresh, independent pass with no investment in the plan succeeding.

1. **State the plan or claim in full**, exactly as it would be presented, with no framing that pre-defends it.
2. **Dispatch a subagent via the Agent tool** with an explicitly adversarial brief: its only goal is to find every gap, loophole, and weak assumption, and to be ruthless about it — not to also list what's good. Give it the plan verbatim; don't summarize it into your own words first, or it'll end up interrogating your paraphrase instead of the plan.
3. **Return the subagent's findings as a structured list** — gaps, weak assumptions, failure points — not folded into a diplomatic paragraph. If a finding is weak or a stretch, keep it in the list rather than pre-filtering; the person using this decides what to act on.

## Implementation

Dispatch with the Agent tool, subagent_type `general-purpose` (or a more specific reviewer type if one fits the domain, e.g. a code-review agent for a technical plan). Prompt shape:

> Red-team this plan. Your only job is to find every gap, loophole, and weak assumption — be ruthless, do not soften findings or list what's good about it. [full plan text]. Report as a structured list: gap → why it matters → what breaks if unaddressed.

Run it in the foreground if the result is needed before the next step; background if the review can land while other work continues.

If the Agent tool isn't available in the current context, say so explicitly and ask before critiquing the plan yourself in-context — a self-critique quietly substituted for the real thing defeats the point and shouldn't happen silently.

## Common Mistakes

- **Critiquing it yourself instead of dispatching.** The same context that wrote the plan is bad at finding its own blind spots — that's what makes this different from just asking "any concerns?" in the same turn.
- **Paraphrasing the plan before handing it off.** The subagent should attack the actual plan, not a summary that already smoothed over the weak parts.
- **Softening the findings on the way back.** Report the list as the subagent returned it — filtering out the findings that feel unlikely defeats the purpose.
