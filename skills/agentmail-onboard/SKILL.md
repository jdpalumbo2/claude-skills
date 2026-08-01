---
name: agentmail-onboard
description: Use when onboarding a new agentmail agent — giving a repo its own email and Telegram identity behind the human-approval send gate. Triggers - "onboard a new agentmail agent", "onboard an email agent", "give this repo an email identity", "give this repo a mailbox and Telegram identity", or an explicit /agentmail-onboard <name>. Requires an agentmail control-plane repo containing an onboarding runbook. NOT for generic software-agent scaffolding, bots without email, or repos outside an agentmail setup.
---

# agentmail-onboard

## Overview

Interactive driver for onboarding ONE new agentmail agent. This skill contains
no facts about any specific infrastructure — no hosts, ids, domains, or bot
names. All of that lives in the operator's control-plane repo, whose onboarding
runbook is the single authority. This skill's job is pacing and discipline:
read the runbook, interview the operator, drive the steps in order, never skip
the verification.

**Core principle: the runbook is the source of truth. If this skill and the
runbook ever disagree, the runbook wins.**

## Prerequisites

- The agentmail control-plane repo, default `~/code/mission-control` — if it is
  not there, ask the operator where it lives before doing anything else.
- Inside it: `docs/agentmail-onboarding.md` (the runbook). Missing → stop and
  say so; do not improvise an onboarding.
- Read the control-plane repo's `CLAUDE.md` first — its guardrail tiers govern
  every action this walkthrough takes.

## Process

1. **Read the runbook** — fully, fresh, this session. Never drive from memory
   of a previous run; the runbook changes as the platform learns.
2. **Interview** before touching anything: agent name, target repo (default:
   the current working directory — confirm it), persona/charter answers (what
   the agent does, who it corresponds with, voice, boundaries), and the first
   allowlisted contacts.
3. **Drive the runbook's numbered steps in order.** For each step:
   - Steps the assistant performs: execute at the tier the runbook marks —
     announce-then-proceed steps get the announcement, wait-for-approval steps
     get presented and WAIT.
   - Steps the operator performs (phone apps, pasting into editors, running
     `!`-prefixed commands, approval taps): give **exactly one instruction per
     message**, then wait for the result before the next. Batched instructions
     get skipped or half-done.
4. **Certification**: run the runbook's E2E matrix section completely. Report
   each check's actual result; a failed check stops the onboarding until fixed.
5. **Documentation duties**: finish the runbook's same-session ledger section.
   Commit or push nothing unless the operator asks.

## Red flags — stop and correct

| About to… | Instead |
|---|---|
| Describe a step from memory | Re-read that runbook section first |
| Put two or more operator actions in one message | Split; one instruction, then wait |
| Let a secret value into chat, a command line, or output | Env-var names only, always |
| Skip E2E checks because "everything worked so far" | The matrix is the definition of worked |
| Substitute a "better" step order | The runbook's order encodes hard-won failures |
