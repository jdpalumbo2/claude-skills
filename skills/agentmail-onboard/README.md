# agentmail-onboard

## What it is

Interactive walkthrough for onboarding a new **agentmail** agent — a
repo-bound AI persona with its own mailbox and Telegram channel, whose every
outbound email is released only by a human approval tap.

It's a driver, not a manual. The skill deliberately knows nothing about any
particular infrastructure — no hosts, ids, domains, or bot names. All of that
lives in your control-plane repo, whose onboarding runbook is the single
authority. If the skill and the runbook ever disagree, the runbook wins.

## How it works

1. **Read the runbook** — fully, fresh, every session. Never from memory of a
   previous run; the runbook changes as the platform learns.
2. **Interview first**: agent name, home repo, persona and charter, first
   allowlisted contacts. Nothing gets touched before the answers exist.
3. **Drive the runbook's numbered steps in order**, at the guardrail tier each
   step is marked with — automatable steps announced and executed, human steps
   (bot creation, secret handling, approval taps) handed over **one
   instruction per message**, waiting for the result before the next. Batched
   instructions get skipped or half-done; the pacing is the feature.
4. **Certification**: the runbook's end-to-end check matrix runs completely,
   with each check's actual result reported. A failed check stops the
   onboarding until fixed — "everything worked so far" is not the definition
   of worked.
5. **Documentation duties**: the runbook's same-session ledger section gets
   finished before the session ends.

Secrets never enter chat, command lines, or output — env-var names only,
always.

## What it's good for

Making agent #2, #3, #n a ~20-minute checklist instead of an afternoon of
re-derivation. Because the runbook stays the single source of truth in your
own repo, the skill never goes stale when your platform learns something new.

## Who it's for

People running an agentmail-style control plane: a gate workflow that queues
agent drafts for human-tapped release, an inbox watcher, and per-repo agent
kits. Built for my setup; if yours rhymes, take it — you'll need your own
control-plane repo with an onboarding runbook for it to drive.

## Install

```bash
ln -s "$(pwd)/skills/agentmail-onboard" ~/.claude/skills/agentmail-onboard
```
