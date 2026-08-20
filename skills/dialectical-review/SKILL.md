---
name: dialectical-review
description: Use when developing a strategy, defending a position, processing a belief, or something feels right but not the whole story — before presenting, committing to, or shipping it.
---

# Dialectical Review

## Overview

Take the current position as a thesis. Build its strongest good-faith antithesis — the real counter-position, not a strawman. Find where both are actually right. The synthesis that holds both is more defensible than the original.

Nobody has to be wrong for the picture to be incomplete.

## When to Use

- A strategy, plan, or belief feels right but something nags — it's not the whole story.
- Before presenting a position to a client, stakeholder, or in a document that will get scrutinized.
- Two people (or two of your own thoughts) both seem right and seem to conflict.

Not for: factual claims that just need checking (use empirical-falsification) or plans that need attacking for gaps (use red-team-pressure-test). Dialectical review is for positions and beliefs, not verifiable facts or execution risk.

## Core Pattern

1. **State the thesis precisely.** Write the position as its strongest form, not a vague gesture at it. If it uses absolute language ("never," "always," "full stop"), that quantifier is itself part of what needs testing — the antithesis should target whether the absolute holds, not just whether the general direction is right.
2. **Build the real antithesis.** Not the weakest opposing view — the strongest one, from someone who has genuinely thought about this and disagrees. Name what they'd actually say and why they're not simply wrong.
3. **Find the synthesis.** Where do both hold? State the fuller position that survives contact with the antithesis. It should be more defensible than the thesis alone, not just a hedge between the two.

## Example

Thesis: "We never discount — it protects brand value."
Antithesis: accessibility for price-sensitive segments, competitive pressure from rivals who do discount, lost market reach in categories where discounting is the norm.
Synthesis: never discount the core offer, but create a lower-tier product/tier that captures price-sensitive demand without eroding the premium anchor. More defensible than the absolute rule, because it was pressure-tested against the reason the rule existed to protect.

## Implementation

Do this inline — it's a single reasoning pass, not something requiring a subagent or external tool. Structure the output explicitly under three headers: **Thesis**, **Antithesis**, **Synthesis**. Don't collapse it into a vague "other considerations" paragraph — the structure is what forces the antithesis to be real instead of gestured at.

## Common Mistakes

- **Strawmanning the antithesis.** If the counter-position is easy to dismiss, it wasn't the real one. Steelman it — argue it as its strongest proponent would.
- **Synthesis as compromise, not synthesis.** Averaging the thesis and antithesis ("do it sometimes") is not a synthesis. A real synthesis explains *why* both were pointing at something true and resolves the tension structurally (see the discount example — the synthesis isn't "discount sometimes," it's a structural fix).
- **Skipping straight to synthesis.** If the antithesis wasn't stated in full, the synthesis is unearned — it'll just restate the thesis with a caveat bolted on.
