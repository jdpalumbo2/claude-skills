# Clodex — design spec (v0.1)

Clodex is a personal development workflow for Claude Code + Codex CLI: a small
skill set behind one routed front door. It replaces the author's use of the
TRIP workflow (upstream: PiLastDigit/TRIP-workflow, MIT), redesigned around a
private 53-thread study of how that workflow actually got used — what ran, what
never ran, where the friction was, and what was missing.

Status: spec for v0.1 — the core path only. Reviewed by Codex plan review
before implementation.

## Design principles (each traces to a study finding)

1. **Noticing-first.** The user never memorizes stage names. One front door
   (`clodex`) reads repo state and the ask, proposes the lane, and resumes
   interrupted runs. Five of ten TRIP stages were never invoked in 53 threads —
   capability behind a name you must remember is capability that rots.
2. **Dense briefs enter directly.** 28/34 studied threads arrived with the
   "what" already specified. Planning asks only blocking or decision-bearing
   questions; ideation ceremony is conditional, not default.
3. **Ship is a state machine, not a stage.** "Tagged" ≠ "pushed" ≠ "deployed" ≠
   "verified live." Release bookkeeping is an automatic transition with one
   authoritative timestamp; the run is not closed until live state is verified
   or an explicit `not-deployed` boundary is recorded.
4. **Evidence classes are declared at plan time.** Offline-green suites missed
   operational defects repeatedly. Each plan declares what proof done requires
   (tests / real data / live check / visual), and deferred evidence is recorded
   as verification debt, never prose.
5. **Durable state, structured events.** Every run has a manifest file.
   Stage transitions are recorded as events, never reconstructed from
   transcript strings. Cross-session and orchestrator/worker handoffs read the
   manifest, not pasted summaries.
6. **Gates attach to decision risk, not stage boundaries.** Human approval is
   reserved for: destructive/irreversible actions, taste and product direction,
   scope changes, unresolved review findings, external publication. Routine
   "proceed?" ceremony is consolidated — one measured session spent 88 minutes
   at gates against 24 minutes of compute.
7. **Independent review by default, instrumented.** Codex plan review changed
   nearly every plan it touched in the study; it stays default-on. Code review
   stays default for consequential diffs, with cost/finding data collected
   before any sampling policy is adopted.

## Architecture

```
skills/
  clodex/            router + shared infrastructure (runner, schemas)
  clodex-plan/
  clodex-build/
  clodex-verify/
  clodex-ship/
```

Engine installs globally (symlinked from this repo, like every catalogue
skill). Each repository gets only a **profile** — no per-repo skill forks,
which the study showed drift into hybrid-version repair work.

### The router (`clodex`)

Entry point for all work. On invocation it:

1. Loads (or on first use, generates) the repo profile; runs **preflight** —
   repo root, git remote state, runtimes, Codex auth, required credentials —
   before any stage starts (14+ studied incidents came from skipped preflight).
2. Checks `.clodex/` for an open run → offers resume with current stage and
   pending decisions.
3. Otherwise classifies the ask: feature-shaped → core path; audit / repair /
   chore / sync-shaped → **names the shape, says the lane is not built yet
   (v0.2), and proposes the closest manual approach**. Noticing ships in v0.1
   even where lanes don't.

### Core path

`plan → build → verify → ship`, with discovery conditional inside plan.

| Skill | Charter | Exit contract |
|---|---|---|
| `clodex-plan` | Ground in the repo, accept a dense brief, ask only decision-bearing questions. If the work is taste-shaped (design, content, positioning), run the **direction checkpoint** first: approved premise/comp before bulk implementation. Produce a versioned plan with declared evidence classes; submit to Codex plan review; iterate to convergence. | Approved plan vN in manifest; review findings resolved or explicitly accepted by the user. |
| `clodex-build` | Execute in small batches. Each Codex batch runs under an explicit **batch contract** (owned paths, forbidden paths, test expectations). Every delta is locally reviewed before the next batch. Assumption changed mid-flight → record a **plan amendment** (what changed, which completed work is affected, what re-review it triggers) — never silently drift. | All plan items done or amended; batch log in manifest. |
| `clodex-verify` | Run the profile's gates plus the plan's declared evidence classes. Real-data and live checks run before tagging when feasible; anything deferred becomes explicit **verification debt** carried in the manifest and surfaced at ship. May delegate a tests-only worker with findings schema. Verify records and surfaces debt; it does NOT gate on it — acceptance happens exactly once, inside release authorization. | Evidence recorded per class; debt list (possibly empty) in manifest. |
| `clodex-ship` | Final review against the approved plan (approvals are bound to plan version + hash, so amendments revoke them mechanically), then one consolidated **release authorization** that enumerates the exact external actions to be taken (commands, targets, tag name, deploy target) plus any verification debt being accepted — the single binding debt gate. Then stepwise transitions, each persisted before and reconciled after: close docs/changelog/version from evidence with one timestamp → commit (run-owned paths only) → tag → push (remote verified first) → deploy → verify-live. Any runtime action outside the authorized set stops the run. | Release state terminal (`verified-live`, `not-deployed`, `abandoned`, or — v0.2, when the profile declares `release_owner: "external"` — `handed-off`, the orchestrated-lane ending: a reviewed branch plus a recorded handoff artifact, release machinery owned outside the run) or explicitly resumable (`deploy-failed`, `push-failed`); run closed or checkpointed. |

### Run state (`.clodex/`, gitignored by default)

*(Amended 2026-08-16, v0.2: gitignored is not the same as durable. A run that
lives in a worktree is archived on close — its run dir plus the envelopes its
manifest names are copied to `<main-checkout>/.clodex/archive/<run-id>/`,
still ignored and never committed, so the release record's pointers outlive
`git worktree remove`. Selection is manifest-driven via `invocations[]`; raw
runner transcripts are deliberately left behind.)*

Two files per run, with distinct write disciplines:

- **`run-<id>.json`** — the snapshot. Written only via lock + atomic replace
  (write temp, validate against schema, rename); carries `schema_version`; one
  active writer enforced by a lockfile carrying the writer's PID/session. A
  second invocation finding a live lock must offer resume-or-abort, never
  write.
- **`run-<id>.events.ndjson`** — append-only event log, one JSON object per
  line. **Events are authoritative**; the snapshot is a derived convenience
  and is rebuilt from events on any validation failure. Event contract: every
  event carries `schema_version`, a monotonic `seq`, and a timestamp; writes
  append-and-fsync **before** any dependent snapshot replacement or external
  action; on recovery, a torn final line (invalid JSON) is truncated and
  logged, never guessed at. The snapshot is defined as a deterministic
  reduction over the event sequence — the reducer and its invariants (stage
  monotonicity, one open release step at a time, approvals reference existing
  plan hashes) ship with the schema, so any conforming implementation rebuilds
  identical state.

```json
{
  "schema_version": 1,
  "run": "r-2026-08-10-a", "parent": null,
  "repo": "<abs path>", "branch": "main",
  "git": {"start_head": "<sha>", "dirty_at_start": ["<paths acknowledged by user>"]},
  "brief": "<the ask, verbatim>",
  "lane": "feature",
  "plan": {"version": 3, "path": "docs/plans/...", "hash": "<sha256>", "amendments": []},
  "stage": "build",
  "batches": [{"id": 1, "owned_paths": ["src/x/"], "commit": "<sha|null>",
                "delta_review": "pass"}],
  "findings": [{"id": "F1", "source": "plan-review", "disposition": "fixed|accepted|rejected"}],
  "verification": {"declared": [], "evidence": [], "debt": []},
  "release": {"state": "in-progress",
               "steps": [{"step": "push", "op_id": "<idempotency key>",
                           "status": "done|failed|pending", "reconciled": true}],
               "timestamp": null, "tag": null, "deployed": null, "verified_live": null},
  "approvals": [{"t": "<iso>", "scope": "release-authorization", "by": "user",
                  "plan_version": 3, "plan_hash": "<sha256>",
                  "actions": [{"id": "push-main", "argv": ["git", "push", "origin", "main"],
                                "cwd": "<repo root>", "target": "origin/main",
                                "env_refs": []}],
                  "accepted_debt": []}]
}
```

Rules an implementer must honor:

- **Change boundary.** Preflight records `start_head` and the dirty-file
  snapshot; the user acknowledges pre-existing dirt or the run aborts. Ship
  stages only paths owned by the run's batches — unrelated work in the tree is
  never swept into a clodex commit. If a dirty file overlaps a planned owned
  path, the run must resolve the overlap before build: capture the
  pre-existing diff into `.clodex/` and fold it into scope with explicit user
  acknowledgment, isolate the run in a clean worktree, or abort. Path-level
  ownership is never allowed to blur file-level provenance.
- **External side effects are two-phase.** Every release step writes a
  pending event with an operation ID before acting and a done/failed event
  after. On resume, a pending step is **reconciled against reality** (does the
  tag exist? did the remote advance? is the deploy live?) before any retry —
  no blind replay of pushes or deploys.
- **Approvals bind to hashes.** A review or approval references the plan
  version + content hash (and diff SHA for code review). An amendment
  supersedes the plan hash, which mechanically revokes **every** review and
  approval bound to the superseded hash — the original plan approval included,
  not just ship-stage approvals. Each amendment declares its required
  re-review scope, and ship is blocked until that re-review exists against the
  new hash. Revocations are events.

### Repo profile (`.clodex/profile.json`, committed)

Build/test/lint commands, version source, branch and tag rules, changelog
path, architecture doc paths, deploy target + verify-live checks, evidence
expectations by default, and a **structured action policy**: the exact
release/deploy actions clodex may propose in this repo, each marked
`auto-with-authorization` or `always-ask-exact` (repos with their own guardrail
tiers — e.g. an infra control plane — mark red-tier actions `always-ask-exact`,
and clodex presents the literal command for approval every time). Free-form
notes are allowed but never drive execution. Generated by the router on first
run from repo inspection + a short interview; updated non-destructively.

### Codex roles and the runner

All four Codex arms survive as **roles invoked inside stages**, never as
stages the user calls:

| Role | Used by | Contract |
|---|---|---|
| plan-reviewer | clodex-plan | default-on; structured findings; convergence or explicit user acceptance of open findings |
| implementer | clodex-build | batch contract; no release-owned files; orchestrator owns delta review |
| code-reviewer | clodex-ship (and clodex-build micro-gates) | default for consequential diffs; findings + cost instrumented |
| advisor | any stage on escalation | must produce a preserved decision artifact |

One shared **runner** (`skills/clodex/runner/`) executes every Codex call:
repo-root anchored, prompt transported by file (never shell strings), per-role
state directories, full output capture, heartbeat for long runs, resumable
after interruption (including quota stalls — record checkpoint, surface a
one-command resume).

Every role invocation returns a **result envelope** (versioned JSON): invocation
ID, role, status (`complete` / `partial` / `failed` / `interrupted`), hashes of
the input artifacts it reviewed, findings with IDs, exit metadata, and paths to
full output. Stages transition only on a valid `complete` envelope — a missing,
malformed, or partial envelope fails closed and the stage surfaces it rather
than inferring success from prose.

## Human-owned decisions (never automated)

Product direction and subjective acceptance · destructive or irreversible
actions · live-data mutation and new security/privacy boundaries · accepting
non-empty verification debt at ship · external publication and client-facing
sends · overriding unresolved review findings.

## Deferred to v0.2 (deliberately)

Audit, repair, chore, and sync lanes (router notices and hands off manually
today); risk-scored / sampled code review (instrument first); approval queue
for asynchronous gates; persistent human-task ledger. Each enters only with
usage evidence from v0.1 runs — the study's clearest lesson is that unused
stages rot.

## v0.1 success criteria (pilot gate)

One real feature in a personal repository runs the full core path with:
manifest present and honest at every stage; zero transcript-string
reconstruction needed to answer "what happened"; release closed with verified
live state or an explicit boundary; fewer human gates than the TRIP baseline
for equivalent work; no runner incident traceable to cwd, prompt transport, or
lost state.

## Attribution

Clodex descends from the TRIP workflow by PiLastDigit (MIT) — the stage
vocabulary and the Codex review arms originate there. This design also adapts
ideas consistent with the author's usage study; no study content (which
includes private client material) appears in this repository.
