# agentmail-onboard

Interactive walkthrough for onboarding a new **agentmail** agent — a repo-bound
AI persona with its own mailbox and Telegram channel, whose every outbound email
is released only by a human approval tap.

**What it is.** A driver, not a manual. The skill deliberately knows nothing
about any particular infrastructure; it locates your agentmail control-plane
repo, reads its onboarding runbook, interviews you (agent name, home repo,
persona, first contacts), and then walks the runbook's steps with you — doing
the automatable parts itself under your guardrail tiers, and handing you the
human steps (bot creation, secret handling, approval taps) one at a time.

**What it's good for.** Making agent #2, #3, #n a ~20-minute checklist instead
of an afternoon of re-derivation. Because the runbook stays the single source
of truth in your own repo, the skill never goes stale when your platform
learns something new.

**Who it's for.** People running an agentmail-style control plane: a gate
workflow that queues agent drafts for human-tapped release, an inbox watcher,
and per-repo agent kits. Built for my setup; if yours rhymes, take it — you'll
need your own control-plane repo with a `docs/agentmail-onboarding.md` runbook
for it to drive.
