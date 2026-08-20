---
name: empirical-falsification
description: Use when a claim, statistic, or assumption is about to be repeated, cited, or built upon — especially in a deck, meeting, or strategy document — and hasn't been checked against real evidence.
---

# Empirical Falsification

## Overview

Check a claim against actual evidence — pass or fail — instead of against how plausible it sounds. Not vibes, not logic, not "this matches what I already believe": evidence.

The most expensive thing in any strategy is a claim nobody checked.

## When to Use

- A statistic or claim is about to be repeated in a deck, meeting, or document.
- You're building on an assumption that's never actually been verified.
- A "fact everyone knows" starts to feel shaky when you try to source it.
- Stakes are high and you don't want to be the one challenged on it in the room.

## Core Pattern

1. **State the claim precisely.** Vague claims can't be falsified — pin down the exact assertion, including any numbers or scope ("70% of X leave because of Y," not "people leave because of managers").
2. **Search for real evidence**, not recalled evidence. This is the step that matters: do not answer from training-data memory of what sources probably say. Use WebSearch (and WebFetch to check a source in full) to find what current, citable sources actually say.
3. **Report pass or fail against what was found**, with sources. If evidence is mixed or the claim is more nuanced than stated, say so — "partially true, with this caveat" is a valid, useful result, not a failure to reach a verdict.

## Implementation

This skill requires the WebSearch tool. Do not produce citations from memory — an LLM will confidently generate plausible-sounding sources that don't check out, which is the exact failure mode this skill exists to prevent. If WebSearch is unavailable, say so explicitly rather than falling back to recalled citations.

When a citation leads to another citation instead of a primary source, follow the chain — a stat repeated everywhere with nothing at the bottom of the chain is itself the finding. Stop once you reach either a primary source (the actual dataset, study, or report) or two consecutive dead ends (a broken link, a page that doesn't contain the number it's cited for). Report which one you hit.

Report format: **Claim** (as stated) → **Evidence found** (sources, with links) → **Verdict** (holds / falsified / partially true — specify what part).

## Common Mistakes

- **Citing from memory and calling it verification.** If no search happened, nothing was falsified — it was just restated with more confidence.
- **Treating "I couldn't find a source either way" as confirmation.** Absence of a counter-source is not evidence the claim is true — report it as unverified, not passed.
- **Softening a failed claim instead of reporting the failure.** If the stat doesn't hold up, say so plainly — that's the entire value of running this.
