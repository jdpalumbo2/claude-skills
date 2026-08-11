---
name: clodex
description: Use when any development work starts in a repository — a feature request, a dense brief, a bug fix, "continue where we left off", or an ask whose shape is unclear. Also use when a repo has a .clodex/ directory with an unfinished run, and before invoking clodex-plan, clodex-build, clodex-verify, or clodex-ship.
---

# clodex — the front door

## Overview

One entry point for all work, so nobody has to remember stage names. This skill
runs five things in order and then hands off:

1. **Preflight** — prove the environment before a stage burns tokens on it.
2. **Open-run detection** — a run already in flight is resumed, never
   overwritten.
3. **Profile** — load `.clodex/profile.json`, or interview once and write it.
4. **Lane classification** — feature-shaped work enters the core path; every
   other shape is named and handed back, because those lanes are v0.2.
5. **Change boundary** — record what was already dirty, and never let the run
   commit someone else's work.

Then it opens the run and hands to a stage skill.

This skill does not edit code, does not call Codex, and does not run release
actions. The stage skills own all three.

## Paths and commands

```bash
CLODEX_HOME="${CLODEX_HOME:-$HOME/.claude/skills/clodex}"  # the dir holding this SKILL.md
STATE="$CLODEX_HOME/state/clodex_state.py"
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"    # do this, do not just assume it
REMOTE="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null | cut -d/ -f1 || true)"
[ -n "$REMOTE" ] || REMOTE="$(git remote | head -1)"   # empty = this repo has no remote
```

Shell variables do not survive between separate command invocations, so
**re-establish this block at the top of any shell you run these procedures in**.
Later sections use `$REPO`, `$STATE`, and `$REMOTE` as if it were already there.

**Every command below runs from `$REPO`.** `git check-ignore`, the repo
inspection in §3, and `git add` all resolve relative paths against the current
directory, so from a subdirectory they answer the wrong question — a correct
`.gitignore` reads as missing. If a step cannot `cd`, use `git -C "$REPO" …`.

| Thing | Path | Committed? |
|---|---|---|
| Run-state engine | `$STATE` | catalogue |
| Profile schema | `$CLODEX_HOME/profile.schema.json` | catalogue |
| Codex runner (stages only, never here) | `$CLODEX_HOME/runner/run-codex.sh` | catalogue |
| Repo profile | `$REPO/.clodex/profile.json` | **yes** |
| Run directory | `$REPO/.clodex/<run-id>/` (`$RUN_DIR` below) | **no — gitignored** |

A run's state is its directory: `events.ndjson` is an append-only event log and
is **the** record of what happened; `run.json` is a snapshot derived from it by
replaying the log; `lock.json` says which session owns the run; `write.lock`
serializes writes and is not something you reason about. You add to a run only
by appending an event.

Engine commands (payloads travel on **stdin**, never argv):

```bash
python3 "$STATE" status  "$RUN_DIR"          # human summary, incl. the lock line
python3 "$STATE" rebuild "$RUN_DIR"          # full snapshot JSON
python3 "$STATE" append  "$RUN_DIR" < event.json
python3 "$STATE" unlock  "$RUN_DIR"          # dead holder only; refuses a live one
```

`append` exit codes: `0` written · `1` refused, nothing written, safe to retry ·
`2` usage · `3` the event is durably logged but `run.json` is stale. On `3` the
event **counts** — it is in the log and the reducer applies it — so **do not
retry** (that would double-write). Run `rebuild` to refresh the snapshot and
carry on from the event you just appended.

---

## 1. Preflight — before any stage runs

Run every check. A failed check stops here; do not "proceed and see." Preflight
results are reported in chat, not logged as events — the durable part is
recorded in `run:opened` (§6).

**When a check fails**, the invocation does not end: name the check, say exactly
what would fix it, and wait for the user. When they say it is fixed, **resume
from that check** — re-run it and continue down the list. Do not silently re-run
the checks that already passed, and do not skip the ones after it.

**Order on a first run:** checks 4 and 6 read the profile, which does not exist
yet. Do checks 1–3 and 5, run the interview (§3), then come back and finish 4
and 6. A first run also has no `.clodex/` directory, so §2 finds nothing and
costs one `ls`.

1. **Repo root.** `git rev-parse --show-toplevel`. Not inside a work tree → stop
   and ask where the work lives. Also note the branch: `git rev-parse
   --abbrev-ref HEAD`.
2. **Remote state.** `$REMOTE` comes from the preamble — the remote is not
   always named `origin`, and halting a workflow over a hardcoded name is a
   self-inflicted outage:
   ```bash
   if [ -n "$REMOTE" ]; then
     git ls-remote --exit-code "$REMOTE" HEAD >/dev/null
   else
     echo "no remote configured"
   fi
   git status -sb | head -1                       # ahead/behind
   ```
   `ls-remote` proves the remote is reachable *and* that credentials work.
   Report divergence now — a repo behind its remote gets resolved before
   planning, never at ship. "No remote configured" is a **pass**, not a failure:
   say so out loud, because ship will have no push step.
3. **`.clodex/` ignore rule.** Run state must never be committed; the profile
   must be:
   ```bash
   git check-ignore -q .clodex/ANY-RUN-ID/events.ndjson  # expect exit 0 (ignored)
   git check-ignore -q .clodex/profile.json              # expect exit 1 (NOT ignored)
   ```
   `check-ignore` tests the path against the ignore rules, so neither path has to
   exist and `ANY-RUN-ID` is a stand-in, not a reserved name. Exit 1 on the
   second probe is the **pass**, not an error — run them as two separate commands
   so a shell with `set -e` cannot swallow the result.
   Either result wrong → show the user exactly these lines and add them to
   `.gitignore` only after they agree:
   ```
   .clodex/*
   !.clodex/profile.json
   ```
4. **Runtimes.** For each entry in the profile's `runtimes`: `command -v
   <command>`, plus the version check when `min_version` is set. Missing runtime
   → stop; it fails later and more expensively inside a stage. An empty list is
   a legal answer (this repo pins no runtimes); a *missing* `runtimes` key is a
   profile that never answered the question — go fix it in §3.
5. **Codex auth.** `command -v codex`, then `codex login status` (expect exit 0
   and a logged-in line). Codex is not optional: plan review is default-on and
   build delegates to it. Not logged in → stop and ask the user to run
   `codex login`.
6. **Credentials.** For each name in the profile's `required_env`:
   ```bash
   printenv "$NAME" >/dev/null || echo "missing credential: $NAME"
   ```
   Names only. Never print, echo, log, or write a credential value.

---

## 2. Is a run already open?

```bash
ls -1d "$REPO"/.clodex/r-*/ 2>/dev/null
python3 "$STATE" status "$REPO/.clodex/<run-id>"
```

A run is **open** when `status` shows a `stage:` other than `closed`.

`stage: -` is not an open run — it is a directory that never got its
`run:opened` event, left by a session that died in the window §6 opens between
`mkdir` and the first append. It has no brief, lane, or start commit, so there
is nothing to resume. Close it out and open a new run:
`echo '{"e":"run:closed"}' | python3 "$STATE" append "$RUN_DIR"` (legal on an
empty log; it yields `stage: closed`).

**v0.1 allows one open run per repo.** If you find two, the older is the one
whose run id sorts first — the ids are `r-<date>-<letter>`, so plain
lexicographic order is chronological. Resume it, or close it with the same
`run:closed` append, before opening anything new.

`status` also prints a `lock:` line when `lock.json` exists. That line decides
what you may do:

| `status` shows | What it means | What to do |
|---|---|---|
| no `lock:` line | no write is in flight and no writer died mid-write | Offer resume (below); an `append` will be accepted. This is the *normal* state even while another session is working, because the lock is taken per write and released — so a missing lock line is not proof you are alone. The one-open-run rule and the user's answer to the resume offer are what actually keep two agents off one run. |
| `lock: held by pid N (not running) since …` | a session died mid-write | Offer resume-or-abort. On resume: `python3 "$STATE" unlock "$RUN_DIR"` — plain `unlock` succeeds only for a dead holder, which is exactly this case — then resume. Never `--force` here. |
| `lock: … (running)` or `… (liveness unknown)` | another session owns the run, or a write is in flight right now. *Unknown* means the lock carries no usable PID — including a lock caught in the instant between its creation and its payload write, whose holder is very much alive | **Do not write.** Name the PID to the user. `unlock` will refuse. Only after the user confirms that process is gone may you run `unlock --force`. Otherwise abort here and let the other session finish. |

**Who may write run state while the lock is held:** only the holder, plus
processes the holder spawned carrying the `CLODEX_LOCK_TOKEN` environment
variable, which the engine exports to its children so they can write as the same
owner. Every other session's `append` is refused — exit 1, nothing written. You
never create or hand-edit `lock.json`, and there is no `acquire` verb: the engine
takes the session lock around each write itself. A dead holder's lock is **never**
broken implicitly; breaking it is this skill's decision, made with the user.

**The resume offer.** From `status` (and `rebuild` for fields `status` does not
print, such as `brief`), tell the user in one message: the run id and lane, the
brief, the current stage, plan version and amendment count, open findings,
verification debt, release state and any pending step. Then offer these three —
**and lead with the one the situation calls for, not always Resume**:

- **Close** → append `{"e": "run:closed"}`. Lead with this, and say plainly that
  it is the answer, whenever the run reached you as a **hand-back from a stage
  skill asking for closure** — `clodex-verify` does that when verification
  fails, so a follow-on run can carry this run's id as its `parent` (§6). Such a
  run is still open at its stage, so offering Resume first walks the user
  straight back into the loop the hand-back exists to escape. Follow the
  handing-back skill's stated procedure; do not improvise a substitute here.
- **Resume** → hand to the stage skill for the current stage (§6 table). If
  `release:` shows a pending step, do **not** retry it here: clodex-ship
  reconciles pending steps against reality before any retry.
- **Abandon** → append `{"e": "release:updated", "state": "abandoned"}`, then
  `{"e": "run:closed"}`.

Never delete a run directory to get out of this. The log is the record of what
happened.

---

## 3. Profile — load, or interview once

`$REPO/.clodex/profile.json` is committed state: it is how a repo tells clodex
how to build, test, version, release, and verify itself.

**It exists** → load it and validate it:

```bash
python3 - "$CLODEX_HOME" "$REPO" <<'PY'
import importlib.util, json, os, sys
home, repo = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location(
    "clodex_state", os.path.join(home, "state", "clodex_state.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
mod.validate(json.load(open(os.path.join(repo, ".clodex", "profile.json"))),
             json.load(open(os.path.join(home, "profile.schema.json"))))
print("profile ok")
PY
```

On success that prints `profile ok` and exits 0. On failure it exits 1 with a
traceback whose **last line names the offending path** — e.g.
`ClodexStateError: $.actions[0].policy: 'auto' is not an allowed value`. Report
that path and message to the user verbatim; it is the fastest fix instruction
there is.

It checks types, required fields, and enums. It does **not** check
`additionalProperties`, `pattern`, or `minItems` — so an unknown key, a
malformed action id, and an action with an empty `argv` all survive it. Read the
file yourself as well.

Two things send you back to the user: a **missing** key the schema requires, and
a **stale** profile — one whose `schema_version` is not the version
`profile.schema.json` accepts, which is the only mechanical signal that the
contract moved. Ask for just those keys and rewrite **only** those keys.
Non-destructive: never regenerate the file wholesale, never drop `notes`.

**It does not exist** → first-run interview:

1. **Inspect before asking.** Anything you can read, do not ask about:
   ```bash
   ls; sed -n '1,60p' package.json 2>/dev/null      # scripts, engines, version
   ls Makefile pyproject.toml tox.ini vercel.json railway.json fly.toml Dockerfile 2>/dev/null
   ls .github/workflows docs 2>/dev/null
   cat .nvmrc .tool-versions .python-version 2>/dev/null   # pinned runtimes
   git tag --sort=-v:refname | head -5
   git symbolic-ref --short "refs/remotes/${REMOTE:-origin}/HEAD" 2>/dev/null
   ```
   **Fill in `runtimes` and `commands.install` here** — preflight check 4 loops
   over `runtimes`, so a profile without it makes that check a permanent no-op.
   `package.json` `engines`, `.nvmrc`, `.tool-versions`, and `pyproject.toml`
   `requires-python` give you `command` and `min_version` without asking anyone.
2. **Ask once, in one message**, only what inspection cannot settle or what is a
   decision rather than a fact: confirm the build/test/lint/typecheck commands
   (`null` where the repo genuinely has none — an omitted gate gets silently
   skipped at verify) and the runtimes you inferred; version source; branch rule
   and tag format; changelog path; architecture docs and where plans go; deploy
   target and the exact command that proves a release is live; default evidence
   classes; which release actions clodex may take; the **names** of required env
   vars.

   What those terms mean, so you can answer "what are my options?":
   - **Version source** — the file that holds the authoritative version, and the
     key inside it. Typically `package.json` → `version`, or `pyproject.toml` →
     `project.version`, or a bare `VERSION` file. `null` if the repo is
     unversioned.
   - **Branch rule** — whether a run may commit straight to the default branch
     (`main`, `work_on_default: true`) or must work on its own branch
     (`work_on_default: false` plus a naming pattern like `feature/<slug>` or
     `clodex/<run-id>`).
   - **Tag format** — the pattern a release tag follows, e.g. `v{version}`
     producing `v1.4.0`; or tagging off entirely (`enabled: false`).
   - **Deploy target** — where a release actually lands and how it gets there:
     a host and project auto-deploying on push to the default branch, a manual
     command listed in `actions`, something external, or nothing at all
     (`deploy: null` — ship then closes at an explicit not-deployed boundary).
   - **Evidence classes** — the four kinds of proof a plan can require;
     `evidence.default_classes` is which of them this repo expects by default:
     `tests` (automated suites), `real-data` (run against production-shaped
     input), `live-check` (the deployed thing observed working), `visual`
     (rendered output reviewed). `clodex-plan` owns the per-plan detail.
3. **Action policy is structured, per action.** Every entry in `actions` carries
   a literal `argv` and a `policy`:
   - `auto-with-authorization` — may run once it is covered by the single
     consolidated release authorization: the one message in which `clodex-ship`
     enumerates every external action a release will take and the user approves
     the set.
   - `always-ask-exact` — the literal filled argv is presented for approval
     **every time, in every run**. Use this for destructive or irreversible
     actions, and for repos with their own guardrail tiers (an infra control
     plane marks its red-tier actions this way).

   Unsure → `always-ask-exact`. Nothing outside `actions` may be proposed at
   ship; a new action gets added to the profile and committed first. A complete
   entry — `{braced}` placeholders are filled from run state before the argv is
   shown or run:
   ```json
   {"id": "push-main",
    "argv": ["git", "push", "origin", "main"],
    "cwd": null,
    "target": "origin/main",
    "env_refs": [],
    "policy": "auto-with-authorization"}
   ```
   The remaining three fields: `cwd` is the repo-relative directory the command
   runs in, `null` meaning the repo root; `target` names what the action affects
   in plain words, so a user approving it can see the blast radius without
   parsing argv; `env_refs` lists the **names** of credentials the action needs,
   never values, and `[]` when it needs none. The same repo would mark a
   production deploy `always-ask-exact`, so its literal filled argv is shown for
   approval on every release.
4. **Write, validate, commit.** Write every required key — the schema requires
   `runtimes` and `required_env` (use `[]` for "none", never omit them) and every
   key of `commands` including `install`, precisely so preflight checks 4 and 6
   have something to check. Re-run the validator above, then commit **by
   pathspec**, because the tree — and the index — may hold the user's unrelated
   work:
   ```bash
   git add .clodex/profile.json && git commit -m "chore(clodex): repo profile" -- .clodex/profile.json
   ```
   The trailing `-- .clodex/profile.json` is the load-bearing part. A bare
   `git commit -m` commits **everything already staged**, so anything the user or
   another tool had in the index rides along inside a commit labelled as a
   profile write. With the pathspec, the commit can hold only that one file and
   the rest of the index is left exactly as it was. The `git add` is still
   required — a pathspec cannot name a file git does not yet know about.

   This is the only commit this skill makes. Never `git add -A`, `git add .`, or
   `git commit -a`. Ever.
5. **`notes` is inert.** It is free-form text for humans and nothing in clodex
   reads it. Anything that must change what clodex *does* goes in a typed field.

Field-by-field contract: `$CLODEX_HOME/profile.schema.json`.

---

## 4. Classify the ask

| Shape | The ask looks like | v0.1 |
|---|---|---|
| **feature** | new or changed behavior someone can observe — a capability, an enhancement, a behavior-changing bug fix | **core path** |
| audit | "review / inventory / assess X across the repo", no change requested yet | lane not built |
| repair | recovering a broken state — failed deploy, environment drift, corrupted data | lane not built |
| chore | mechanical, no product decision — dependency bumps, renames, formatting, test backfill, config sync | lane not built |
| sync | making two places agree — docs↔code, env↔env, fork↔upstream, inventory↔reality | lane not built |

**Feature-shaped** → continue to §5, open the run, hand to `clodex-plan`.

**Anything else** → the noticing rule. Say exactly three things and stop:

1. Name the shape: "This is chore-shaped work — a mechanical change with no
   product decision in it."
2. Say the lane is not built: "clodex v0.1 has no chore lane; audit, repair,
   chore, and sync are deferred to v0.2."
3. Propose the closest manual approach, concretely — the actual commands, files,
   or sequence you would use, not a category.

Then **do not open a run.** There is no stage skill to drive a non-feature lane,
and an open run nothing can advance is worse than none. If the user accepts the
manual approach, do that work as ordinary work: no run directory, no manifest,
no clodex events.

Mixed asks ("audit the config, then fix it") classify by what the user wants
*done*. If the fix is feature-shaped and specified, run the core path on the fix
and handle the audit part manually.

---

## 5. The change boundary

### A. At open — acknowledge what is already dirty

```bash
START_HEAD="$(git rev-parse HEAD)"                # recorded as git.start_head
git status --porcelain --untracked-files=all      # the dirty snapshot
```

`--untracked-files=all` (`-uall`) is not optional. Plain `git status --porcelain`
collapses an untracked directory into one entry — `?? docs/` — but everything
downstream treats `git.dirty_at_start` as a list of **files**, and a directory
entry breaks the change boundary in both directions. §5B asks whether a dirty
path *is* an owned path or sits under one, which an acknowledged **ancestor**
like `docs/` never satisfies: a batch owning `docs/plans/` sees no overlap, and
the user's pre-existing `docs/plans/older-draft.md` lands in the batch commit —
the exact outcome this section exists to prevent. Compared the other way, every
file under an acknowledged directory reads as an unowned stray and falsely
halts the run. `-uall` records the files themselves, so neither happens.

Record each entry as a **repo-relative file path with the status prefix
stripped**. Porcelain lines are `XY<space>path`, so take everything from the
fourth character on: ` M src/app.ts` → `src/app.ts`, `?? docs/plans/draft.md` →
`docs/plans/draft.md`. No status letters, no trailing slashes, no directories.
For a staged rename (`R  old -> new`) record the new path. A path containing a
space or a quote comes back C-quoted (`"a b.txt"`); if you hit one, re-run with
`-z` and split the NUL-separated output instead of unquoting by hand.

Show the user every dirty path. They acknowledge the list, or **the run does not
open**. The acknowledged paths go into `run:opened` as `git.dirty_at_start`
(§6). A clean tree records `[]`.

### B. Before build — when a dirty path overlaps an owned path

**Who runs this and when:** not the router. The router's pass ends at §6, and
owned paths do not exist yet at that point. `clodex-build` re-reads this section
**before opening its first batch**, comparing the plan's owned paths against
`git.dirty_at_start` in the run snapshot. Running it earlier does not work
mechanically either: the `approval:granted` event below binds to a plan hash, so
the reducer refuses it — exit 1, *"approval must bind to a plan hash; none given
and no plan is recorded"* — until `clodex-plan` has recorded a plan.

A **batch** is one bounded unit of implementation work with a declared list of
**owned paths** — the only paths that batch may touch. `clodex-plan` declares
them. A dirty path overlaps when it *is* an owned path or sits under one, which
is a sound test only because §A recorded files: if you find a directory entry in
`git.dirty_at_start` — an older run, or a hand-edited snapshot — expand it with
`git status --porcelain --untracked-files=all` before comparing, or an ancestor
entry will match nothing and let a pre-existing file through. There are exactly
**three legal outcomes**:

1. **Fold with acknowledgment.** The pre-existing edit will end up inside a
   clodex commit, so capture it into the run directory *first* and get the user
   to say so out loud:
   ```bash
   git diff -- <overlapping tracked paths> > "$RUN_DIR/pre-existing.diff"
   git diff --stat -- <overlapping tracked paths>          # show the user
   # untracked overlaps are absent from git diff — copy them instead:
   for f in <overlapping untracked paths>; do
     mkdir -p "$RUN_DIR/pre-existing/$(dirname "$f")"
     cp -p "$f" "$RUN_DIR/pre-existing/$f"
   done
   ```
   Then record the acknowledgment as an event (a plan is recorded by now, so the
   approval binds to it):
   ```json
   {"e": "approval:granted", "scope": "dirty-fold", "by": "user",
    "actions": [{"id": "fold-pre-existing", "paths": ["src/x/thing.ts"],
                 "captured": ".clodex/<run-id>/pre-existing.diff"}]}
   ```
2. **Isolate in a clean worktree.**
   ```bash
   git worktree add ../<repo>-clodex-<run-id> -b clodex/<run-id> "$START_HEAD"
   ```
   Re-run this skill from the worktree: fresh preflight, clean tree, new run. If
   a run was already open in the dirty checkout, close it (§2) and set the new
   run's `parent` to the closed run's id.
3. **Abort.** Do not open or continue the run. Tell the user what would unblock
   it — commit, stash, or move their work — and stop.

**Hard rules, no fourth option:**

- Path-level ownership never blurs file-level provenance. Owning `src/x/` does
  not entitle a commit to a pre-existing edit to `src/x/thing.ts`. That file is
  folded, isolated, or the run aborts.
- Never run `git add -A`, `git add .`, `git commit -a`, `git stash`, or
  `git checkout -- <path>` on the user's behalf.
- Ship stages only paths owned by the run's batches. Unrelated work in the tree
  is never swept into a clodex commit.

---

## 6. Open the run, then hand off

```bash
DATE="$(date -u +%Y-%m-%d)"
RUN_ID=""
for L in a b c d e f g h; do
  [ -e "$REPO/.clodex/r-$DATE-$L" ] && continue
  RUN_ID="r-$DATE-$L"; break                  # first free letter for today
done
if [ -z "$RUN_ID" ]; then
  RUN_DIR=""
  echo "no free run id for $DATE — stop, do not open a run"
else
  RUN_DIR="$REPO/.clodex/$RUN_ID"
  mkdir -p "$RUN_DIR"
fi
```

The guard is inside the block on purpose. An unguarded empty `$RUN_ID` makes
`$REPO/.clodex/$RUN_ID` expand to `$REPO/.clodex/` itself, and the append then
writes `events.ndjson` and `run.json` **beside `profile.json`**, where §2's
`ls -1d "$REPO"/.clodex/r-*/` will never find them. If you see that message,
**stop and tell the user**: eight runs in one day means something is wrong, and
appending into an existing run directory would corrupt someone else's history.

Write the event to `$RUN_DIR/run-opened.json` with your file-writing tool, not
shell interpolation — the brief is verbatim user text and will contain quotes:

```json
{"e": "run:opened",
 "run": "r-2026-08-10-b",
 "parent": null,
 "repo": "/absolute/path/to/repo",
 "branch": "main",
 "brief": "<the ask, verbatim>",
 "lane": "feature",
 "git": {"start_head": "<git rev-parse HEAD>",
         "dirty_at_start": ["src/app.ts", "docs/plans/older-draft.md"]}}
```

Two fields need a decision rather than a copy:

- **`parent`** is `null` for ordinary new work, but **not** when the ask reached
  you as a hand-back from a stage skill naming a prior run. A run cannot be sent
  backwards — stage order is monotonic — so a stage that needs earlier work
  redone closes its run and asks for a follow-on; `clodex-verify` does exactly
  this when verification fails. In that case `parent` is the closed run's id,
  copied verbatim from the hand-back sentence: `"parent": "r-2026-08-10-a"`. It
  is the only link between the two runs, so a `null` here silently orphans the
  history. The §5B worktree path is the same shape: the new run's `parent` is the
  run you closed in the dirty checkout.
- **`dirty_at_start`** is file paths only — never `"docs/"` — for the reasons in
  §5A.

```bash
python3 "$STATE" append "$RUN_DIR" < "$RUN_DIR/run-opened.json"   # stdin, never argv
rm -f "$RUN_DIR/run-opened.json"
```

The engine stamps `schema_version`, `seq`, and `t` — do not supply them. On a
non-zero exit, read the error on stderr and act on the exit codes above: `1`
covers a locked run, a bad payload, and a reducer invariant alike, and they need
different responses.

Then invoke the stage skill, telling it the absolute run directory — it reads
everything else from the run itself ("clodex-plan, run dir
`/absolute/path/to/repo/.clodex/r-2026-08-10-a`"):

| Stage in `status` | Hand to |
|---|---|
| `open`, `plan` | `clodex-plan` |
| `build` | `clodex-build` |
| `verify` | `clodex-verify` |
| `ship` | `clodex-ship` |

The router does **not** append `stage:*:entered`. Each stage skill appends its
own entry event, so the log never claims a stage that did not start.

---

## Common mistakes

| Mistake | Instead |
|---|---|
| Inventing an event name | The vocabulary is frozen at 23 names and the reducer refuses anything else; the full list is the `e` enum in `$CLODEX_HOME/state/schemas/event.schema.json`. This skill appends only four of them: `run:opened`, `run:closed`, `release:updated`, `approval:granted`. |
| Hand-editing `run.json` | It is derived. Append an event; `rebuild` regenerates it. |
| Building an audit/repair/chore/sync lane on the fly | Name the shape, say it is v0.2, propose the manual approach (§4). |
