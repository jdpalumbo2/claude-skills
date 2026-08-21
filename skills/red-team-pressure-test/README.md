# red-team-pressure-test

## What it is

Dispatches a genuinely independent subagent with one job: find every gap,
loophole, and weak assumption in a plan, ruthlessly, with no credit given for
what's good about it. Not a self-critique — the context that wrote the plan is
anchored on the reasoning that already convinced itself the plan was good, so
the adversary has to come from outside it.

The work isn't finished until someone has tried to destroy it.

## How it works

1. **The plan goes over verbatim** — exactly as it would be presented, with no
   framing that pre-defends it. Summarizing it first means the subagent
   attacks your paraphrase, which already smoothed over the weak parts.
2. **The subagent's brief is explicitly adversarial**: find every gap,
   loophole, and weak assumption; be ruthless; do not also list what's good.
   Each finding comes back as gap → why it matters → what breaks if
   unaddressed.
3. **The findings return as a structured list**, unfiltered — not folded into
   a diplomatic paragraph. Weak or stretch findings stay in; the person using
   this decides what to act on, not the messenger.

If no subagent capability is available in the current context, the skill says
so and asks — a self-critique quietly substituted for the real thing defeats
the point.

## What it's good for

The plan, pitch, contract, or decision that's about to get presented and
doesn't already run through a dedicated review lane. High-stakes calls where
being wrong is expensive: a client-facing commitment, a contract, a change to
a production automation.

Deliberately **not** for: quick low-stakes checks (independence costs a
subagent dispatch — don't spend it on something that doesn't warrant it), or
code changes and build plans that already have an adversarial pass built in —
a `clodex`/TRIP-style pipeline or a `codex-plan-review`/`codex-code-review`
pass exists precisely so code doesn't need this on top. This skill is for
everything else: strategy, pitches, anything belief- or business-shaped.

## Who it's for

Anyone who'd rather have a subagent find the gap on a Tuesday afternoon than
have a client or reality find it later, at a worse time.

It's one of three rigor skills that divide the territory: this one attacks
**execution** — what breaks, what was assumed, what nobody checked —
`dialectical-review` attacks a **position**, and `empirical-falsification`
attacks a **fact**.

## Install

```bash
ln -s "$(pwd)/skills/red-team-pressure-test" ~/.claude/skills/red-team-pressure-test
```
