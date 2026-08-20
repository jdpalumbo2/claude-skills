# empirical-falsification

**What it is.** Forces a claim through a real WebSearch pass — not recalled training-data memory of what a source probably says — and reports a verdict: holds, falsified, or partially true with the caveat spelled out. Follows citation chains to a primary source or two consecutive dead ends, and says which one it hit.

**What it's good for.** The stat that's about to get repeated in a deck or strategy document and has never actually been checked. The failure mode this exists to kill is specific: an LLM confidently restating a plausible-sounding number with more confidence, not less, the more times it's been repeated — which is exactly backwards from what should happen to an unverified claim.

**Who it's for.** Anyone building on a claim that could get challenged in the room, where "I was pretty sure that was right" isn't a good enough answer after the fact. Pairs with `dialectical-review` when what's shaky is a position instead of a fact, and composes underneath `red-team-pressure-test` — an adversarial pass is only as good as the facts it's arguing over.
