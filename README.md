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

One row per skill; each skill's own README covers what it is, what it's good
for, and who it's for.

## Acknowledgements

The quality floor, self-simulation slop test, and copy guidance in
`jp-frontend-design` adapt ideas from Anthropic's
[`frontend-design`](https://github.com/anthropics/claude-plugins) skill
(Apache 2.0).

## License

MIT — see [LICENSE](LICENSE).
