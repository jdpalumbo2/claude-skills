---
name: vinyl-dig
description: Use when asked to run a vinyl-shop dig — crawl a set of local record shops' online catalogs in parallel, benchmark prices against Discogs, and produce a tiered buy list. Originated for Johnny's Chicago digs; portable to any city/shop-list as long as the calling project provides the companion files below.
---

# Vinyl Dig

## Overview

Turns "go see what's in stock at my local shops" into a parallel, read-only crawl with
a scored, deduped buy list at the end — never a hallucinated listing. One subagent per
shop, dispatched concurrently, each returning structured candidates; a synthesis pass
benchmarks against Discogs and tiers the result.

**Originated in Johnny's `shelf` repo** (`music/.claude/commands/vinyl-dig.md` +
`music/.claude/agents/shop-crawler.md`, Chicago shop list). Promoted here 2026-08-21 so
it isn't locked to one repo. The crawl mechanics and scoring rubric below are the
portable part; the shop list, seed artists, and collection data are not — they live in
the calling project and get named at invocation time.

## What the calling project must provide

This skill reads project-local files; it has no data of its own. Before running it,
confirm the project has:

- **A shop directive** — one file (name it anything, e.g. `chicago-shops.md`) listing
  shops, neighborhoods, tiers, and standing dig rules (formats/condition/budget
  discipline). Johnny's version also carries a "route clusters" section for planning a
  physical trip, which is optional.
- **A catalog access map** — working URLs/API endpoints per shop (Shopify
  `/products.json`, a storefront's own catalog JSON, Discogs seller storefronts) plus
  known gotchas (403s, stale info-only catalogs). Crawling blind against a shop site
  that blocks scrapers wastes the round.
- **A collection ledger** (`collection.csv` or equivalent) — to dedupe against what's
  already owned.
- **A wantlist** (`wantlist.csv` or equivalent) — to flag high-conviction matches.
- **A taste/verdict store** (`taste-db.csv` or equivalent) — to never re-pitch a
  `passed` record, and to score fit for the rest.

If any of these don't exist yet, say so and stop rather than crawling without a dedupe
or scoring basis — a buy list that recommends an owned or already-passed record is
worse than no buy list.

## Running the dig

1. **Read the shop directive and the catalog access map first.** Confirm the shop list
   and per-shop crawl method (native catalog vs. Discogs storefront) are current — a
   shop's site changes shape often enough that a stale access map produces zero
   candidates silently.
2. **Stay in plan mode and propose the crawl before running it**: which shops, which
   URLs/endpoints per shop, genre/label filters, subagent layout. Wait for approval.
   This catches a stale or wrong shop list before burning a full crawl on it.
3. **Dispatch one subagent per shop, in parallel**, each read-only (never writes
   files), each returning: artist, title, label/cat#, format, year/pressing, price,
   media + sleeve condition, listing URL, and which taste target it fills. Each
   subagent's prompt should carry: the shop's catalog/storefront URL, the hard filters
   (format rules, condition floor, "already owned" check against the collection
   ledger), and the benchmark instruction (price vs. Discogs stats → steal/fair/toppy).
4. **Never fabricate a listing.** Every candidate needs a URL actually fetched this
   session. A shop with a broken or blocked catalog is a reported gap, not a silently
   empty result folded into "nothing found."
5. **Synthesize**: dedupe against the collection ledger and taste-db `passed` rows,
   flag wantlist matches, score confidence/fit (see rubric below — adapt to whatever
   scoring the project's own taste-db uses if it differs), and build a tiered buy list
   ("best cart under $X" if the project sets a budget ceiling, otherwise ranked by
   desire band).
6. **Write the report** to a file the calling project expects (Johnny's convention:
   `vinyl-recommendations.md`), or ask where it should land if unclear.

## Scoring rubric (starting point — adapt to the project's own if it differs)

- **Fit/confidence 0–100**: 90+ dead-center (spine adjacency, priority label, on the
  wantlist); scale down for genre-adjacent or unfamiliar-artist candidates.
- **Price tier**: steal / fair / toppy, benchmarked against Discogs marketplace stats —
  remember Discogs prices typically exclude $6–15 shipping, so compare landed cost, not
  item price.
- **Desire band** (if the project has one, e.g. Johnny's AUTO-BUY/HUNTING/OPPORTUNISTIC):
  rank by the project's own band above raw fit score — a record he's actively hunting
  beats a higher-fit record he hasn't expressed desire for yet.

## Common mistakes

| Mistake | Instead |
|---|---|
| Crawling before confirming the shop/access-map files are current | Read them first; a stale catalog URL returns zero silently, which reads as "nothing in stock" rather than "the crawl broke" |
| Skipping the plan-mode proposal step | Propose shops/URLs/filters and wait for approval — catches a wrong or outdated shop list cheaply |
| A subagent inventing a listing it didn't actually fetch | Never fabricate — a reported gap ("shop's catalog 403'd") beats an invented candidate |
| Recommending something already in the collection ledger or a `passed` taste-db row | Dedupe against both before the buy list is built, not after |
| One subagent crawling all shops sequentially | One subagent per shop, dispatched in parallel — that's the whole point of the fan-out |
