# jp-frontend-design

## What it is

A **process skill**, not a craft skill. It doesn't teach taste — it enforces the
order in which taste gets applied: constraints before code, tokens before
components, one hero screen before ten scaffolds, screenshots before "done."
It's designed to run alongside a craft-level design skill (like Anthropic's
`frontend-design`) and a dataviz skill; this one governs the sequence, they
govern the judgment.

## What it's good for

- **Tokens-first styling.** Every component consumes a `tokens.css` written
  before any component exists — so restyling the whole app is a hand-edit to
  30 lines of variables, not a hunt through components.
- **Hero-first discipline.** One screen polished to done before anything else
  is scaffolded. Ten screens at once means ten mediocre screens.
- **The screenshot critique loop.** Models critique rendered output far better
  than they design blind. The skill makes the loop mandatory — minimum two
  rounds, desktop and mobile widths, with an accessibility quality floor — which
  is where the actual quality happens.

Reach for it when any user-facing UI is about to be built, or when an existing
one reads as generic, templated, or AI-generated.

## Who it's for

Builders who make tools for themselves — people customizing their own agents
who want a repeatable design process, not a component library or a theme.
It was made for me, for people like me, by people like me.

Honest caveats: it's opinionated (that's the point); the critique loop assumes
a screenshot capability (browser MCP, Playwright, or Chrome DevTools); and
project-specific identity belongs in the project's own docs — this skill only
supplies the process.

## Install

```bash
ln -s "$(pwd)/skills/jp-frontend-design" ~/.claude/skills/jp-frontend-design
```
