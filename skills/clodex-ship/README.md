# clodex-ship

## What it is

The release stage of the clodex core path (`plan → build → verify → ship`), and
the only stage that changes anything outside the repository. `clodex-verify`
hands it a run whose evidence and gaps are both written down; it turns that into
a version, a changelog entry, a commit, a tag, a push, a deploy, and a check that
the thing is actually live — or into an explicit, recorded boundary saying which
of those did not happen and why.

Two mechanisms do most of the work:

| Mechanism | What it means in practice |
|---|---|
| **One release authorization** | A single message enumerates every action the release will take — action id, the literal filled argv, working directory, target, and the *names* of credentials it needs — plus every verification debt entry being accepted. Approving it records those exact descriptors in the run. Anything not in that set stops the run, mechanically: the executor reads the argv back out of the approval rather than composing one. |
| **Two-phase steps that reconcile before they retry** | Every step writes a pending event with an operation id before it acts and a done or failed event after. A session that dies mid-push leaves that pending event behind, and the next session checks the remote before doing anything — so an interrupted release is reconciled against reality rather than replayed. |

Release state is a small state machine, not a feeling: `verified-live`,
`not-deployed`, and `abandoned` are terminal and close the run; `push-failed` and
`deploy-failed` are resumable and deliberately leave it open.

You do not invoke this skill directly. Invoke `clodex`; it works out which stage
you are in.

## What it's good for

- **One place where "ship it, with these gaps?" gets asked.** Verification debt —
  the live check nobody could run, the fixture that does not exist — is recorded
  earlier and accepted here, once, in the same message as the exact push and
  deploy it applies to. Never inferred from silence, never approved twice, never
  approved in the abstract hours before it mattered.
- **Commands a human approved character for character.** Actions come from the
  repo's committed profile, `{braced}` placeholders are filled from run state
  before anything is shown, and the string that was approved is the string that
  runs. Actions a repo marks `always-ask-exact` — the destructive ones, and the
  red-tier ones in repos with their own guardrail rules — are shown literally
  again immediately before every single execution, including retries after a
  crash.
- **Interrupted releases that do not double-fire.** "Tagged" is not "pushed" is
  not "deployed" is not "verified live", and each transition is persisted before
  it happens. Resume asks the world what is true — does the tag exist, did the
  remote advance, is the new version serving — and only then decides whether
  there is anything left to do.
- **Release commits that contain the release and nothing else.** The commit
  stages the changelog and the version file by explicit pathspec, so the work you
  had staged in your index before the run stays yours. A file that changed
  between review and commit halts it rather than landing unreviewed.
- **An honest ending, including "this did not go live."** A run that will not
  deploy is closed at an explicit `not-deployed` boundary with the reason
  recorded in the run — not left open forever, and not quietly marked done. A
  deploy nobody could verify is never recorded as verified.
- **A commit nobody planned cannot hide in a release.** Every commit between the
  run's start and its head is matched against the batches that own them; anything
  unowned is named, disposed by you, and itemised in the authorization next to
  the debt.

## Who it's for

Someone running the clodex workflow on their own repositories, who has tagged a
release that never got pushed, pushed one that never deployed, deployed one that
nobody checked, or answered "yes" to a release prompt without ever seeing the
literal command it was about to run.

It needs the `clodex` skill installed beside it (the state engine, the Codex
runner, and the repo's `.clodex/profile.json` all live there), a run handed over
by `clodex-verify`, a logged-in `codex`, git, and Python 3.9+.

## Install

```bash
ln -s "$(pwd)/skills/clodex-ship" ~/.claude/skills/clodex-ship
```
