# workbench

**Claude Code skills I actually run, maintain, and get asked for.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Works with Claude Code](https://img.shields.io/badge/Claude_Code-D97757)](https://claude.com/claude-code)
[![Works with Codex CLI](https://img.shields.io/badge/Codex_CLI-10A37F)](https://developers.openai.com/codex/cli/)

Published because people building their own agents keep wanting copies — but
make no mistake about the audience: these are made **for me, for people like
me, by people like me**. People who'd rather build a tool that fits their own
hands than adopt someone else's framework. If a skill here fits yours too,
take it.

*Formerly `claude-skills`; renamed August 2026. The old URL redirects.*

## How a skill works

A skill is a directory with a `SKILL.md`: the YAML frontmatter `description` is
the trigger (Claude reads it to decide when the skill applies), and the body is
the process it follows once loaded. Drop the directory into `~/.claude/skills/`
and it's live in your next session.

## Install

This repo is the canonical source — my `~/.claude/skills` entries are symlinks
into it, so `git pull` updates every installed skill at once:

```bash
git clone https://github.com/jdpalumbo2/workbench
ln -s "$(pwd)/workbench/skills/jp-frontend-design" ~/.claude/skills/jp-frontend-design
```

Install only what you'll use. The `clodex-*` stage skills expect the `clodex`
router installed beside them; everything else stands alone.

## Catalogue

Three shelves. The tables below say what each skill governs; each skill's own
README covers how it works, what it's good for, and who it's for.

### The clodex pipeline

A development workflow for Claude Code + Codex CLI: one front door, four
stages, and an audit lane. Claude orchestrates; Codex independently reviews
plans and code and implements under contract; every run is a durable event log
that survives a dead session. It descends from the
[TRIP workflow](https://github.com/PiLastDigit/TRIP-workflow) by PiLastDigit —
lineage and the full workflow diagram live in the
[clodex README](skills/clodex/README.md).

```mermaid
flowchart LR
  clodex([clodex]) --> plan --> build --> verify --> ship
  clodex --> audit
```

| Skill | The stage it owns |
|---|---|
| [clodex](skills/clodex/) | The front door, and the shared engine the stages import: preflight, resuming interrupted runs, the repo's committed profile, lane routing, and the change boundary a run starts from |
| [clodex-plan](skills/clodex-plan/) | A written plan, default-on Codex review with a disposition recorded per finding, the evidence classes "done" will have to prove, and an approval bound to the plan's content hash |
| [clodex-build](skills/clodex-build/) | Batches under a written contract of owned and forbidden paths, a reviewed delta before every commit, and commits that stage explicit pathspecs only |
| [clodex-verify](skills/clodex-verify/) | The repo's own gates, plus every declared evidence class ending as either produced evidence or a recorded debt entry naming its reason and risk — surfaced, never waived here |
| [clodex-ship](skills/clodex-ship/) | The only stage that acts outside the repo: one authorization over literal argv, two-phase steps that reconcile against the remote before they retry, and a terminal release state |
| [clodex-audit](skills/clodex-audit/) | The read-only lane: every claim tagged `VERIFIED (method)` or `HYPOTHESIS`, a verdict-first report, and per-item routing that feeds follow-on runs |

### Rigor

Three skills, one discipline, three targets: `dialectical-review` attacks a
**position**, `empirical-falsification` attacks a **fact**,
`red-team-pressure-test` attacks **execution**. They compose — an adversarial
pass is only as good as the facts it's arguing over — and they exist for
everything that already doesn't have a dedicated review lane the way code does.

| Skill | What it governs |
|---|---|
| [dialectical-review](skills/dialectical-review/) | Pressure-testing a strategy or belief in one reasoning pass: state it as its strongest thesis, build the real antithesis, find the synthesis that survives both |
| [empirical-falsification](skills/empirical-falsification/) | Checking a claim against real search evidence instead of recalled confidence, following citation chains to a primary source or two dead ends, and reporting holds / falsified / partially true |
| [red-team-pressure-test](skills/red-team-pressure-test/) | Dispatching a genuinely independent adversarial subagent to find every gap and weak assumption in a plan before a client, stakeholder, or reality does |

### Standalone

| Skill | What it governs |
|---|---|
| [jp-frontend-design](skills/jp-frontend-design/) | The ORDER of frontend design work: brief → tokens → hero screen → screenshot-critique loop → scale out. A process skill, built to run beside a craft-level design skill |
| [opus-orchestration](skills/opus-orchestration/) | Large multi-deliverable builds as workflow-orchestrated Opus fleets: the premium main thread plans, gates, and reviews; Opus agents research, draft, adversarially verify, and fix |
| [agentmail-onboard](skills/agentmail-onboard/) | Onboarding a new email + Telegram agent against an agentmail control plane, one runbook step at a time, with every outbound send behind a human approval tap |
| [vinyl-dig](skills/vinyl-dig/) | A parallel record-shop crawl: one subagent per shop, prices benchmarked against Discogs, deduped against your collection, and a tiered buy list at the end |

## Acknowledgements

- The quality floor, self-simulation slop test, and copy guidance in
  `jp-frontend-design` adapt ideas from Anthropic's
  [`frontend-design`](https://github.com/anthropics/claude-plugins) skill
  (Apache 2.0).
- `clodex` and its stage skills descend from the
  [TRIP workflow](https://github.com/PiLastDigit/TRIP-workflow) by PiLastDigit
  (MIT) — the stage vocabulary and the Codex review roles originate there.
- The three rigor skills — `dialectical-review`, `empirical-falsification`,
  and `red-team-pressure-test` — took shape with help from my friend Lisa
  Larbi, whose thinking runs through all three.

## License

MIT — see [LICENSE](LICENSE).
