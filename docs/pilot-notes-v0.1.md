# clodex v0.1 — pilot notes

First end-to-end operator run of the clodex skill set, 2026-08-11.

**Target:** a polyglot personal repo — a JS site at the root, a Python data
pipeline in a subdirectory, deployed by a host that builds automatically on
push to the default branch.

**Feature:** hardening an ingest script that regenerates a generated CSV from a
vendor export — add a price-coverage report, condition capture, and
duplicate-pressing detection. A real unchecked backlog item with its own
Done-when.

**Run id:** `r-2026-08-11-a`
**Terminal state:** **stage `plan`, release `not-started`, 3 findings open, 0
approvals.** The run did not reach build, verify, or ship.

---

## Headline result

The core path was **not** completed, and the reason is the finding, not an
accident. Plan review ran **five rounds** and never converged. It produced **26
findings**; I verified essentially all of them directly against the repo and
**every one was true**. Twenty-three were fixed across four plan amendments. The
fifth round — after a full re-scope — still returned a high and two mediums that
were also true.

The three exits the skill offers at the convergence cap were each tried or ruled
out:

| Exit | Outcome |
|---|---|
| Keep iterating | Taken once (round 4). Returned **three new highs** — severity went *up*. |
| Re-scope and restart | Taken (plan v5). The restarted round still returned a high. |
| Accept the open findings | **Not available.** The skill reserves `accepted`/`rejected` for the user, explicitly. An autonomous operator cannot take it. |

So the run parked, honestly, on a human gate. That is a legitimate terminal
state for an autonomous pilot and the manifest says so plainly. It is also the
single most important thing this pilot learned, and it is a *design* finding,
not a bug: **convergence as v0.1 defines it may be unreachable for a plan of any
real density, because a sufficiently thorough reviewer keeps finding true
things.**

### Why the loop did not converge

Rounds 1–2 found problems with the plan's *approach* — genuinely wrong choices
that got fixed and stayed fixed. Rounds 3–5 found problems with the plan's
*claims about data*: an expected count that was off by one, an assumption of
uniqueness that a real data file contradicted, a vocabulary list that missed
real spellings.

That is the mechanism. Every time the plan got more specific to satisfy a
reviewer, it made new falsifiable assertions, and each assertion was a fresh
surface to be wrong on. Specificity was *generating* findings, not exhausting
them.

The v5 re-scope was an attempt to break that: state behaviour as numbered
invariants, delete every prediction about the data, and replace the hand-written
vocabulary table with a test that asserts a property over the repo's own real
corpus. That was the right move — it retired an entire class of finding — and it
still was not enough, because the reviewer then correctly attacked the
invariants themselves.

**Recommendation.** Convergence should not be defined solely as "a round
returned nothing new." Two changes would have let this run finish honestly:

1. **Let the operator record a `deferred-to-build` disposition** for findings
   that are true but are implementation detail rather than plan defects. Two of
   round 5's three were exactly that. Today the only non-user disposition is
   `fixed`, which forces an amendment, which re-opens the loop — a genuine
   ratchet with no exit.
2. **Make the cap's exits reachable without a human**, or state clearly that
   clodex has no autonomous mode. Right now the cap hands you three doors and
   locks two of them the moment there is no user in the room.

---

## Success criteria — answered from the manifest and events alone

Per criterion 2, each answer below was derived by reading only
`rebuild` output and `events.ndjson`. Where I had to fall back on my own session
memory or on files outside the run state, that is called out — **those fallbacks
are themselves criterion-2 failures.**

| # | Criterion | Verdict | Evidence, and how it was obtained |
|---|---|---|---|
| 1 | Manifest present and honest at every stage | **PASS, for the stages reached** | The manifest reports `stage: plan`, `plan: v5 (4 amendments)`, `findings: 26 (3 open)`, `approvals: []`, `release: not-started`, `batches: []`, `verification: 0 declared`. Every one of those is true, including the unflattering ones. Nothing had to be corrected to make it honest, and at no point did it claim a stage or an approval that had not happened. Build/verify/ship were never entered, so their honesty is untested. |
| 2 | Zero transcript reconstruction needed to answer "what happened" | **FAIL** | Answerable: lane, brief, start commit, the 730-path dirty snapshot, plan path/version/hash, all 26 findings with severity, source and disposition, all four amendments with their `required_review`, and full disposition reasoning in the event `note` fields. **Not answerable:** how many review rounds ran (recoverable only because I hand-encoded `r<N>-` into finding ids — the schema has no concept of a round); which envelope or Codex invocation produced any finding; which plan version a finding was raised against; that a round was interrupted and resumed; any cost or duration. Also **not answerable: whether preflight ran or passed** — the router states outright that preflight results are reported in chat and not logged, so the single question "was this environment ever verified?" is answerable only from a transcript. |
| 3 | Release closed with verified live state or an explicit boundary | **NOT REACHED** | `release: not-started`. The run never got to ship, so the `not-deployed` boundary machinery this pilot was meant to exercise went untested. |
| 4 | Fewer human gates than the TRIP baseline | **NOT ASSESSABLE, with a caveat** | Gates *spent*: zero — plan review, disposition of 23 findings, and four amendments all proceeded without one, where the incumbent workflow asks a question per release step. But the run is now **parked on** a gate it cannot pass alone, and the cap decision (which exit to take) is itself an unmodelled gate the manifest does not represent. Fewer gates on the happy path; one unbounded gate on the unhappy one. |
| 5 | No runner incident traceable to cwd, prompt transport, or lost state | **PASS on all three named causes; one incident from a fourth** | Five invocations, zero cwd problems, zero prompt-transport problems (prompts go by file and stdin throughout — writing every event and prompt to a file rather than interpolating shell strings is the reason nothing broke on the em-dashes and quotes these documents are full of), and zero lost run state. One incident did occur: round 2 was killed at exactly 600 s by the **harness's** maximum tool timeout, not by anything in the runner. The runner handled it correctly — wrote an `interrupted` envelope, preserved the session id, and resumed cleanly in 34 s. |

**Criterion 2 is the one to act on.** The gap is narrow and mechanical: the event
vocabulary has no way to say "a review round happened, here is its envelope, and
here is the artifact hash it examined." Everything else about the run is
beautifully recoverable.

---

## The three deferred questions

### 1. Is the 3-round plan-review convergence cap right?

**The cap fires at the right moment. Its advice is wrong.**

Right, because round 3 is genuinely where the signal changed: rounds 1–2 fixed
the approach, and from round 3 on the reviewer was mining detail. Stopping to
take stock there was correct.

Wrong, because the skill says "a fourth round is not the answer" and that a
reviewer still surfacing blockers is telling you the scope is wrong. Neither held
here. Round 4 surfaced three highs that were all true and all cheap — including
one that would have shipped silent data corruption. Round 4 was *valuable*. The
scope was not wrong; the plan was simply making more claims than it could keep.

Findings per round fell steadily — 8, 6, 5, 4, 3 — but **severity did not**:

| Round | blocker | high | medium | low | info |
|---|---|---|---|---|---|
| 1 | 0 | 3 | 5 | 0 | 0 |
| 2 | 0 | 0 | 4 | 1 | 1 |
| 3 | 0 | 0 | 3 | 2 | 0 |
| 4 | 0 | 3 | 1 | 0 | 0 |
| 5 (post re-scope) | 0 | 1 | 2 | 0 | 0 |

A cap keyed to round *count* cannot see that. Keep the checkpoint at 3, but make
it report the severity trend and require the operator to name which mechanism
they are seeing — approach defects (keep going), detail mining (deferrable), or
scope error (re-scope). And add the `deferred-to-build` disposition, without
which "keep iterating" is the only door an autonomous operator can open.

### 2. What does Codex review actually cost?

Plan review only — the run never reached code review, so that half is unmeasured.

- **5 rounds, 39.4 minutes of real wall clock.** Per round: 366 s, 634 s
  (600 s killed + 34 s resume), 358 s, 501 s, 505 s.
- **Envelopes under-report this by 25%.** They sum to 29.4 min, because a resume
  overwrites the interrupted envelope and the replacement records only the
  resume leg — 34 s in place of 634 s. Cost accounting from envelopes alone is
  not trustworthy.
- **Findings per round: 8, 6, 5, 4, 3.** Yield stayed useful to the very last
  round; there was no point at which a round stopped paying.
- Reviewer ran at `xhigh` effort in a read-only sandbox. It opened source files,
  cross-referenced a friend-data CSV, counted rows, and caught a duplicate id in
  a 290-row file. The quality genuinely justified the time.

Roughly **6–8 minutes per round** on a ~250-line plan. Budget ~30 minutes of
wall clock for plan review on a feature of this size, and note that this is
already the *cheap* half — the design puts code review on nearly every non-doc
batch, which this run never reached.

### 3. Is envelope-on-disk vs manifest-event felt in practice?

**Yes, immediately and repeatedly. This is the sharpest concrete defect found.**

- Envelopes land in `<repo>/.clodex/runner/<role>/<invocation-id>.*` — **outside
  the run directory and not keyed to the run.** Nothing links an envelope to the
  run that produced it. A second run in the same repo drops its envelopes in the
  same folder, interleaved.
- The manifest contains no `envelope`, `invocation`, or `round` field at all. I
  could answer "was this reviewed, and against which version?" only because I
  invented an `r<N>-F0NN` id convention and wrote the reasoning into event
  `note` fields by hand. Another operator using a different convention would
  leave a run from which that is unrecoverable.
- The envelope *does* carry the input hash, so envelope↔plan-version matching is
  possible — but only by manually hashing files and grepping a directory the
  manifest never mentions.
- **Resume destroys evidence.** After resuming, the envelope reads `complete`
  with a 34 s duration. That a round was interrupted, and that 600 s were spent,
  survives only in `codex.resumed: true`.

`rebuild` alone genuinely cannot answer "was this reviewed, and against which
version?" A single `review:completed` event carrying role, envelope path, input
hash and duration would close all four gaps at once, and is the highest-value
change this pilot can recommend.

---

## Friction incidents

Every incident, including the ones worked around.

**1. Preflight's gitignore remedy collides with the change boundary.** The
router's fix for un-ignored run state is "add these lines to `.gitignore`" — but
in this repo that file already carried another session's uncommitted edit.
Committing it would have swept their work into a clodex commit, which §5
forbids without qualification. Worked around with a nested ignore file inside
the run-state directory (`*`, `!.gitignore`, `!profile.json`), which satisfies
both probes and touches nothing the other session owns. The skill offers no
guidance for this case and its literal instruction is unsafe here. **Fix:**
prefer the nested ignore file as the default remedy — it is self-contained and
cannot conflict.

**2. `-uall` expanded a 19-path dirty set to 730.** §5A rightly mandates
`--untracked-files=all`, and the failure it prevents is real. But a generated
asset directory expanded to 711 entries, so `dirty_at_start` is a 730-element
array and the accompanying instruction to "show the user every dirty path"
became unusable. **Fix:** keep the rule, and add presentation guidance — group
by directory for display while recording files.

**3. A review round can outlive the maximum tool timeout.** Round 2 was killed
at exactly 600 000 ms. Every later round had to be launched detached to survive.
Nothing in the skill warns that a single review can exceed a harness limit.

**4. The resume line is printed to the stderr that the kill destroys.** The
skill says to surface the runner's one-command resume line — but it goes to
stderr, which is precisely what is lost when the invocation is killed. Had to
reconstruct `--resume <invocation-id>` from `--help`. **Fix:** write the resume
command into the envelope, where it survives.

**5. Resume overwrote the interrupted envelope** (see deferred question 3).

**6. Envelopes are not keyed to the run** (see deferred question 3).

**7. Preflight results are deliberately not events**, so "was this environment
verified?" is unanswerable from run state. This directly costs criterion 2.

**8. One `commands.test` slot for a polyglot repo.** Two suites with different
runners had to be composed with `&&`, so a failure cannot be attributed to a
lane without re-running.

**9. The profile's own branch rule is committed to the branch it forbids.** The
profile records `work_on_default: false`, and the router's profile commit
necessarily lands on the default branch — the rule does not exist until the
commit that creates it. Harmless, but it reads as a contradiction.

**10. A genuinely decision-bearing question had no one to ask.** Whether the
ingest may read a second data file is a scope decision the skill says to put to
the user. Resolved by the operator under standing authorization — **and the
reviewer then proved the answer wrong** in round 1, citing an existing module
that already does exactly that. A worked example of why that gate exists.

**11. Only `fixed` is available to an autonomous operator**, and it forces an
amendment, which re-opens the review loop. This is the ratchet described above
and the direct cause of the run parking.

**12. The convergence rule and the materiality rule interact badly.** Any
material amendment requires a fresh round; every fix to a substantive finding is
material; every round finds something substantive. There is no configuration of
these two rules that terminates while the reviewer keeps finding true things.

**13. Round-number bookkeeping is entirely manual.** Finding ids must be
hand-namespaced `r<N>-` or the reducer rejects the collision — correct, but it
means the only record of which round a finding came from is a string convention
the operator has to remember.

---

## What went right

Worth recording, because it is most of the system.

- **The change boundary held perfectly.** 730 dirty paths belonging to another
  session, across 60+ minutes and 6 commits' worth of temptation — nothing of
  theirs was staged, moved, or committed. The pathspec discipline
  (`git commit -- <paths>`) and the ban on `git add -A` are the reason.
- **The engine refused everything it should.** Approvals bind to the current
  plan hash; a second `plan:recorded` is refused; duplicate finding ids are
  refused. No invariant had to be enforced by care.
- **Events-as-source-of-truth works.** `rebuild` was correct after every append,
  including a 730-element array and 56 events.
- **File-based prompt and event transport is the right call.** These documents
  are full of em-dashes, quotes and `$`; not one shell-quoting incident occurred
  in the entire run.
- **The runner failed safely** under an external kill: correct status, preserved
  session, clean resume.
- **Review quality was outstanding.** 26 findings, all true, several of which
  would have shipped real defects — silent metadata blanking, valid data
  reported as unrecognised, and a folder-policy error that would have
  misclassified every freshly imported record.

---

## Coverage gap

This pilot exercised the router and `clodex-plan` thoroughly and `clodex-build`,
`clodex-verify` and `clodex-ship` **not at all**. The `not-deployed` boundary,
the release authorization, the `skipped:` reason grammar, and the
`verify-live`-cannot-be-cut refusal all remain untested. A second pilot should
start from a plan that is already approved, so those stages get the same
scrutiny plan review just received.
