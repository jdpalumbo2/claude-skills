# dialectical-review

## What it is

A single-pass reasoning technique for testing a position before you commit to
it: state it as its strongest thesis, build the real antithesis (the strongest
good-faith counter-argument, not a strawman), then find the synthesis that
survives contact with both. No subagent, no tools — just a forced structure
that keeps you from skipping straight to "yeah, probably right."

The premise underneath it: nobody has to be wrong for the picture to be
incomplete.

## How it works

1. **State the thesis precisely** — the position in its strongest form. If it
   leans on an absolute ("we never…", "always…"), that quantifier is itself
   under test, not just the general direction.
2. **Build the real antithesis** — what the smartest person who genuinely
   disagrees would actually say, and why they're not simply wrong. If the
   counter-position is easy to dismiss, it wasn't the real one.
3. **Find the synthesis** — the fuller position that holds what both were
   pointing at. A real synthesis resolves the tension structurally; averaging
   the two ("do it sometimes") is a hedge, not a synthesis.

The output is explicitly structured under those three headers. That structure
is the mechanism — collapse it into an "other considerations" paragraph and
the antithesis gets gestured at instead of built.

A worked example, from the skill itself: thesis "we never discount — it
protects brand value"; antithesis: price-sensitive segments, rivals who do
discount, whole categories where discounting is the norm; synthesis: never
discount the core offer, but build a lower tier that captures price-sensitive
demand without eroding the premium anchor. More defensible than the absolute
rule, because it was tested against the reason the rule existed.

## What it's good for

The strategy or belief that feels right but nags — something not being said,
an absolute that hasn't actually been pressure-tested against the reason it
exists. Best run before a position goes into a client-facing document or gets
defended out loud, where the gap in it becomes someone else's finding instead
of yours. Also the specific case where two people (or two of your own
thoughts) both seem right and seem to conflict.

## Who it's for

Anyone who makes judgment calls for a living and wants arguing-the-other-side
to be a habit, not a thing that only happens when someone else pushes back.

It's one of three rigor skills that divide the territory: this one attacks a
**position**, `empirical-falsification` attacks a **fact**, and
`red-team-pressure-test` attacks **execution**. Reach for the one that matches
what's actually shaky.

## Install

```bash
ln -s "$(pwd)/skills/dialectical-review" ~/.claude/skills/dialectical-review
```
