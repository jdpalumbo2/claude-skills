# vinyl-dig

## What it is

Turns "go see what's in stock at my local shops" into a parallel, read-only
crawl with a scored, deduped buy list at the end — never a hallucinated
listing. One subagent per shop, dispatched concurrently, each returning
structured candidates; a synthesis pass benchmarks prices against Discogs,
dedupes against what you already own, and tiers the result.

It originated as a Chicago-specific command in my `shelf` music repo and was
promoted here with the portable part — the crawl mechanics and scoring rubric
— separated from the personal part, which stays in the calling project.

## How it works

1. The shop directive and catalog access map are read first, and the proposed
   crawl (shops, endpoints, filters, subagent layout) is presented for
   approval before anything runs — a stale shop list gets caught before it
   burns a full crawl.
2. One subagent per shop crawls in parallel, read-only, each returning
   candidates with artist, title, pressing, condition, price, and the actual
   listing URL. **Every candidate needs a URL fetched this session** — a shop
   whose catalog is broken or blocked is a reported gap, never a silently
   empty result.
3. Synthesis dedupes against the collection ledger and previously-passed
   records, flags wantlist matches, scores fit, and benchmarks each price
   against Discogs marketplace stats (landed cost, not item price — Discogs
   numbers usually exclude shipping) into steal / fair / toppy tiers.
4. The output is a tiered buy list — "best cart under $X" if the project sets
   a budget ceiling, otherwise ranked by desire band.

## What the calling project must provide

The skill has no data of its own. It reads five project-local files: a shop
directive (shops, tiers, standing dig rules), a catalog access map (working
URLs/endpoints per shop, known gotchas), a collection ledger, a wantlist, and
a taste/verdict store. Missing any of them, it says so and stops — a buy list
that recommends a record you own or already passed on is worse than no buy
list.

## Who it's for

Record collectors who dig with an agent. Built for my Chicago shop list;
portable to any city — the mechanics travel, the taste data doesn't.

## Install

```bash
ln -s "$(pwd)/skills/vinyl-dig" ~/.claude/skills/vinyl-dig
```
