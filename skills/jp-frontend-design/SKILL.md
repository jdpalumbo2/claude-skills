---
name: jp-frontend-design
description: Use when building or restyling any user-facing UI — web apps, dashboards, media libraries, client deliverables, prototypes, artifacts — before writing the first component or stylesheet. Also use when an existing UI feels generic, templated, or AI-generated and needs a design pass.
---

# JP Frontend Design

## Overview

Unconstrained generation regresses to the statistical mean of every UI ever made —
templated, forgettable, instantly recognizable as AI output. Constraints get set
BEFORE code. Design is a sequence of deliberate, subject-grounded choices, and this
skill is the sequence.

**Companions (load if available):** a craft-level design skill (e.g. Anthropic's
`frontend-design`) alongside this one; a dataviz skill before any chart. This skill
governs the ORDER of work.

## The sequence (do these in order — no component code before step 2 exists)

1. **Brief.** Propose 3 distinct visual directions: each gets a name, 3 mood words,
   a typography pairing, a color story, and one thing it deliberately avoids.
   Slop-test each: would a generic version of this prompt produce the same
   direction? If yes, replace it. The user picks or remixes. Working autonomously? Pick the direction most
   grounded in the subject's own world and say so — never the safest.
2. **Tokens file.** One `tokens.css` / theme config before any component: semantic
   color names, type scale, spacing scale, radii, shadows. Every component consumes
   only tokens. This file is where taste lives — tweaks happen here, not in
   components, and a hand-edit to 30 lines of variables restyles the whole app.
3. **References (when given).** Screenshots get analyzed first — "what creates the
   hierarchy, density, spacing rhythm, type character" — then the findings go into
   the tokens. Analyze-then-build, never clone.
4. **One hero screen to full polish.** Not a scaffold of every page. One screen,
   finished, embodying the brief's signature element.
5. **Screenshot critique loop — minimum 2 rounds.** Render it, screenshot at
   desktop AND mobile widths (browser MCP / Playwright / DevTools), then critique
   both images as a senior product designer: 10 specific problems across
   hierarchy, spacing, typography, color; fix; re-shoot. Quality floor each
   round: responsive at mobile width, visible keyboard focus,
   prefers-reduced-motion respected. Models critique rendered output far better
   than they design blind — the loop is where quality actually happens.
6. **Scale out.** Only after the hero passes: "extend this system" to remaining
   screens. Coherence comes from the tokens + finished exemplar.

## Ground the direction in the subject

The subject's own world — its materials, artifacts, and vernacular — is where
distinctive choices come from. Category priors that consistently beat defaults:

- **Media/collection libraries** (music, film, books, games): the owned artwork IS
  the interface — covers, sleeves, posters carry the design; chrome recedes; type
  and texture borrow from the medium's physical history.
- **Data-dense analytics** (sports, finance, ops): broadcast-graphics energy —
  typography and alignment create the hierarchy, not card chrome; tabular numerals;
  density is a feature, not a bug.
- **Client/brand work**: derive the tokens from the client's existing brand first;
  add exactly one signature element per surface; never ship a default theme.

## Slop tells (the critique checklist — flag any of these in step 5)

Inter/system font everywhere · purple/indigo gradient · three-card hero grid ·
untouched component-library defaults · emoji as UI icons · uniform rounded-shadow
cards · big-number-small-label hero · cream + serif + terracotta "tasteful" default ·
near-black + single acid accent default · broadsheet hairlines/zero-radius default ·
centered-everything · copy that sells instead of explains

Copy is design material: name things by what the user controls, active voice,
buttons say what happens.

## Common mistakes

- Scaffolding ten screens at once → ten mediocre screens. One polished, then extend.
- Skipping the critique loop because it "looks done" — blind output always reads
  templated; the loop is cheap and mandatory.
- Fixing components when the problem is a token. Change the variable, let it cascade.
- Waiting for the user to supply taste. Propose directions with conviction; they veto.
- Project-specific identity notes belong in the project's own docs (CLAUDE.md /
  architecture memory), not in this skill — this skill supplies the process.
