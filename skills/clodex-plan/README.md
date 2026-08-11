# clodex-plan

## What it is

The planning stage of the clodex core path (`plan → build → verify → ship`). The
`clodex` router hands it a run; it hands `clodex-build` an approved plan.

It produces four things, and they are all facts in the run's event log rather
than claims in a transcript:

| Artifact | Where it lives |
|---|---|
| The plan document | the repo, at the profile's `docs.plans_dir` |
| Its version, path, and sha256 hash | `plan:recorded` / `plan:amended` |
| A disposition for every review finding | `finding:recorded` / `finding:disposed` |
| The evidence classes done will require | `verification:declared` |

Approval is `plan:approved`, bound to the plan's content hash. Change the plan
and that approval is mechanically revoked — not by anyone remembering to, but
because the hash it points at no longer exists as the current plan.

You do not invoke this skill directly. Invoke `clodex`; it works out that
planning is what you need.

## What it's good for

- **Dense briefs going straight to work.** There is no unconditional
  requirements ceremony. If the ask already says what to build, the only
  questions that reach you are the ones a file cannot answer — blocking, or a
  decision that is genuinely yours to make. Everything else is resolved by
  reading the repo and written down as a stated assumption.
- **Taste getting its say before the code exists.** Work whose acceptance is
  visual, editorial, or positional gets its premise and comps approved first.
  Work that is data, pipeline, refactor, or infrastructure does not — that gate
  would be pure ceremony, and the skill answers the question with a checkable
  predicate over the ask and the paths, not a judgment call.
- **Knowing what "done" will have to prove, before anyone starts.** Every plan
  declares its evidence classes — automated tests, production-shaped data, a
  live check, a look at the rendered thing — drawn from the repo's defaults and
  overridable per plan, with any dropped default argued in writing. An
  offline-green test suite is no longer allowed to stand in for proof it works.
- **Independent review that converges instead of drifting.** Codex reviews every
  plan, default-on. Rounds are machine-checked result envelopes, not prose: a
  review that stopped short cannot be mistaken for one that finished, and an
  envelope that hashed a different file cannot be mistaken for a review of this
  one. The loop has a defined end and a defined cap, and hitting the cap is a
  conversation rather than another round.
- **Overrides that survive.** A finding you decide not to act on is recorded as
  `accepted`, with your words attached. It is still there at ship. Nothing gets
  quietly dropped between "we discussed it" and "we shipped it."
- **A plan that answers "is this approved?" without anyone's memory.** Three
  facts in the run manifest, checkable by a session that has never seen the
  conversation.

## Who it's for

Someone running the clodex workflow on their own repositories, who has been
burned by plans that drifted from the thing that got approved, by review
findings that evaporated between the review and the release, and by "all tests
pass" meaning something narrower than it sounded.

It needs the `clodex` skill installed beside it (state engine, Codex runner, and
the repo's `.clodex/profile.json` all live there), a logged-in `codex`, and
Python 3.9+.

## Install

```bash
ln -s "$(pwd)/skills/clodex-plan" ~/.claude/skills/clodex-plan
```
