# empirical-falsification

## What it is

Forces a claim through a real WebSearch pass — not recalled training-data
memory of what a source probably says — and reports a verdict: **holds**,
**falsified**, or **partially true** with the caveat spelled out. The most
expensive thing in any strategy is a claim nobody checked.

## How it works

1. **State the claim precisely.** Vague claims can't be falsified — pin down
   the exact assertion, numbers and scope included ("70% of X leave because of
   Y", not "people leave because of managers").
2. **Search for real evidence.** This is the step that matters: no answering
   from memory of what sources probably say. Live search, sources fetched and
   read.
3. **Follow the citation chain.** When a citation leads to another citation,
   keep going — until either a primary source (the actual dataset, study, or
   report) or two consecutive dead ends (a broken link, a page that doesn't
   contain the number it's cited for). The skill reports which one it hit; a
   stat repeated everywhere with nothing at the bottom of the chain is itself
   the finding.
4. **Report**: the claim as stated → the evidence found, with links → the
   verdict. "Partially true, with this caveat" is a valid, useful result.
   "I couldn't find a source either way" is reported as unverified, never
   quietly passed.

## What it's good for

The stat that's about to get repeated in a deck or strategy document and has
never actually been checked. The failure mode this exists to kill is specific:
an LLM confidently restating a plausible-sounding number with *more*
confidence, not less, each time it's been repeated — which is exactly
backwards from what should happen to an unverified claim.

## Who it's for

Anyone building on a claim that could get challenged in the room, where "I was
pretty sure that was right" isn't a good enough answer after the fact. It
requires an agent with a live web-search tool; if that's unavailable, the
skill says so rather than falling back to recalled citations.

It's one of three rigor skills that divide the territory: this one attacks a
**fact**, `dialectical-review` attacks a **position**, and
`red-team-pressure-test` attacks **execution**. It also composes underneath
the other two — an adversarial pass is only as good as the facts it's arguing
over.

## Install

```bash
ln -s "$(pwd)/skills/empirical-falsification" ~/.claude/skills/empirical-falsification
```
