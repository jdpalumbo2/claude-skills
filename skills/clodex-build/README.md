# clodex-build

## What it is

The execution stage of the clodex core path (`plan → build → verify → ship`).
`clodex-plan` hands it an approved plan; it hands `clodex-verify` a series of
commits.

Work happens in **batches**. Each batch runs under a written **contract** — the
paths it owns, the paths it must not touch, and the test command that has to be
green — which is handed to the Codex implementer role as a hashed input, so the
run can later prove which contract the work was done under. Nothing advances on
a model's say-so: the runner's result envelope decides, and the orchestrator
reviews the delta before it becomes a commit.

| Fact | Recorded as | In the run manifest |
|---|---|---|
| what a batch may touch | `batch:opened` | `batches[].owned_paths` |
| the delta was reviewed, and the verdict | `batch:reviewed` | `batches[].delta_review` |
| the commit it landed in | `batch:committed` | `batches[].commit` |
| an assumption that turned out wrong | `plan:amended` | `plan.amendments[]`, plus revoked approvals |

You do not invoke this skill directly. Invoke `clodex`; it works out which stage
you are in.

## What it's good for

- **A delegated implementer that cannot quietly widen its scope.** The contract
  names owned paths, and after every invocation the stage checks the working
  tree against them. A file the batch does not own showing up modified stops the
  run and goes to you as what it is — a scope change — rather than riding along
  in the next commit.
- **Release files that stay closed until release.** The changelog, the version
  source, and tags belong to `clodex-ship`, which writes them from evidence under
  a single authorization. Build treats them as forbidden in every batch, and says
  so in the contract the implementer reads. "May build touch the changelog?" has
  exactly one answer, and it is no.
- **Commits that contain only the batch's work.** Every commit stages explicit
  paths. Never `git add -A`, never `git add .`, never `git commit -a` — so the
  unrelated work in your tree cannot be swept into someone else's commit, and
  the pre-existing dirt the run acknowledged at open is left exactly where you
  put it.
- **Every delta reviewed before the next one starts.** The micro-gate is the
  repo's own test command, green. On top of that the orchestrator reads the
  whole staged diff against the batch's *Done when*, and consequential deltas get
  an independent Codex code review whose findings are recorded and disposed one
  by one. A batch that fails review is recorded as failed, then fixed, then
  reviewed again — the log keeps both verdicts.
- **An assumption breaking mid-build costing exactly what it should.** Amending
  the plan supersedes its content hash, and the state engine mechanically revokes
  every approval bound to the old hash — the original plan approval included,
  marked in place rather than dropped. The amendment says which completed work is
  affected and what re-review it triggers, and ship stays blocked until that
  re-review exists against the new plan. Nothing drifts quietly, and nobody has
  to remember that an approval went stale.

## Who it's for

Someone running the clodex workflow on their own repositories, who has watched a
delegated coding agent touch three files it was never asked to touch, or found
the version bumped twice because two stages both thought release bookkeeping was
theirs, or discovered at release time that the thing built was not the thing
approved.

It needs the `clodex` skill installed beside it (the state engine, the Codex
runner, and the repo's `.clodex/profile.json` all live there), an approved plan
from `clodex-plan`, a logged-in `codex`, git, and Python 3.9+.

## Install

```bash
ln -s "$(pwd)/skills/clodex-build" ~/.claude/skills/clodex-build
```
