# claude-skills

Claude Code skills I actually run, maintain, and get asked for. Published because
people building their own agents keep wanting copies — but make no mistake about
the audience: these are made **for me, for people like me, by people like me**.
People who'd rather build a tool that fits their own hands than adopt someone
else's framework. If a skill here fits yours too, take it.

## How a skill works

A skill is a directory with a `SKILL.md`: the YAML frontmatter `description` is
the trigger (Claude reads it to decide when the skill applies), and the body is
the process it follows once loaded. Drop the directory into `~/.claude/skills/`
and it's live in your next session.

## Install

This repo is the canonical source — `~/.claude/skills` entries are symlinks into
it, so `git pull` updates every installed skill at once:

```bash
git clone https://github.com/jdpalumbo2/claude-skills
ln -s "$(pwd)/claude-skills/skills/jp-frontend-design" ~/.claude/skills/jp-frontend-design
```

## Catalogue

| Skill | What it governs | Pairs with |
|---|---|---|
| [jp-frontend-design](skills/jp-frontend-design/) | The ORDER of frontend design work: brief → tokens → hero screen → screenshot-critique loop → scale out | A craft-level design skill (e.g. Anthropic's `frontend-design`); a dataviz skill for charts |
| [agentmail-onboard](skills/agentmail-onboard/) | Onboarding a new email+Telegram agent against an agentmail control plane, one runbook step at a time | Your own control-plane repo holding the onboarding runbook it drives |
| [clodex](skills/clodex/) | The front door to a `plan → build → verify → ship` workflow for Claude Code + Codex CLI: preflight, resuming an interrupted run, the repo's `.clodex/profile.json`, and the change boundary a run starts from — v0.1 routes the feature lane only | The four `clodex-*` stage skills, installed beside it; a logged-in Codex CLI |
| [clodex-plan](skills/clodex-plan/) | The planning stage: a written plan, default-on Codex plan review with a disposition recorded per finding, the evidence classes done will have to prove, and an approval bound to the plan's content hash | `clodex`, which routes into it; `clodex-build`, which it hands the approved plan to |
| [clodex-build](skills/clodex-build/) | The execution stage: batches under a written contract of owned and forbidden paths, a reviewed delta before every commit, and commits that stage explicit pathspecs only | `clodex-plan`'s approved plan; the Codex implementer role, run through clodex's result-envelope runner |
| [clodex-verify](skills/clodex-verify/) | The evidence stage: the repo's own gates, plus every declared evidence class ending as either produced evidence or a recorded debt entry naming its reason and risk — it surfaces debt, it never gates on it | `clodex-build`'s commits; `clodex-ship`, where the debt is accepted once |
| [clodex-ship](skills/clodex-ship/) | The release stage, and the only one that acts outside the repo: one authorization over literal argv, two-phase steps that reconcile against the remote before they retry, and a terminal release state | `clodex-verify`'s evidence and debt; the action list in the repo's committed `.clodex/profile.json` |

One row per skill; each skill's own README covers what it is, what it's good
for, and who it's for.

## Acknowledgements

The quality floor, self-simulation slop test, and copy guidance in
`jp-frontend-design` adapt ideas from Anthropic's
[`frontend-design`](https://github.com/anthropics/claude-plugins) skill
(Apache 2.0).

`clodex` and its four stage skills descend from the
[TRIP workflow](https://github.com/PiLastDigit/TRIP-workflow) by PiLastDigit
(MIT) — the stage vocabulary and the Codex review roles originate there.

## License

MIT — see [LICENSE](LICENSE).
